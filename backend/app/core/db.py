"""MongoDB Atlas access and index setup.

Collections:
  chunks   {_id, site, url, title, text, embedding, crawled_at, kind: page|form, form_number_norm, ingest_id}
  services custom Actor records (section 6 format) + ingest metadata
  forms    one doc per unique form URL: {number, number_norm, name, url, fields, description, source_pages, ...}
  sites    {site, start_url, last_crawled_at, status, ...}
"""
import time
from functools import lru_cache

from pymongo import ASCENDING, MongoClient
from pymongo.database import Database
from pymongo.operations import SearchIndexModel

from .config import env

VECTOR_INDEX = "chunks_vector"
EMBEDDING_DIMS = 1024  # BAAI/bge-m3


@lru_cache(maxsize=1)
def client() -> MongoClient:
    return MongoClient(env("MONGODB_URI", required=True), serverSelectionTimeoutMS=15000, appname="plainpath")


def db() -> Database:
    return client()[env("MONGODB_DB", "plainpath")]


def ensure_indexes(wait: bool = True, timeout_s: int = 300) -> None:
    """Idempotent. Creates regular indexes and the Atlas Vector Search index on chunks.embedding."""
    d = db()
    d.chunks.create_index([("site", ASCENDING), ("kind", ASCENDING), ("ingest_id", ASCENDING)])
    d.services.create_index([("site", ASCENDING)])
    d.forms.create_index([("number_norm", ASCENDING)])
    d.forms.create_index([("site", ASCENDING)])
    d.sites.create_index([("site", ASCENDING)], unique=True)

    if "chunks" not in d.list_collection_names():
        d.create_collection("chunks")
    existing = {ix["name"]: ix for ix in d.chunks.list_search_indexes()}
    if VECTOR_INDEX not in existing:
        d.chunks.create_search_index(
            SearchIndexModel(
                name=VECTOR_INDEX,
                type="vectorSearch",
                definition={
                    "fields": [
                        {"type": "vector", "path": "embedding", "numDimensions": EMBEDDING_DIMS, "similarity": "cosine"},
                        {"type": "filter", "path": "site"},
                        {"type": "filter", "path": "kind"},
                    ]
                },
            )
        )
    if wait:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            ix = next((i for i in d.chunks.list_search_indexes() if i["name"] == VECTOR_INDEX), None)
            if ix and ix.get("queryable"):
                return
            time.sleep(5)
        raise TimeoutError(f"Vector index {VECTOR_INDEX} not queryable after {timeout_s}s")
