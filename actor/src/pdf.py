"""Robots-aware PDF form enrichment: field names + first-page description via pypdf."""
from __future__ import annotations

import asyncio
import io
import re
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from crawlee._utils.robots import RobotsTxtFile
from pypdf import PdfReader

MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_FIELDS = 80
DESCRIPTION_CHARS = 1500

Fetch = Callable[[str], Awaitable[tuple[int, bytes]]]


class RobotsGate:
    """Caches one parsed robots.txt per origin. Unreachable robots.txt => allow (standard crawler behavior)."""

    def __init__(self, fetch: Fetch):
        self._fetch = fetch
        self._cache: dict[str, RobotsTxtFile | None] = {}

    async def allowed(self, url: str) -> bool:
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._cache:
            try:
                status, body = await self._fetch(origin + "/robots.txt")
                self._cache[origin] = (
                    await RobotsTxtFile.from_content(origin + "/robots.txt", body.decode("utf-8", "replace"))
                    if status == 200
                    else None
                )
            except Exception:
                self._cache[origin] = None
        robots = self._cache[origin]
        return robots is None or robots.is_allowed(url)


def _field_label(name: str, field: dict) -> str:
    label = field.get("/TU") or name
    label = re.sub(r"\s+", " ", str(label)).strip()
    return label


def parse_pdf(data: bytes) -> dict:
    """Returns {fields, pdf_pages, description}. Never raises; returns empty values on parse errors."""
    try:
        reader = PdfReader(io.BytesIO(data))
        fields: list[str] = []
        for name, field in (reader.get_fields() or {}).items():
            label = _field_label(name, field)
            if label and label not in fields:
                fields.append(label)
        first_page = reader.pages[0].extract_text() if reader.pages else ""
        description = re.sub(r"[ \t]+", " ", first_page or "").strip()[:DESCRIPTION_CHARS]
        return {"fields": fields[:MAX_FIELDS], "pdf_pages": len(reader.pages), "description": description}
    except Exception as exc:  # malformed / encrypted PDFs
        return {"fields": [], "pdf_pages": 0, "description": "", "pdf_error": type(exc).__name__}


class PdfEnricher:
    """Fetches each form PDF at most once, only when robots.txt allows it."""

    def __init__(self, fetch: Fetch, max_pdfs: int):
        self._fetch = fetch
        self._robots = RobotsGate(fetch)
        self._max = max_pdfs
        self._cache: dict[str, dict] = {}

    async def enrich(self, form: dict) -> dict:
        url = form["url"]
        if url not in self._cache:
            self._cache[url] = await self._load(url)
        return {**form, **self._cache[url], "fields": self._cache[url].get("fields") or form.get("fields", [])}

    async def _load(self, url: str) -> dict:
        if not await self._robots.allowed(url):
            return {"pdf_status": "disallowed_by_robots_txt"}
        if sum(1 for v in self._cache.values() if v.get("pdf_status") == "parsed") >= self._max:
            return {"pdf_status": "skipped_limit"}
        try:
            status, data = await self._fetch(url)
        except Exception as exc:
            return {"pdf_status": f"fetch_error:{type(exc).__name__}"}
        if status != 200 or not data.startswith(b"%PDF"):
            return {"pdf_status": f"not_pdf:{status}"}
        if len(data) > MAX_PDF_BYTES:
            return {"pdf_status": "too_large"}
        # pypdf is CPU-bound; keep it off the event loop so crawler concurrency stays up.
        return {"pdf_status": "parsed", **await asyncio.to_thread(parse_pdf, data)}
