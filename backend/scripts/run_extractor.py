"""Run the custom PlainPath Gov Extractor Actor on the service pages found by the latest WCC crawl.

Usage (from backend/):  ../.venv/Scripts/python -m scripts.run_extractor
Pipeline: Website Content Crawler (step 3) -> service_page_urls() -> Gov Extractor with maxCrawlDepth=0.
"""
import time

from app.core import crawl


def main() -> None:
    wcc = crawl.latest_succeeded_run()
    if wcc is None:
        raise SystemExit("No successful Website Content Crawler run; run scripts.run_crawl first.")
    urls = crawl.service_page_urls(wcc["dataset_id"])
    started = crawl.start_extractor(urls)
    print(f"{len(urls)} service pages from WCC dataset {wcc['dataset_id']}")
    print(f"started {crawl.extractor_actor_id()} run {started['run_id']} dataset {started['dataset_id']}")
    while True:
        status = crawl.get_status(started["run_id"])
        print(f"  {status['status']}: {status['pages_done']} records, ${status['usage_usd'] or 0:.3f}", flush=True)
        if status["status"] not in ("READY", "RUNNING"):
            break
        time.sleep(20)
    print(f"final {status['status']}: {status['pages_done']} records")


if __name__ == "__main__":
    main()
