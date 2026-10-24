"""Data freshness and live refresh (used by the Crawler agent).

A site counts as fresh if its last crawl is younger than CRAWL_MAX_AGE_HOURS (default 24). A refresh runs the same
Apify pipeline as the initial crawl: Website Content Crawler -> ingest pages -> PlainPath Gov Extractor on the
service pages -> ingest services/forms. Only one refresh per site runs at a time (tracked in `sites`).
"""
import logging
from datetime import datetime, timezone

from . import crawl, db, ingest
from .config import env

log = logging.getLogger("plainpath.refresh")

ACTIVE_RUN_STATUSES = {"READY", "RUNNING"}


def max_age_hours() -> float:
    return float(env("CRAWL_MAX_AGE_HOURS", "24"))


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def check(site: str) -> dict:
    """{site, exists, crawled_at, age_hours, fresh, refreshing_run_id}"""
    rec = db.db().sites.find_one({"site": site}) or {}
    crawled = _parse(rec.get("last_crawled_at"))
    age = (datetime.now(timezone.utc) - crawled).total_seconds() / 3600 if crawled else None
    return {
        "site": site,
        "exists": bool(rec) and db.db().chunks.count_documents({"site": site}, limit=1) > 0,
        "crawled_at": rec.get("last_crawled_at"),
        "age_hours": round(age, 2) if age is not None else None,
        "fresh": age is not None and age < max_age_hours(),
        "refreshing_run_id": rec.get("refresh_run_id") if rec.get("status") == "refreshing" else None,
    }


def start_url_for(site: str) -> str:
    target = env("TARGET_START_URL")
    if target and crawl.site_of(target) == site:
        return target
    rec = db.db().sites.find_one({"site": site}) or {}
    return rec.get("start_url") or f"https://www.{site}/"


def start(site: str) -> dict:
    """Start (or join) a refresh. Returns {run_id, joined}. Raises on Apify failure."""
    current = check(site).get("refreshing_run_id")
    if current and crawl.get_status(current)["status"] in ACTIVE_RUN_STATUSES:
        return {"run_id": current, "joined": True}
    if env("CRAWLER_SIMULATE_FAILURE") == "1":
        raise RuntimeError("Simulated Apify failure (CRAWLER_SIMULATE_FAILURE=1)")
    started = crawl.start_crawl(start_url_for(site), int(env("MAX_PAGES", "300")))
    db.db().sites.update_one(
        {"site": site}, {"$set": {"status": "refreshing", "refresh_run_id": started["run_id"]}}, upsert=True
    )
    return {"run_id": started["run_id"], "joined": False}


def progress(run_id: str) -> dict:
    """{status, pages_done, done}"""
    s = crawl.get_status(run_id)
    return {"status": s["status"], "pages_done": s["pages_done"], "done": s["status"] not in ACTIVE_RUN_STATUSES}


def finish(site: str, run_id: str) -> dict:
    """Block until the crawl ends, then ingest pages and refresh services/forms. Safe to call from a thread."""
    try:
        status = crawl.wait_for_run(run_id)
        if status["status"] != "SUCCEEDED":
            raise RuntimeError(f"crawl {run_id} ended with {status['status']}")
        pages = ingest.ingest_wcc_dataset(status["dataset_id"], run_id)
        urls = crawl.service_page_urls(status["dataset_id"])
        extractor = crawl.start_extractor(urls)
        ex_status = crawl.wait_for_run(extractor["run_id"])
        services = (
            ingest.ingest_extractor_dataset(ex_status["dataset_id"], extractor["run_id"])
            if ex_status["status"] == "SUCCEEDED"
            else {"error": ex_status["status"]}
        )
        log.info("refresh of %s done: pages=%s services=%s", site, pages, services)
        return {"ok": True, "pages": pages, "services": services}
    except Exception as exc:
        log.exception("refresh of %s failed", site)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        db.db().sites.update_one({"site": site, "refresh_run_id": run_id}, {"$set": {"status": "ready"}, "$unset": {"refresh_run_id": ""}})
