"""Step 5 acceptance: vector search over Atlas returns relevant chunks (needs a populated database).

Run `python -m scripts.run_ingest` first.
"""
import pytest

from app.core import retrieval

SITE = "dmv.ca.gov"


def urls(results: list[dict]) -> list[str]:
    return [r["url"] for r in results]


@pytest.mark.parametrize(
    "question,expected_url_part",
    [
        ("How do I renew my disabled parking placard?", "disabled-person"),
        ("What documents do I need for a REAL ID?", "real-id"),
        ("I moved. How do I change my address with the DMV?", "address"),
        ("我想续办残疾人停车证", "disabled-person"),  # cross-lingual query against English pages
    ],
)
def test_vector_search_returns_relevant_chunks(question, expected_url_part):
    results = retrieval.vector_search(question, SITE, k=8)
    assert len(results) == 8
    assert all(r["site"] == SITE and r["url"].startswith("https://") and r["crawled_at"] for r in results)
    assert any(expected_url_part in u.lower() for u in urls(results[:5])), urls(results)


def test_form_number_exact_match_comes_first():
    results = retrieval.search("What is form REG 195?", SITE)
    assert results[0]["match"] == "form_number"
    assert results[0]["kind"] == "form"
    assert "reg-195" in results[0]["url"]
    assert "Fields to fill in" in results[0]["text"]


def test_form_chunk_found_by_meaning():
    results = retrieval.vector_search("Which form do I fill out to apply for a disabled person placard?", SITE, k=8, kind="form")
    assert any("reg-195" in u for u in urls(results)), urls(results)
