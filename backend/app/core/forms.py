"""Required documents and form explanations for a service (used by the Form agent).

Source data is the custom Apify Actor output (`services` + `forms` collections). Bitdeer only rewrites and
explains what is in those records; links always come from the crawl.
"""
import json
import logging

from . import db, llm, retrieval
from .answer import DISCLAIMER_EN, is_english, localized

log = logging.getLogger("plainpath.forms")

MAX_DOCS = 25
MAX_FORMS = 6
MAX_UNNUMBERED = 2  # guides / fact sheets without a form number
MAX_FIELDS = 25
# Relative match for related forms: keep hits within FORM_MATCH_BAND of the best hit, never below FORM_MATCH_FLOOR.
# (REG 195A scores 0.833 for "renew disabled parking placard" but 0.810 once "in Contra Costa, California" is added.)
FORM_MATCH_FLOOR = 0.78
FORM_MATCH_BAND = 0.03

FORMS_SYSTEM = """You explain government paperwork in plain words. You are given the user's question, numbered required-document
lines and forms taken from an official website. Write in this language: {language}. Use short sentences and everyday words.

Rules:
- Use ONLY the given lines and forms. Never add documents, fees or rules that are not there.
- Keep only documents and forms for the user's specific action. For example, for a renewal keep the renewal form
  and renewal requirements, and leave out first-time application forms and documents unless the official text says
  they are needed for renewal. Leave out everything else
  (return only the relevant forms, by id). If the same guide or fact sheet exists in several languages, keep only
  the version in "answer_language" (or English if there is none).
- "documents": keep only lines that describe something the person must bring, provide, sign or fill in.
  Rewrite each one simply. Merge duplicates. Cite the line numbers in "sources".
- For each form: "purpose" says in one sentence what the form is for, based on its name and instructions.
  "fields": pick up to 8 of the most important fields and explain in a few words what to write there.
- Keep form numbers (e.g. REG 195) and official names exactly as written. No legal or medical advice.

Return ONLY JSON:
{{"documents": [{{"text": "...", "sources": [1]}}],
  "forms": [{{"id": 1, "purpose": "...", "fields": [{{"label": "...", "explain": "..."}}]}}]}}"""


LANGUAGE_NAMES = {"en": "English", "zh": "Chinese", "es": "Spanish", "vi": "Vietnamese", "ko": "Korean",
                  "tl": "Tagalog", "ru": "Russian", "ar": "Arabic", "fa": "Persian", "hy": "Armenian",
                  "hi": "Hindi", "pa": "Punjabi", "ja": "Japanese", "km": "Khmer"}


def language_name(code: str | None) -> str:
    return LANGUAGE_NAMES.get((code or "en").split("-")[0].lower(), code or "English")


def _canonical(url: str) -> str:
    return url.replace("://dmv.", "://www.dmv.").rstrip("/")


def gather(source_urls: list[str], site: str | None = None, question: str | None = None) -> tuple[list[dict], list[dict]]:
    """Raw (English) document lines and form docs: from the pages an answer cited, plus the pages and forms that
    vector search finds for the question (the extractor may have recorded the service on a sibling page)."""
    related_forms: list[str] = []
    if question:
        related = retrieval.vector_search(question, site, k=8, kind="page")
        source_urls = list(source_urls) + [c["url"] for c in related]
        hits = retrieval.vector_search(question, site, k=5, kind="form")
        cutoff = max(FORM_MATCH_FLOOR, (hits[0]["score"] - FORM_MATCH_BAND) if hits else 1.0)
        related_forms = [c["url"] for c in hits if c["score"] >= cutoff]
        # The pages that link a related form describe its requirements (the crawler and the extractor can store the
        # same page under different URLs, e.g. dpp-renewal vs dppp-renewal, so URL matching alone misses them).
        # Only numbered forms: unnumbered guides (e.g. "Quick Start Guide") are linked from many unrelated pages.
        for f in db.db().forms.find({"_id": {"$in": related_forms}, "number": {"$ne": None}}, {"source_pages.url": 1}):
            source_urls += [p["url"] for p in (f.get("source_pages") or [])[:3]]
    wanted = {_canonical(u) for u in source_urls}
    query = {"site": site} if site else {}
    docs, seen_docs, form_urls = [], set(), []
    for rec in db.db().services.find(query, {"url": 1, "required_documents": 1, "forms": 1, "crawled_at": 1}):
        if _canonical(rec["url"]) not in wanted:
            continue
        for line in rec.get("required_documents") or []:
            if line not in seen_docs:
                seen_docs.add(line)
                docs.append({"text": line, "source_url": rec["url"], "crawled_at": rec.get("crawled_at")})
        for f in rec.get("forms") or []:
            if f["url"] not in form_urls:
                form_urls.append(f["url"])
    # Forms cited directly (e.g. an answer that linked a form PDF) count too.
    form_urls = [u for u in related_forms if u not in form_urls] + form_urls
    form_urls += [u for u in source_urls if "/file/" in u and u not in form_urls]
    forms = [f for f in (db.db().forms.find_one({"_id": u}) for u in form_urls) if f]
    # Numbered forms first: they are the actual application forms; unnumbered PDFs are usually guides.
    related = set(related_forms)
    forms.sort(key=lambda f: (f["_id"] not in related, f.get("number") is None, -len(f.get("fields") or [])))
    return docs[:MAX_DOCS], forms[:MAX_FORMS]


def checklist(source_urls: list[str], language: str = "en", site: str | None = None, question: str | None = None) -> dict:
    """{documents: [{text, source_url, crawled_at}], forms: [{number, name, url, source_url, crawled_at, purpose,
    fields: [{label, explain}]}], empty, disclaimer}"""
    docs, forms = gather(source_urls, site, question)
    if not docs and not forms:
        return {"documents": [], "forms": [], "empty": True, "disclaimer": localized({"d": DISCLAIMER_EN}, language)["d"]}

    payload = {
        "question": question or "",
        "answer_language": language_name(language),
        "lines": {i: d["text"] for i, d in enumerate(docs, start=1)},
        "forms": [
            {
                "id": i,
                "number": f.get("number"),
                "name": f["name"],
                "instructions": (f.get("description") or "")[:600],
                "fields": (f.get("fields") or [])[:MAX_FIELDS],
            }
            for i, f in enumerate(forms, start=1)
        ],
    }
    data = llm.chat_json(
        [
            {"role": "system", "content": FORMS_SYSTEM.format(language=language_name(language))},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        max_tokens=1500,
    )

    out_docs = []
    for d in data.get("documents") or []:
        cited = [docs[n - 1] for n in d.get("sources") or [] if isinstance(n, int) and 1 <= n <= len(docs)]
        if cited and d.get("text"):
            out_docs.append({"text": str(d["text"]).strip(), "source_url": cited[0]["source_url"], "crawled_at": cited[0]["crawled_at"]})

    explained = {f.get("id"): f for f in data.get("forms") or [] if isinstance(f, dict)}
    out_forms = []
    for i, f in enumerate(forms, start=1):
        if explained and i not in explained:
            continue  # model judged this form irrelevant to the question
        e = explained.get(i, {})
        source = (f.get("source_pages") or [{"url": f["url"]}])[0]
        out_forms.append(
            {
                "number": f.get("number"),
                "name": f["name"],
                "url": f["url"],
                "source_url": source["url"],
                "crawled_at": f.get("crawled_at"),
                "purpose": str(e.get("purpose") or ""),
                "fields": [
                    {"label": str(x.get("label", "")), "explain": str(x.get("explain", ""))}
                    for x in (e.get("fields") or [])[:8]
                    if isinstance(x, dict)
                ],
            }
        )
    numbered = [f for f in out_forms if f["number"]]
    out_forms = numbered + [f for f in out_forms if not f["number"]][:MAX_UNNUMBERED]
    disclaimer = DISCLAIMER_EN if is_english(language) else localized({"d": DISCLAIMER_EN}, language)["d"]
    return {"documents": out_docs, "forms": out_forms, "empty": False, "disclaimer": disclaimer}
