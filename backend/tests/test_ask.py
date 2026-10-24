"""Step 6 acceptance: POST /ask with Chinese questions returns cited steps; an unrelated question is not_found.

Needs the populated Atlas database (step 5) and Bitdeer credentials. Chinese inputs are written as
Unicode escapes so the source stays ASCII-only.
"""
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
SITE = "dmv.ca.gov"
CJK = re.compile("[\\u4e00-\\u9fff]")

CHINESE_QUESTIONS = [
    # "I want to renew my disabled parking placard. What do I do?"
    ("\u6211\u60f3\u7eed\u529e\u6b8b\u75be\u4eba\u505c\u8f66\u8bc1\uff0c\u8981\u600e\u4e48\u505a\uff1f", ("dpp", "disabled-person")),
    # "What documents do I need to bring for a REAL ID?"
    ("\u529e REAL ID \u9700\u8981\u5e26\u54ea\u4e9b\u6750\u6599\uff1f", ("real-id",)),
    # "I moved. How do I update my address with the DMV?"
    ("\u6211\u642c\u5bb6\u4e86\uff0c\u600e\u4e48\u5728 DMV \u66f4\u65b0\u5730\u5740\uff1f", ("address", "updating-information")),
]
# "How do I apply for a California fishing license?" (handled by CDFW, not the DMV)
UNRELATED_QUESTION = "\u600e\u4e48\u7533\u8bf7\u52a0\u5dde\u9493\u9c7c\u6267\u7167\uff1f"


def ask(question: str, language: str = "zh") -> dict:
    r = client.post("/ask", json={"question": question, "language": language, "site": SITE})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("question,expected_url_parts", CHINESE_QUESTIONS)
def test_chinese_question_returns_cited_steps(question, expected_url_parts):
    body = ask(question)
    assert body["not_found"] is False
    assert len(body["steps"]) >= 2
    for step in body["steps"]:
        assert step["text"] and CJK.search(step["text"]), step  # answered in Chinese
        assert step["source_url"].startswith("https://www.dmv.ca.gov/"), step
        assert step["crawled_at"], step
    for item in body["steps"] + body["documents"]:
        assert not re.search(r"\[\d+\]", item["text"]), item  # citation markers replaced by source_url
    sources = [s["source_url"].lower() for s in body["steps"]]
    assert any(part in url for url in sources for part in expected_url_parts), sources
    assert CJK.search(body["disclaimer"])
    for form in body["forms"]:
        assert form["url"].startswith("https://www.dmv.ca.gov/") and form["crawled_at"]


def test_unrelated_question_is_not_found_with_contact():
    body = ask(UNRELATED_QUESTION)
    assert body["not_found"] is True
    assert body["steps"] == []
    assert CJK.search(body["message"])
    assert body["contact"]["url"].startswith("https://www.dmv.ca.gov/")


def test_form_number_question_returns_official_form_link():
    body = ask("What is form REG 195 used for?", "en")
    assert body["not_found"] is False
    assert any(f["number"] == "REG 195" and "reg-195" in f["url"] for f in body["forms"]), body["forms"]


def test_ask_validates_input():
    assert client.post("/ask", json={"question": ""}).status_code == 422
