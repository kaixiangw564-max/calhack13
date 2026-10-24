"""Grounded Q&A: retrieve official chunks, then have Bitdeer write plain-language numbered steps.

Rules enforced in code (not left to the model):
  * every step's source_url / crawled_at comes from the retrieved chunk the model cited by number;
    steps citing no valid source are dropped
  * no relevant chunks (score gate) or the model reports nothing found -> not_found + site contact page
"""
import json
import logging
import re

from . import db, llm, retrieval
from .ingest import normalize_form_number

log = logging.getLogger("plainpath.answer")

# Calibrated on dmv.ca.gov (step 6): related questions score >= 0.857, unrelated <= 0.807.
MIN_SCORE = 0.83
TOP_K = 8
DISCLAIMER_EN = "This information comes from the official website. Always check the original page."
NOT_FOUND_EN = "This was not found on the official website."

ANSWER_SYSTEM = """You help people use government websites. You are given numbered excerpts from the official website.

Rules:
- Use ONLY the excerpts. Never use outside knowledge. If the excerpts do not answer the question, set "not_found": true.
- Write in this language: {language}.
- Use short sentences and everyday words, at an elementary-school reading level.
- Give numbered steps in order. Each step must cite the excerpt numbers it comes from, e.g. [2].
- List required documents only if the excerpts mention them.
- List forms only if the excerpts mention them; use the form number and name exactly as written.
- Do not give legal or medical advice. Only restate what the official text says.
- Keep official names, form numbers, website names, phone numbers and addresses exactly as written.

Return ONLY a JSON object:
{{"not_found": false,
  "steps": [{{"text": "...", "sources": [1]}}],
  "documents": [{{"text": "...", "sources": [2]}}],
  "forms": [{{"number": "REG 195", "name": "...", "sources": [3]}}],
  "disclaimer": "<translate: {disclaimer}>"}}"""

TRANSLATE_SYSTEM = (
    "Translate each value of the JSON object into {language}. Keep the keys. "
    "Return ONLY the JSON object."
)
QUERY_SYSTEM = (
    "Rewrite the user's question as one short English search query for a government website. "
    "Keep names, form numbers and places. Return ONLY the query."
)


def is_english(language: str | None) -> bool:
    return not language or language.strip().lower() in ("en", "english", "en-us", "en-gb")


def english_query(question: str) -> str | None:
    try:
        q = llm.chat([{"role": "system", "content": QUERY_SYSTEM}, {"role": "user", "content": question}], max_tokens=60)
        return q.strip().strip('"') or None
    except Exception as exc:  # retrieval still works with the original question
        log.warning("query rewrite failed: %s", exc)
        return None


def retrieve(question: str, language: str | None, site: str | None) -> list[dict]:
    """Hybrid search on the original question, plus its English rewrite for non-English questions."""
    results = {c["_id"]: c for c in retrieval.search(question, site, TOP_K)}
    # Only rewrite questions not already written in English (the Navigator passes an English restatement).
    if re.search(r"[^\x00-\x7f]", question):
        rewritten = english_query(question)
        if rewritten:
            for c in retrieval.search(rewritten, site, TOP_K):
                if c["_id"] not in results or c["score"] > results[c["_id"]]["score"]:
                    results[c["_id"]] = c
    ranked = sorted(results.values(), key=lambda c: (c.get("match") == "form_number", c["score"]), reverse=True)
    return ranked[:TOP_K]


def contact_for(site: str | None) -> dict | None:
    """The site's contact page, if it was crawled."""
    query = {"kind": "page", "url": {"$regex": "contact", "$options": "i"}, **({"site": site} if site else {})}
    doc = db.db().chunks.find_one(query, {"url": 1, "title": 1, "crawled_at": 1}, sort=[("url", 1)])
    return {"url": doc["url"], "title": doc["title"], "crawled_at": doc["crawled_at"]} if doc else None


def localized(texts: dict[str, str], language: str | None) -> dict[str, str]:
    if is_english(language):
        return texts
    try:
        out = llm.chat_json(
            [
                {"role": "system", "content": TRANSLATE_SYSTEM.format(language=language)},
                {"role": "user", "content": json.dumps(texts, ensure_ascii=False)},
            ],
            max_tokens=300,
        )
        return {k: str(out.get(k) or v) for k, v in texts.items()}
    except Exception as exc:
        log.warning("translation failed: %s", exc)
        return texts


def not_found(language: str | None, site: str | None, reason: str) -> dict:
    texts = localized({"message": NOT_FOUND_EN, "disclaimer": DISCLAIMER_EN}, language)
    return {
        "steps": [],
        "documents": [],
        "forms": [],
        "not_found": True,
        "message": texts["message"],
        "contact": contact_for(site),
        "disclaimer": texts["disclaimer"],
        "reason": reason,
    }


def _excerpts(chunks: list[dict]) -> str:
    return "\n\n".join(f"[{i}] {c['title']}\n{c['text']}" for i, c in enumerate(chunks, start=1))


def _strip_refs(text) -> str:
    """Remove the model's "[2]" / "[1, 3]" markers; sources are returned as URLs instead."""
    return re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]", "", str(text or "")).strip()


def _cited(item: dict, chunks: list[dict]) -> list[dict]:
    out = []
    for n in item.get("sources") or []:
        if isinstance(n, int) and 1 <= n <= len(chunks) and chunks[n - 1] not in out:
            out.append(chunks[n - 1])
    return out


def _forms(model_forms: list[dict], chunks: list[dict], site: str | None) -> list[dict]:
    """Forms the model mentioned, resolved against the `forms` collection (never trusting model URLs)."""
    out, seen = [], set()
    for f in model_forms:
        norm = normalize_form_number(f.get("number"))
        doc = db.db().forms.find_one({"number_norm": norm, **({"site": site} if site else {})}) if norm else None
        cited = _cited(f, chunks)
        if doc is None:
            # Fall back to a cited form chunk (official PDF URL comes from the crawl).
            form_chunk = next((c for c in cited if c.get("kind") == "form"), None)
            doc = db.db().forms.find_one({"_id": form_chunk["url"]}) if form_chunk else None
        if doc is None or doc["url"] in seen:
            continue
        seen.add(doc["url"])
        source = doc["source_pages"][0] if doc.get("source_pages") else {"url": doc["url"]}
        out.append(
            {
                "number": doc.get("number"),
                "name": doc["name"],
                "url": doc["url"],
                "source_url": source["url"],
                "crawled_at": doc["crawled_at"],
            }
        )
    return out


def ask(question: str, language: str | None = "en", site: str | None = None) -> dict:
    chunks = retrieve(question, language, site)
    if not chunks or chunks[0]["score"] < MIN_SCORE:
        return not_found(language, site, "no_relevant_content")

    messages = [
        {"role": "system", "content": ANSWER_SYSTEM.format(language=language or "English", disclaimer=DISCLAIMER_EN)},
        {"role": "user", "content": f"Official excerpts:\n\n{_excerpts(chunks)}\n\nQuestion: {question}"},
    ]
    try:
        data = llm.chat_json(messages, max_tokens=1500)
    except ValueError:
        data = llm.chat_json(messages, max_tokens=1500)  # one retry on malformed JSON

    if data.get("not_found"):
        return not_found(language, site, "model_found_no_answer")

    steps = []
    for s in data.get("steps") or []:
        cited = _cited(s, chunks)
        text = _strip_refs(s.get("text"))
        if cited and text:
            steps.append({"text": text, "source_url": cited[0]["url"], "crawled_at": cited[0]["crawled_at"]})
    if not steps:
        return not_found(language, site, "no_cited_steps")

    documents = []
    for d in data.get("documents") or []:
        cited = _cited(d, chunks)
        text = _strip_refs(d.get("text"))
        if cited and text:
            documents.append({"text": text, "source_url": cited[0]["url"], "crawled_at": cited[0]["crawled_at"]})

    return {
        "steps": steps,
        "documents": documents,
        "forms": _forms(data.get("forms") or [], chunks, site),
        "not_found": False,
        "disclaimer": str(data.get("disclaimer") or DISCLAIMER_EN),
    }
