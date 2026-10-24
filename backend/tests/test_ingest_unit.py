"""Offline tests for ingest/retrieval helpers and the webhook route (no database or network)."""
from fastapi.testclient import TestClient

from app import main
from app.core import ingest, retrieval


def test_normalize_form_number():
    assert ingest.normalize_form_number("REG 195") == "REG195"
    assert ingest.normalize_form_number("reg-195") == "REG195"
    assert ingest.normalize_form_number("DL 44") == "DL44"
    assert ingest.normalize_form_number(None) is None
    assert ingest.normalize_form_number("Application") is None


def test_form_numbers_in_question_only_known_prefixes():
    known = {"REG", "DL"}
    assert retrieval.form_numbers_in("What is REG 195 and dl-44?", known) == ["REG195", "DL44"]
    assert retrieval.form_numbers_in("Mail to Sacramento, CA 94269", known) == []


def test_canonical_urls_prefers_www_when_present():
    urls = ["https://dmv.ca.gov/portal/a/", "https://www.dmv.ca.gov/portal/b/", "https://other.gov/x"]
    canon = ingest.canonical_urls(urls)
    assert canon["https://dmv.ca.gov/portal/a/"] == "https://www.dmv.ca.gov/portal/a/"
    assert canon["https://other.gov/x"] == "https://other.gov/x"


def test_common_title_suffix():
    titles = ["REAL ID - California DMV", "Placards - California DMV", "Home"]
    assert ingest.common_title_suffix(titles) == " - California DMV"
    assert ingest.common_title_suffix(["A - X", "B - Y", "C"]) is None


def test_chunk_markdown_splits_by_heading_and_strips_links():
    md = (
        "Intro paragraph about placards that is long enough to stand alone as its own chunk of text here.\n\n"
        "## Applying\n\n- Complete [REG 195 (PDF)](https://www.dmv.ca.gov/portal/file/reg-195-pdf/).\n\n"
        "## Renewing\n\n" + ("Renew online. " * 200)
    )
    chunks = ingest.chunk_markdown(md, "Disabled Person Parking Placards")
    assert all(c.startswith("Disabled Person Parking Placards") for c in chunks)
    assert all(len(c) <= ingest.MAX_CHUNK_CHARS + 200 for c in chunks)
    assert any("Complete REG 195 (PDF)." in c for c in chunks)
    assert not any("https://" in c for c in chunks)
    assert any("## Renewing" in c for c in chunks)


def test_form_chunk_text_contains_number_url_and_fields():
    text = ingest.form_chunk_text(
        {
            "number": "REG 195",
            "name": "Application for Disabled Person Placard or Plates (REG 195)",
            "url": "https://www.dmv.ca.gov/portal/file/reg-195-pdf/",
            "source_pages": [{"url": "https://www.dmv.ca.gov/portal/dpp/", "title": "DP Placards", "service": "Applying for a DP Placard"}],
            "description": "Use this form to apply for a disabled person placard.",
            "fields": ["DL No", "Date of birth"],
        }
    )
    assert text.startswith("Form REG 195: Application for Disabled Person Placard")
    assert "https://www.dmv.ca.gov/portal/file/reg-195-pdf/" in text
    assert "Applying for a DP Placard" in text and "DL No" in text


def test_webhook_rejects_missing_or_wrong_secret(monkeypatch):
    monkeypatch.setenv("APIFY_WEBHOOK_SECRET", "s3cret")
    client = TestClient(main.app)
    assert client.post("/webhook/apify", json={}).status_code == 401
    assert client.post("/webhook/apify", json={}, headers={"X-PlainPath-Webhook-Secret": "nope"}).status_code == 401


def test_webhook_schedules_ingest_for_succeeded_run(monkeypatch):
    monkeypatch.setenv("APIFY_WEBHOOK_SECRET", "s3cret")
    calls = []
    monkeypatch.setattr(main, "_ingest_run", lambda *args: calls.append(args))
    client = TestClient(main.app)
    payload = {"eventType": "ACTOR.RUN.SUCCEEDED", "resource": {"id": "run1", "actId": "act1", "status": "SUCCEEDED", "defaultDatasetId": "ds1"}}
    r = client.post("/webhook/apify", json=payload, headers={"X-PlainPath-Webhook-Secret": "s3cret"})
    assert r.status_code == 200 and r.json() == {"ok": True, "ingest": "started"}
    assert calls == [("act1", "run1", "ds1")]


def test_health():
    assert TestClient(main.app).get("/health").json() == {"ok": True}
