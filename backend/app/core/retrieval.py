"""Hybrid retrieval: exact form-number match + Atlas Vector Search.

Embeddings handle codes like "REG 195" poorly, so any form number mentioned in the question is
looked up exactly first; vector search fills the remaining slots.
"""
import re

from . import db, embeddings
from .ingest import FORM_NUMBER_RE

TOP_K = 8
_PROJECTION = {"embedding": 0, "ingest_id": 0}


def form_numbers_in(text: str, known_prefixes: set[str]) -> list[str]:
    """Normalized form numbers in free text, limited to prefixes that exist in the forms collection."""
    out = []
    for m in FORM_NUMBER_RE.finditer(text):
        prefix = m.group(1).upper()
        if prefix in known_prefixes:
            norm = f"{prefix}{m.group(2).upper()}"
            if norm not in out:
                out.append(norm)
    return out


def known_form_prefixes(site: str | None = None) -> set[str]:
    query = {"number_norm": {"$ne": None}, **({"site": site} if site else {})}
    return {re.match(r"[A-Z]+", n).group(0) for n in db.db().forms.distinct("number_norm", query)}


def vector_search(question: str, site: str | None = None, k: int = TOP_K, kind: str | None = None) -> list[dict]:
    filters = [f for f in ({"site": site} if site else None, {"kind": kind} if kind else None) if f]
    stage = {
        "index": db.VECTOR_INDEX,
        "path": "embedding",
        "queryVector": embeddings.embed_one(question),
        "numCandidates": max(20 * k, 100),
        "limit": k,
    }
    if filters:
        stage["filter"] = filters[0] if len(filters) == 1 else {"$and": filters}
    pipeline = [
        {"$vectorSearch": stage},
        {"$project": {**_PROJECTION, "score": {"$meta": "vectorSearchScore"}}},
    ]
    return list(db.db().chunks.aggregate(pipeline))


def exact_form_chunks(question: str, site: str | None = None) -> list[dict]:
    numbers = form_numbers_in(question, known_form_prefixes(site))
    if not numbers:
        return []
    query = {"kind": "form", "form_number_norm": {"$in": numbers}, **({"site": site} if site else {})}
    return [{**c, "score": 1.0, "match": "form_number"} for c in db.db().chunks.find(query, _PROJECTION)]


def search(question: str, site: str | None = None, k: int = TOP_K) -> list[dict]:
    """Top-k chunks: exact form-number hits first, then vector hits (deduplicated)."""
    results = exact_form_chunks(question, site)
    seen = {c["_id"] for c in results}
    for c in vector_search(question, site, k):
        if c["_id"] not in seen:
            seen.add(c["_id"])
            results.append({**c, "match": "vector"})
    return results[:k]
