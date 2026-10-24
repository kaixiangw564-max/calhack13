"""Step 4 acceptance: the latest platform run of PlainPath Gov Extractor has >= 5 records in the section 6 format.

Run `python -m scripts.run_extractor` first; this test only reads the resulting dataset.
"""
from app.core import crawl

REQUIRED_KEYS = {"site", "url", "title", "service", "steps_raw", "required_documents", "forms", "locations", "fees", "crawled_at"}


def latest_records() -> list[dict]:
    run = crawl.latest_succeeded_run(crawl.extractor_actor_id())
    assert run is not None, "no successful extractor run yet; run scripts.run_extractor"
    return list(crawl.client().dataset(run["dataset_id"]).iterate_items())


def test_at_least_5_records_in_output_format():
    records = latest_records()
    assert len(records) >= 5
    for rec in records:
        assert REQUIRED_KEYS <= rec.keys()
        assert rec["url"].startswith("https://")
        assert rec["crawled_at"]
        assert isinstance(rec["required_documents"], list)
        for form in rec["forms"]:
            assert {"name", "url", "fields"} <= form.keys()


def test_reg_195_form_is_found_with_pdf_fields():
    forms = [f for rec in latest_records() for f in rec["forms"] if f.get("number") == "REG 195"]
    assert forms, "REG 195 not found in extractor output"
    parsed = [f for f in forms if f.get("pdf_status") == "parsed"]
    assert parsed and parsed[0]["fields"], forms[0]
