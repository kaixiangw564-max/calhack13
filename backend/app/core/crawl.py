"""Trigger and inspect Apify crawls (apify-client 3.x).

Full-site page text comes from Apify's Website Content Crawler (WCC).
"""
from datetime import timedelta
from functools import lru_cache
from typing import Iterator
from urllib.parse import urlparse

from apify_client import ApifyClient

from .config import env

WCC_ACTOR = "apify/website-content-crawler"
MIN_TEXT_CHARS = 200  # pages shorter than this are treated as having no real content


@lru_cache(maxsize=1)
def client() -> ApifyClient:
    return ApifyClient(env("APIFY_TOKEN", required=True))


def site_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host.removeprefix("www.")


def wcc_input(start_url: str, max_pages: int) -> dict:
    return {
        "startUrls": [{"url": start_url}],
        # Government sites here are server-rendered; plain HTTP is fastest and cheapest.
        "crawlerType": "cheerio",
        "maxCrawlPages": max_pages,
        "maxCrawlDepth": 5,
        "respectRobotsTxtFile": True,
        "excludeUrlGlobs": [
            {"glob": "**/wp-content/uploads/**"},  # disallowed by dmv.ca.gov robots.txt
            {"glob": "**/wp-admin/**"},
            {"glob": "**/feed/**"},
            {"glob": "**/*?s=*"},
        ],
        "saveMarkdown": True,
    }


def _status(run) -> str:
    return str(getattr(run.status, "value", run.status))


def start_crawl(start_url: str, max_pages: int, webhook_url: str | None = None) -> dict:
    """Start a WCC run without waiting. Returns {run_id, status, dataset_id}."""
    webhooks = None
    if webhook_url:
        webhooks = [{"event_types": ["ACTOR.RUN.SUCCEEDED"], "request_url": webhook_url}]
    run = client().actor(WCC_ACTOR).start(
        run_input=wcc_input(start_url, max_pages),
        memory_mbytes=2048,
        run_timeout=timedelta(minutes=30),
        webhooks=webhooks,
    )
    return {"run_id": run.id, "status": _status(run), "dataset_id": run.default_dataset_id}


def get_status(run_id: str) -> dict:
    """Returns {status, pages_done, dataset_id, usage_usd}."""
    run = client().run(run_id).get()
    if run is None:
        return {"status": "NOT_FOUND", "pages_done": 0, "dataset_id": None, "usage_usd": None}
    dataset = client().dataset(run.default_dataset_id).get()
    return {
        "status": _status(run),
        "pages_done": getattr(dataset, "item_count", 0) or 0,
        "dataset_id": run.default_dataset_id,
        "usage_usd": run.usage_total_usd,
    }


def wait_for_run(run_id: str) -> dict:
    client().run(run_id).wait_for_finish()
    return get_status(run_id)


def latest_succeeded_run() -> dict | None:
    """Most recent successful WCC run on this account: {run_id, dataset_id, finished_at}."""
    run = client().actor(WCC_ACTOR).last_run(status="SUCCEEDED").get()
    if run is None:
        return None
    return {"run_id": run.id, "dataset_id": run.default_dataset_id, "finished_at": run.finished_at}


def iter_pages(dataset_id: str) -> Iterator[dict]:
    """Normalized pages with real content: {site, url, title, text, crawled_at}."""
    for item in client().dataset(dataset_id).iterate_items(clean=True):
        text = (item.get("text") or "").strip()
        if len(text) < MIN_TEXT_CHARS:
            continue
        url = item.get("url") or item.get("crawl", {}).get("loadedUrl")
        yield {
            "site": site_of(url),
            "url": url,
            "title": (item.get("metadata") or {}).get("title") or url,
            "text": text,
            "markdown": item.get("markdown") or text,
            "crawled_at": (item.get("crawl") or {}).get("loadedTime"),
        }
