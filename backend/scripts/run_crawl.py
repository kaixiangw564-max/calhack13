"""Run a full-site Website Content Crawler crawl of TARGET_START_URL and wait for it.

Usage (from backend/):  ../.venv/Scripts/python -m scripts.run_crawl
Prints the run id and dataset id; record the dataset id in PROGRESS.md.
"""
import time

from app.core import crawl
from app.core.config import env


def main() -> None:
    start_url = env("TARGET_START_URL", required=True)
    max_pages = int(env("MAX_PAGES", "300"))
    started = crawl.start_crawl(start_url, max_pages)
    print(f"started run {started['run_id']} dataset {started['dataset_id']} for {start_url} (max {max_pages} pages)")
    while True:
        status = crawl.get_status(started["run_id"])
        print(f"  {status['status']}: {status['pages_done']} pages, ${status['usage_usd'] or 0:.3f}", flush=True)
        if status["status"] not in ("READY", "RUNNING"):
            break
        time.sleep(20)
    pages = list(crawl.iter_pages(started["dataset_id"]))
    print(f"final {status['status']}: {status['pages_done']} items, {len(pages)} pages with content")


if __name__ == "__main__":
    main()
