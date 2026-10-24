"""Ingest the latest successful crawl runs into MongoDB Atlas (same code path as POST /webhook/apify).

Usage (from backend/):  ../.venv/Scripts/python -m scripts.run_ingest
"""
from app.core import crawl, db, ingest


def main() -> None:
    db.ensure_indexes(wait=False)
    wcc = crawl.latest_succeeded_run()
    if wcc:
        print("pages:", ingest.ingest_wcc_dataset(wcc["dataset_id"], wcc["run_id"]), flush=True)
    extractor = crawl.latest_succeeded_run(crawl.extractor_actor_id())
    if extractor:
        print("forms/services:", ingest.ingest_extractor_dataset(extractor["dataset_id"], extractor["run_id"]), flush=True)
    print("waiting for vector index to be queryable...", flush=True)
    db.ensure_indexes(wait=True)
    print("ready")


if __name__ == "__main__":
    main()
