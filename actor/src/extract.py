"""Pure HTML -> service-record extraction for government service pages.

No network access here, so everything is unit-testable against saved fixtures.
Tuned on WordPress-style government sites (dmv.ca.gov) but uses only generic structure:
h1 title, h2/h3/h4 sections, accordion headers, lists, paragraphs, tables, and links.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

# Headings that describe "how to do something" become their own service record.
ACTION_RE = re.compile(
    r"^(apply|applying|renew|renewing|replace|replacing|how (do|to|can)|steps? (to|for)\b|to (apply|renew|replace|get|obtain|register)"
    r"|register|registering|obtain|get an?\b|request|change|update|transfer|submit|mail)",
    re.I,
)
DOCS_HEADING_RE = re.compile(
    r"(what (you|to) (need|bring)|required|requirements|documents?|checklist|bring|eligib|proof|qualif)", re.I
)
DOC_ITEM_RE = re.compile(
    r"\b(proof|documents?|certificate|certification|signature|signed|birth|passport|social security|identity|residency"
    r"|application|form|license|card|title|photo|id)\b",
    re.I,
)
ELIGIBILITY_ITEM_RE = re.compile(r"^you (have|are|were|need to be)\b", re.I)
FEE_RE = re.compile(r"(\$\s?\d[\d,]*(\.\d\d)?|\bno (charge|fee)\b|\bfree\b|\bfees?\b)", re.I)
# "(REG 195)", "(DL 44)", "(REG 156)", "(INF 1125)"
FORM_NO_IN_TEXT_RE = re.compile(r"\(([A-Z]{2,4}\s?-?\s?\d{1,4}[A-Z]?)\)")
# /portal/file/application-for-disabled-person-placard-or-plates-reg-195-pdf/
FORM_NO_IN_SLUG_RE = re.compile(r"-([a-z]{2,4})-(\d{1,4}[a-z]?)-pdf/?$")
ADDRESS_RE = re.compile(r"((?:[^\n]{2,80}\n){0,3}[^\n]*\bCA\s+9\d{4}(?:-\d{4})?)")
ACCORDION_NOISE_RE = re.compile(r"\s*Expand Accordion.*$", re.I)
STOP_HEADINGS = {"need something else?", "related content", "related links"}
NAV_HEADINGS = {"how can we help?", "how can we help"}
SKIP_ANCESTOR_CLASSES = ("page-breadcrumbs", "hero__", "site-header", "site-footer", "skip-link")

MAX_STEPS_CHARS = 6000


@dataclass
class Section:
    heading: str
    lines: list[str] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)

    def text(self) -> str:
        return "\n".join([self.heading, *self.lines]).strip()


def clean(text: str) -> str:
    return " ".join(text.split())


def site_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _skip(el: Tag) -> bool:
    for parent in [el, *el.parents]:
        classes = " ".join(parent.get("class") or [])
        if parent.name in ("nav", "header", "footer") or any(c in classes for c in SKIP_ANCESTOR_CLASSES):
            return True
    return False


def _heading_text(el: Tag) -> str:
    return ACCORDION_NOISE_RE.sub("", clean(el.get_text(" ", strip=True))).rstrip(":")


def split_sections(soup: BeautifulSoup, page_url: str) -> tuple[str, list[Section]]:
    """Returns (h1 title, sections in document order)."""
    main = soup.find("main") or soup.body or soup
    # Keep <br> as line breaks but join inline elements (links, <strong>) with spaces.
    for br in main.find_all("br"):
        br.replace_with("\n")
    h1 = main.find("h1") or soup.find("h1")
    title = clean(h1.get_text(" ", strip=True)) if h1 else clean(soup.title.get_text()) if soup.title else page_url
    sections = [Section(heading=title)]
    for el in main.find_all(["h2", "h3", "h4", "button", "p", "li", "table"]):
        if _skip(el):
            continue
        if el.name == "button" and "accordion" not in " ".join(el.get("class") or []):
            continue
        if el.name in ("h2", "h3", "h4", "button"):
            heading = _heading_text(el)
            if not heading:
                continue
            if heading.lower() in STOP_HEADINGS:
                break
            # Short label headings like "Mail to:" belong to the current section's content.
            if clean(el.get_text()).endswith(":") and el.name != "h2":
                sections[-1].lines.append(heading + ":")
                continue
            sections.append(Section(heading=heading))
            continue
        # p / li / table: skip if nested inside another li/table already captured.
        if any(p.name in ("li", "table") for p in el.parents if p is not main):
            continue
        if el.name == "table":
            rows = [" | ".join(clean(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])) for tr in el.find_all("tr")]
            text = "\n".join(r for r in rows if r.strip(" |"))
        else:
            text = el.get_text(" ")
        text = "\n".join(clean(line) for line in text.splitlines() if clean(line))
        text = re.sub(r" ([.,;:!?)])", r"\1", text)
        if not text:
            continue
        prefix = "- " if el.name == "li" else ""
        sections[-1].lines.append(prefix + text)
        for a in el.find_all("a", href=True):
            sections[-1].links.append((clean(a.get_text(" ", strip=True)), urljoin(page_url, a["href"])))
    return title, [s for s in sections if s.lines or s is sections[0]]


def form_from_link(text: str, href: str) -> dict | None:
    path = urlparse(href).path.lower()
    is_form = "/file/" in path or path.endswith(".pdf") or "(pdf)" in text.lower()
    if not is_form:
        return None
    number = None
    if m := FORM_NO_IN_TEXT_RE.search(text):
        number = re.sub(r"\s*-\s*|\s+", " ", m.group(1)).strip()
    elif m := FORM_NO_IN_SLUG_RE.search(path):
        number = f"{m.group(1).upper()} {m.group(2).upper()}"
    name = re.sub(r"\s*\((PDF|pdf)\)\s*", " ", text).strip(" .")
    if not name or name.upper() in ("PDF", number or ""):
        name = number or path.rstrip("/").split("/")[-1]
    return {"name": name, "number": number, "url": href, "fields": []}


def collect_forms(links: list[tuple[str, str]]) -> list[dict]:
    """Dedupe by URL; keep the most descriptive anchor text as the name."""
    by_url: dict[str, dict] = {}
    for text, href in links:
        form = form_from_link(text, href)
        if not form:
            continue
        key = form["url"].replace("://dmv.", "://www.dmv.") if "://dmv." in form["url"] else form["url"]
        form["url"] = key
        prev = by_url.get(key)
        if prev is None or len(form["name"]) > len(prev["name"]):
            if prev and not form["number"]:
                form["number"] = prev["number"]
            by_url[key] = form
    return list(by_url.values())


def required_documents(sections: list[Section]) -> list[str]:
    docs: list[str] = []
    for s in sections:
        doc_section = bool(DOCS_HEADING_RE.search(s.heading))
        if not (doc_section or ACTION_RE.search(s.heading) or len(sections) == 1):
            continue
        for line in s.lines:
            if not line.startswith("- "):
                continue
            item = line[2:].split("\n")[0]
            if ELIGIBILITY_ITEM_RE.search(item) and not doc_section:
                continue
            if doc_section or DOC_ITEM_RE.search(item):
                if item not in docs and len(item) <= 400:
                    docs.append(item)
    return docs[:40]


def fees(sections: list[Section]) -> str:
    sentences: list[str] = []
    for s in sections:
        for line in s.lines:
            for sentence in re.split(r"(?<=[.!?])\s+|\n", line.lstrip("- ")):
                if FEE_RE.search(sentence) and sentence not in sentences:
                    sentences.append(sentence)
    return " ".join(sentences[:6])


def locations(sections: list[Section]) -> list[dict]:
    out: list[dict] = []
    for s in sections:
        for i, line in enumerate(s.lines):
            for m in ADDRESS_RE.finditer(line):
                address = "\n".join(l.strip() for l in m.group(1).splitlines() if l.strip())
                label = s.lines[i - 1].rstrip(":") if i > 0 and s.lines[i - 1].endswith(":") else s.heading
                if all(o["address"] != address for o in out):
                    out.append({"name": label, "address": address, "hours": ""})
        for text, href in s.links:
            if "/locations/" in href and all(o.get("url") != href for o in out):
                out.append({"name": text or "Office locations", "address": "", "hours": "", "url": href})
    return out[:10]


def _record(site: str, url: str, title: str, service: str, sections: list[Section], crawled_at: str) -> dict:
    links = [link for s in sections for link in s.links]
    return {
        "site": site,
        "url": url,
        "title": title,
        "service": service,
        "steps_raw": "\n\n".join(s.text() for s in sections)[:MAX_STEPS_CHARS],
        "required_documents": required_documents(sections),
        "forms": collect_forms(links),
        "locations": locations(sections),
        "fees": fees(sections),
        "crawled_at": crawled_at,
    }


def extract_records(soup: BeautifulSoup, url: str, crawled_at: str) -> list[dict]:
    """One page-level record per service page, plus one record per "how to" section.

    Pages with no actionable content (no forms, no action sections, no document lists) yield nothing.
    """
    title, sections = split_sections(soup, url)
    site = site_of(url)
    action_sections = [
        s for s in sections[1:] if ACTION_RE.search(s.heading) and s.heading.lower() not in NAV_HEADINGS
    ]
    page = _record(site, url, title, title, sections, crawled_at)
    if not (action_sections or page["forms"] or any(DOCS_HEADING_RE.search(s.heading) for s in sections)):
        return []
    records = [page]
    for s in action_sections:
        service = s.heading.rstrip("?")
        if len(service.split()) <= 2:  # "Renew", "Mail" -> "Renew — Driver's License & ID Card Online Renewal"
            service = f"{service} — {title}"
        records.append(_record(site, url, title, service, [s], crawled_at))
    return records
