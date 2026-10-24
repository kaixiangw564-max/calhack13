"""PlainPath FastAPI app. Business logic lives in app.core; routes are thin wrappers."""
import hmac
import logging

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException

from .core import crawl, ingest
from .core.config import env

log = logging.getLogger("plainpath")
app = FastAPI(title="PlainPath API")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


def _ingest_run(actor_id: str, run_id: str, dataset_id: str) -> None:
    name = crawl.actor_full_name(actor_id)
    if name == crawl.extractor_actor_id():
        result = ingest.ingest_extractor_dataset(dataset_id, run_id)
    elif name == crawl.WCC_ACTOR:
        result = ingest.ingest_wcc_dataset(dataset_id, run_id)
    else:
        log.warning("webhook for unknown actor %s (%s); ignored", name, actor_id)
        return
    log.info("ingested %s run %s: %s", name, run_id, result)


@app.post("/webhook/apify")
def apify_webhook(
    payload: dict,
    background: BackgroundTasks,
    x_plainpath_webhook_secret: str | None = Header(default=None),
) -> dict:
    """Called by Apify when a crawl run succeeds. Responds immediately; ingestion runs in the background
    (Apify times out webhooks after 2 minutes and retries non-2xx responses)."""
    secret = env("APIFY_WEBHOOK_SECRET")
    if not secret or not hmac.compare_digest(x_plainpath_webhook_secret or "", secret):
        raise HTTPException(status_code=401, detail="bad webhook secret")
    run = payload.get("resource") or {}
    if run.get("status") != "SUCCEEDED" or not run.get("defaultDatasetId"):
        return {"ok": True, "ingest": "skipped"}
    background.add_task(_ingest_run, run["actId"], run["id"], run["defaultDatasetId"])
    return {"ok": True, "ingest": "started"}
