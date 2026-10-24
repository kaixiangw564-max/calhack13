"""PlainPath Gov Extractor — Apify Actor entry point.

Crawls a public government site (robots.txt respected), turns each service page into
structured records (steps, required documents, forms, locations, fees), and enriches
every linked PDF form with its field names when robots.txt allows fetching it.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from apify import Actor, Event
from crawlee import Glob
from crawlee.crawlers import BeautifulSoupCrawler, BeautifulSoupCrawlingContext

from .extract import extract_records
from .pdf import PdfEnricher

DEFAULT_START_URLS = [{"url": "https://www.dmv.ca.gov/portal/"}]
DEFAULT_EXCLUDE_GLOBS = [
    "**/wp-content/**",
    "**/wp-admin/**",
    "**/file/**",  # PDF forms: fetched by PdfEnricher, not crawled as pages
    "**/uploads/**",
    "**/feed/**",
    "**/*?s=*",
    "**/news-and-media/**",
    "**/dmv-research-reports/**",
]


def _canonicalizer(start_urls: list[str]):
    """Rewrites example.gov <-> www.example.gov to the start URL's host so pages are not crawled twice."""
    canonical = {urlparse(u).netloc.removeprefix("www."): urlparse(u).netloc for u in start_urls}

    def transform(options):
        parts = urlparse(options["url"])
        host = canonical.get(parts.netloc.removeprefix("www."))
        if host and host != parts.netloc:
            options["url"] = parts._replace(netloc=host).geturl()
        return options

    return transform


async def main() -> None:
    async with Actor:

        async def on_aborting() -> None:
            await asyncio.sleep(1)
            await Actor.exit()

        Actor.on(Event.ABORTING, on_aborting)

        actor_input = await Actor.get_input() or {}
        start_urls = [s["url"] for s in actor_input.get("startUrls", DEFAULT_START_URLS) if s.get("url")]
        if not start_urls:
            Actor.log.info("No start URLs, exiting.")
            await Actor.exit()
        max_pages = int(actor_input.get("maxPagesPerCrawl", 100))
        max_depth = actor_input.get("maxCrawlDepth")  # 0 = only the start URLs
        max_pdfs = int(actor_input.get("maxPdfs", 150))
        extract_pdfs = bool(actor_input.get("extractPdfFields", True))
        exclude = [Glob(g) for g in actor_input.get("excludeUrlGlobs", DEFAULT_EXCLUDE_GLOBS)]
        transform = _canonicalizer(start_urls)
        start_urls = [transform({"url": u})["url"] for u in start_urls]

        crawler = BeautifulSoupCrawler(
            max_requests_per_crawl=max_pages,
            max_crawl_depth=int(max_depth) if max_depth is not None else None,
            respect_robots_txt_file=True,
            max_request_retries=2,
            request_handler_timeout=timedelta(seconds=180),
        )
        stats = {"pages": 0, "records": 0, "forms": 0}
        enricher: PdfEnricher | None = None

        @crawler.router.default_handler
        async def handle(context: BeautifulSoupCrawlingContext) -> None:
            nonlocal enricher
            url = context.request.loaded_url or context.request.url
            crawled_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            records = extract_records(context.soup, url, crawled_at)

            if extract_pdfs and records:
                if enricher is None:

                    async def fetch(target: str) -> tuple[int, bytes]:
                        response = await context.send_request(target, timeout=timedelta(seconds=60))
                        return response.status_code, await response.read()

                    enricher = PdfEnricher(fetch, max_pdfs)
                for record in records:
                    record["forms"] = [await enricher.enrich(f) for f in record["forms"]]

            for record in records:
                await context.push_data(record)
            stats["pages"] += 1
            stats["records"] += len(records)
            stats["forms"] += sum(len(r["forms"]) for r in records[:1])
            await Actor.set_status_message(
                f"{stats['pages']} pages, {stats['records']} service records, {stats['forms']} form links"
            )
            await context.enqueue_links(strategy="same-domain", exclude=exclude, transform_request_function=transform)

        await crawler.run(start_urls)
        Actor.log.info(f"Done: {stats}")
