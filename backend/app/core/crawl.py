"""Trigger and inspect Apify crawls (apify-client 3.x).

Full-site page text comes from Apify's Website Content Crawler (WCC).
"""
import json
import re
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


WEBHOOK_SECRET_HEADER = "X-PlainPath-Webhook-Secret"


def ingest_webhooks() -> list[dict] | None:
    """Ad-hoc webhook that calls POST /webhook/apify when a run succeeds (needs a public BACKEND_PUBLIC_URL)."""
    base, secret = env("BACKEND_PUBLIC_URL"), env("APIFY_WEBHOOK_SECRET")
    if not base or not secret or "localhost" in base or "127.0.0.1" in base:
        return None
    return [
        {
            "event_types": ["ACTOR.RUN.SUCCEEDED"],
            "request_url": base.rstrip("/") + "/webhook/apify",
            "headers_template": json.dumps({WEBHOOK_SECRET_HEADER: secret}),
        }
    ]


def start_crawl(start_url: str, max_pages: int) -> dict:
    """Start a WCC run without waiting. Returns {run_id, status, dataset_id}."""
    webhooks = ingest_webhooks()
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


def extractor_actor_id() -> str:
    return env("APIFY_ACTOR_ID", required=True)


_SERVICE_HEADING_RE = re.compile(
    r"^#{1,4}\s*(apply|applying|renew|renewing|replace|replacing|how (do|to|can)|register|request|change|update|"
    r"transfer|what (you|to) (need|bring)|required|documents|checklist|eligib)",
    re.I | re.M,
)
_FORM_LINK_RE = re.compile(r"\]\([^)]*(/file/|\.pdf)[^)]*\)|\(PDF\)", re.I)


def service_page_urls(wcc_dataset_id: str) -> list[str]:
    """Pages from a Website Content Crawler dataset that look like service pages (form links or how-to headings)."""
    urls: list[str] = []
    for page in iter_pages(wcc_dataset_id):
        if _FORM_LINK_RE.search(page["markdown"]) or _SERVICE_HEADING_RE.search(page["markdown"]):
            if page["url"] not in urls:
                urls.append(page["url"])
    return urls


def start_extractor(start_urls: list[str], max_crawl_depth: int | None = 0, max_pdfs: int = 200) -> dict:
    """Start our custom Actor (PlainPath Gov Extractor). Returns {run_id, status, dataset_id}.

    Default pipeline: Website Content Crawler finds every page, then the extractor processes only
    the service pages it found (max_crawl_depth=0), so no budget is spent re-discovering the site.
    """
    run = client().actor(extractor_actor_id()).start(
        run_input={
            "startUrls": [{"url": u} for u in start_urls],
            "maxPagesPerCrawl": len(start_urls) if max_crawl_depth == 0 else 400,
            "maxCrawlDepth": max_crawl_depth,
            "maxPdfs": max_pdfs,
        },
        memory_mbytes=2048,
        run_timeout=timedelta(minutes=30),
        webhooks=ingest_webhooks(),
    )
    return {"run_id": run.id, "status": _status(run), "dataset_id": run.default_dataset_id}


def actor_full_name(actor_id: str) -> str | None:
    """'aYG0l9s7dbB7j3gbS' -> 'apify/website-content-crawler'."""
    actor = client().actor(actor_id).get()
    return f"{actor.username}/{actor.name}" if actor else None


def latest_succeeded_run(actor_id: str = WCC_ACTOR) -> dict | None:
    """Most recent successful run of an Actor on this account: {run_id, dataset_id, finished_at}."""
    run = client().actor(actor_id).last_run(status="SUCCEEDED").get()
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
