"""Step 3 acceptance: the latest Website Content Crawler run has >= 50 pages with real text.

Run `python -m scripts.run_crawl` first; this test only reads the resulting dataset.
"""
from app.core import crawl
from app.core.config import env


def test_wcc_input_respects_robots():
    run_input = crawl.wcc_input("https://www.dmv.ca.gov/portal/", 300)
    assert run_input["respectRobotsTxtFile"] is True
    assert run_input["maxCrawlPages"] == 300


def test_latest_crawl_has_50_content_pages():
    run = crawl.latest_succeeded_run()
    assert run is not None, "no successful crawl yet; run scripts.run_crawl"
    pages = list(crawl.iter_pages(run["dataset_id"]))
    assert len(pages) >= 50
    target_site = crawl.site_of(env("TARGET_START_URL", required=True))
    for page in pages:
        assert page["site"] == target_site
        assert page["url"].startswith("https://")
        assert page["crawled_at"]
        assert len(page["text"]) >= crawl.MIN_TEXT_CHARS
