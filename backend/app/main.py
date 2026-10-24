"""PlainPath FastAPI app. Business logic lives in app.core; routes are thin wrappers."""
import hmac
import logging

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .core import answer, crawl, ingest
from .core.config import env

log = logging.getLogger("plainpath")
app = FastAPI(title="PlainPath API")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    language: str = "en"
    site: str | None = None


class CrawlRequest(BaseModel):
    start_url: str
    max_pages: int = Field(default=300, ge=1, le=1000)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/ask")
def ask(req: AskRequest) -> dict:
    """{steps: [{text, source_url, crawled_at}], documents, forms, not_found, disclaimer}."""
    return answer.ask(req.question, req.language, req.site)


@app.post("/crawl")
def start_crawl(req: CrawlRequest) -> dict:
    """Start an Apify Website Content Crawler run (ingest happens via the webhook)."""
    started = crawl.start_crawl(req.start_url, req.max_pages)
    return {"run_id": started["run_id"], "status": started["status"]}


@app.get("/crawl/{run_id}")
def crawl_status(run_id: str) -> dict:
    status = crawl.get_status(run_id)
    if status["status"] == "NOT_FOUND":
        raise HTTPException(status_code=404, detail="run not found")
    return {"status": status["status"], "pages_done": status["pages_done"]}


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
