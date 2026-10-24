# PlainPath Gov Extractor

Turn a public government service website into **structured, citeable service records**: what the service is, the official step-by-step text, required documents, PDF forms (with their fillable field names), mailing addresses and offices, and fees. Every record carries its source URL and crawl timestamp.

Built for [PlainPath](https://github.com/kaixiangw564-max/calhack13), which helps blind and low-vision users, older adults, and people with limited English use government websites in their own language. It works well on WordPress-style government portals (tested on `dmv.ca.gov`), and only uses generic page structure (headings, lists, accordions, links), so it is not tied to one site.

## What it does

1. Crawls the start URLs on the same domain with Crawlee (BeautifulSoup), **respecting robots.txt**.
2. Splits each page into sections (headings and FAQ accordions) and emits:
   - one **page-level record** per service page, and
   - one record per **"how to" section** (e.g. "Applying for a DP Parking Placard", "How do I replace my placard").
   Navigation-only pages produce no records.
3. Detects **form links** (e.g. `Application for Disabled Person Placard or Plates (REG 195) (PDF)`), extracts the form number and name, then downloads the PDF **only if robots.txt allows it** and extracts its fillable field labels and first-page instructions with `pypdf`.
4. Extracts mailing addresses (e.g. `DMV Placard, PO Box 942869, Sacramento, CA 94269-0001`), office-locator links, and fee sentences.

## Input

| Field | Type | Default | Description |
|---|---|---|---|
| `startUrls` | array | `[{"url": "https://www.dmv.ca.gov/portal/"}]` | Pages to start from. Crawling stays on the same domain. |
| `maxPagesPerCrawl` | integer | `100` | Maximum HTML pages to visit. |
| `extractPdfFields` | boolean | `true` | Download linked PDF forms (robots.txt permitting) and extract field names. |
| `maxPdfs` | integer | `150` | Maximum PDFs to download and parse. |
| `excludeUrlGlobs` | array | WordPress internals, feeds, search, news | Links matching these globs are not crawled as pages. |

## Output

One dataset item per service:

```json
{
  "site": "dmv.ca.gov",
  "url": "https://www.dmv.ca.gov/portal/vehicle-registration/license-plates-decals-and-placards/disabled-person-parking-placards-plates/",
  "title": "Disabled Person Parking Placards & Plates",
  "service": "Applying for a DP Parking Placard or DP License Plates",
  "steps_raw": "Applying for a DP Parking Placard or DP License Plates\n- Apply online using the Disabled Person Parking Placard Form Application.\n- Apply by mail or in office: Complete and sign an Application for Disabled Person Placard or Plates (REG 195) (PDF). ...",
  "required_documents": ["Complete and sign an Application for Disabled Person Placard or Plates (REG 195) (PDF).", "..."],
  "forms": [
    {
      "name": "Application for Disabled Person Placard or Plates (REG 195)",
      "number": "REG 195",
      "url": "https://www.dmv.ca.gov/portal/file/application-for-disabled-person-placard-or-plates-reg-195-pdf/",
      "fields": ["DL No. Driver license number or identification card number ...", "..."],
      "pdf_status": "parsed",
      "pdf_pages": 3,
      "description": "APPLICATION FOR DISABLED PERSON PLACARD OR PLATES ..."
    }
  ],
  "locations": [{"name": "Mail to", "address": "DMV Placard\nPO Box 942869\nSacramento, CA 94269-0001", "hours": ""}],
  "fees": "Submit applicable fees when requesting a temporary placard. ...",
  "crawled_at": "2026-10-24T06:20:00Z"
}
```

`forms[].pdf_status` is one of `parsed`, `disallowed_by_robots_txt`, `skipped_limit`, `too_large`, `not_pdf:<status>`, `fetch_error:<type>`.

## Responsible crawling

- Only public pages; nothing behind a login.
- robots.txt is enforced for both pages (Crawlee) and PDF downloads (separate per-origin check).
- The output only restates official content and always links back to the source. Always verify with the original page.

## Local development

```bash
cd actor
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt pytest pytest-asyncio
.venv/Scripts/python -m pytest          # offline tests against saved fixtures
.venv/Scripts/python -m src             # local run; input in storage/key_value_stores/default/INPUT.json
apify push                              # deploy
```
