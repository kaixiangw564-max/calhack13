"""Chunk, embed and store crawled content.

Two sources, both produced by Apify:
  * Website Content Crawler dataset -> page chunks (kind="page")
  * PlainPath Gov Extractor dataset  -> `services`, `forms`, and one form chunk per unique form (kind="form")

Re-ingesting a run is idempotent: chunk ids are deterministic and chunks from older ingests of the
same site/kind are removed afterwards.
"""
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from pymongo import ReplaceOne

from . import crawl, db, embeddings

MAX_CHUNK_CHARS = 1500
MIN_CHUNK_CHARS = 120
FORM_NUMBER_RE = re.compile(r"\b([A-Za-z]{2,4})[\s-]?(\d{1,4}[A-Za-z]?)\b")
_MD_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$", re.M)


def _id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_form_number(number: str | None) -> str | None:
    """'REG 195' / 'reg-195' / 'REG195' -> 'REG195'."""
    if not number:
        return None
    m = FORM_NUMBER_RE.fullmatch(number.strip())
    return f"{m.group(1).upper()}{m.group(2).upper()}" if m else None


def canonical_urls(urls: list[str]) -> dict[str, str]:
    """Maps bare-domain URLs to their www. variant when the dataset also contains that host."""
    hosts = {urlparse(u).netloc for u in urls}
    out = {}
    for u in urls:
        parts = urlparse(u)
        if not parts.netloc.startswith("www.") and f"www.{parts.netloc}" in hosts:
            u2 = parts._replace(netloc=f"www.{parts.netloc}").geturl()
        else:
            u2 = u
        out[u] = u2
    return out


def common_title_suffix(titles: list[str]) -> str | None:
    """Site-wide title suffix such as ' - California DMV' if more than half the pages share it."""
    counts: dict[str, int] = {}
    for t in titles:
        m = re.search(r"\s[-|–]\s[^-|–]+$", t)
        if m:
            counts[m.group(0)] = counts.get(m.group(0), 0) + 1
    if not counts:
        return None
    suffix, n = max(counts.items(), key=lambda kv: kv[1])
    return suffix if n > len(titles) / 2 else None


def chunk_markdown(markdown: str, title: str) -> list[str]:
    """Split by headings, merge small sections, split long ones on paragraph boundaries.

    Each chunk starts with the page title (and its section heading) so it is self-describing.
    """
    text = _MD_LINK_RE.sub(r"\1", markdown)
    sections: list[tuple[str, str]] = []
    last, heading = 0, ""
    for m in _HEADING_RE.finditer(text):
        sections.append((heading, text[last : m.start()]))
        heading, last = m.group(2).strip(), m.end()
    sections.append((heading, text[last:]))

    pieces: list[tuple[str, str]] = []
    for heading, body in sections:
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        if not body:
            continue
        paragraphs, buf = body.split("\n\n"), ""
        for para in paragraphs:
            if buf and len(buf) + len(para) > MAX_CHUNK_CHARS:
                pieces.append((heading, buf))
                buf = ""
            buf = f"{buf}\n\n{para}" if buf else para
            while len(buf) > MAX_CHUNK_CHARS:  # a single huge paragraph
                pieces.append((heading, buf[:MAX_CHUNK_CHARS]))
                buf = buf[MAX_CHUNK_CHARS:]
        if buf:
            pieces.append((heading, buf))

    merged: list[tuple[str, str]] = []
    for heading, body in pieces:
        if merged and (len(body) < MIN_CHUNK_CHARS or len(merged[-1][1]) < MIN_CHUNK_CHARS) and len(
            merged[-1][1]
        ) + len(body) <= MAX_CHUNK_CHARS:
            prev_heading, prev_body = merged[-1]
            label = f"## {heading}\n" if heading and heading != prev_heading else ""
            merged[-1] = (prev_heading, f"{prev_body}\n\n{label}{body}")
        else:
            merged.append((heading, body))
    return [f"{title}\n## {h}\n{b}" if h and h != title else f"{title}\n{b}" for h, b in merged]


def _write_chunks(docs: list[dict], site: str, kind: str, ingest_id: str) -> int:
    if docs:
        vectors = embeddings.embed([d["text"] for d in docs])
        for doc, vector in zip(docs, vectors):
            doc["embedding"] = vector
        db.db().chunks.bulk_write([ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in docs])
    # Remove chunks of this site/kind left over from older ingests.
    db.db().chunks.delete_many({"site": site, "kind": kind, "ingest_id": {"$ne": ingest_id}})
    return len(docs)


def ingest_wcc_dataset(dataset_id: str, run_id: str | None = None) -> dict:
    """Website Content Crawler dataset -> page chunks. Returns {site, pages, chunks}."""
    pages = list(crawl.iter_pages(dataset_id))
    if not pages:
        return {"site": None, "pages": 0, "chunks": 0}
    canon = canonical_urls([p["url"] for p in pages])
    suffix = common_title_suffix([p["title"] for p in pages])
    ingest_id = run_id or dataset_id
    seen_urls, docs = set(), []
    for page in pages:
        url = canon[page["url"]]
        if url.rstrip("/") in seen_urls:
            continue
        seen_urls.add(url.rstrip("/"))
        title = page["title"].removesuffix(suffix).strip() if suffix else page["title"]
        for i, text in enumerate(chunk_markdown(page["markdown"], title)):
            docs.append(
                {
                    "_id": _id(url, "page", str(i)),
                    "site": page["site"],
                    "url": url,
                    "title": title,
                    "text": text,
                    "crawled_at": page["crawled_at"],
                    "kind": "page",
                    "ingest_id": ingest_id,
                }
            )
    site = pages[0]["site"]
    n = _write_chunks(docs, site, "page", ingest_id)
    _touch_site(site, f"https://{urlparse(canon[pages[0]['url']]).netloc}/", pages, wcc_run_id=run_id, page_chunks=n)
    return {"site": site, "pages": len(seen_urls), "chunks": n}


def form_chunk_text(form: dict) -> str:
    label = f"Form {form['number']}: {form['name']}" if form.get("number") else f"Form: {form['name']}"
    lines = [label, f"Official form PDF: {form['url']}"]
    services = sorted({s["service"] for s in form["source_pages"]})
    if services:
        lines.append("Used for: " + "; ".join(services[:8]))
    pages = sorted({f"{s['title']} ({s['url']})" for s in form["source_pages"]})
    lines.append("Mentioned on: " + "; ".join(pages[:5]))
    if form.get("description"):
        lines.append("Form instructions (first page): " + re.sub(r"\s+", " ", form["description"])[:800])
    if form.get("fields"):
        lines.append("Fields to fill in: " + "; ".join(form["fields"][:30]))
    return "\n".join(lines)


def ingest_extractor_dataset(dataset_id: str, run_id: str | None = None) -> dict:
    """PlainPath Gov Extractor dataset -> services, forms, form chunks. Returns counts."""
    records = list(crawl.client().dataset(dataset_id).iterate_items())
    if not records:
        return {"site": None, "services": 0, "forms": 0, "chunks": 0}
    ingest_id = run_id or dataset_id
    site = records[0]["site"]
    d = db.db()

    service_ops, forms = [], {}
    for rec in records:
        service_ops.append(
            ReplaceOne({"_id": _id(rec["url"], rec["service"])}, {**rec, "ingest_id": ingest_id}, upsert=True)
        )
        for f in rec["forms"]:
            form = forms.setdefault(
                f["url"],
                {
                    "_id": f["url"],
                    "site": rec["site"],
                    "url": f["url"],
                    "number": f.get("number"),
                    "number_norm": normalize_form_number(f.get("number")),
                    "name": f["name"],
                    "fields": f.get("fields") or [],
                    "description": f.get("description", ""),
                    "pdf_status": f.get("pdf_status"),
                    "pdf_pages": f.get("pdf_pages"),
                    "crawled_at": rec["crawled_at"],
                    "source_pages": [],
                    "ingest_id": ingest_id,
                },
            )
            if len(f["name"]) > len(form["name"]):
                form["name"] = f["name"]
            if not form["number"] and f.get("number"):
                form["number"], form["number_norm"] = f["number"], normalize_form_number(f["number"])
            source = {"url": rec["url"], "title": rec["title"], "service": rec["service"]}
            if source not in form["source_pages"]:
                form["source_pages"].append(source)

    d.services.bulk_write(service_ops)
    d.services.delete_many({"site": site, "ingest_id": {"$ne": ingest_id}})
    if forms:
        d.forms.bulk_write([ReplaceOne({"_id": k}, v, upsert=True) for k, v in forms.items()])
    d.forms.delete_many({"site": site, "ingest_id": {"$ne": ingest_id}})

    chunk_docs = [
        {
            "_id": _id(form["url"], "form"),
            "site": form["site"],
            "url": form["url"],
            "title": f"{form['number']}: {form['name']}" if form.get("number") else form["name"],
            "text": form_chunk_text(form),
            "crawled_at": form["crawled_at"],
            "kind": "form",
            "form_number_norm": form["number_norm"],
            "ingest_id": ingest_id,
        }
        for form in forms.values()
    ]
    n = _write_chunks(chunk_docs, site, "form", ingest_id)
    _touch_site(site, None, records, extractor_run_id=run_id, form_chunks=n)
    return {"site": site, "services": len(records), "forms": len(forms), "chunks": n}


def _touch_site(site: str, start_url: str | None, items: list[dict], **extra) -> None:
    crawled = [i["crawled_at"] for i in items if i.get("crawled_at")]
    update = {"site": site, "status": "ready", "last_crawled_at": max(crawled) if crawled else now_iso(), **extra}
    if start_url:
        update["start_url"] = start_url
    db.db().sites.update_one({"site": site}, {"$set": {k: v for k, v in update.items() if v is not None}}, upsert=True)
