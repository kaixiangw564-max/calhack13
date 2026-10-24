# Progress

| Step | Status |
|---|---|
| 1 Project skeleton | ✅ |
| 2 Bitdeer calls | ✅ |
| 3 Full-site crawl | ✅ |
| 4 Custom Actor | ✅ (Store publishing pending: human) |
| 5 Ingest | ⏳ |
| 6 Q&A endpoint | ⏳ |
| 7 Accessible website | ⏳ |
| 8 Navigator + Answer Agent | ⏳ |
| 9 Crawler + Form Agent + Cards | ⏳ |
| 10 Deployment | ⏳ |
| 11 README and submission | ⏳ |

---

## Step 1: Project skeleton ✅

**Done**: directory structure (actor / backend / agents / web), `.gitignore`, `.env.example`, README skeleton, DECISIONS, PROGRESS; git initialized and remote set to `kaixiangw564-max/calhack13`.

**Verification**: created a temporary `.env` and ran `git status --porcelain --ignored`: `.env` shows only as ignored (`!!`) and never as untracked or staged.

**Still missing**: the human needs to fill in `.env` (Bitdeer key/URL/model are required for step 2).

## Step 2: Bitdeer calls ✅

**Done**:
- `backend/app/core/config.py`: loads the repo-root `.env` centrally
- `backend/app/core/llm.py`: `chat()` and `chat_json()` using the `openai` client with the Bitdeer base_url (`https://api-inference.bitdeer.ai/v1`), 2 automatic retries
- `backend/app/core/embeddings.py`: `embed()` and `embed_one()` using `BAAI/bge-m3` (1024-dim), batches of 32
- `backend/tests/test_llm.py`: 3 tests that make real API calls (chat reply, JSON output, embedding similarity)
- Python 3.11 venv: `uv venv --python 3.11 .venv`, then `uv pip install --python .venv/Scripts/python.exe -r backend/requirements.txt`

**Verification**: `cd backend && ../.venv/Scripts/python -m pytest -v` gives 3 passed. `GET /v1/models` confirmed the configured chat model `deepseek-ai/DeepSeek-V4.1-Flash` and `BAAI/bge-m3` are available. Embedding check: "renew disabled parking placard" is closer to "renew disabled parking permit" than to "fishing license fees".

**Still missing**: none.

## Step 3: Full-site crawl ✅

**Done**:
- `backend/app/core/crawl.py` (apify-client 3.3): `start_crawl()` (with an optional webhook), `get_status()` (pages done and spend so far), `wait_for_run()`, `latest_succeeded_run()`, and `iter_pages()` (normalizes items to `{site, url, title, text, markdown, crawled_at}` and drops pages under 200 characters)
- `backend/scripts/run_crawl.py`: starts the crawl and polls its progress
- `backend/tests/test_crawl.py`: acceptance test

**Verification**: ran `cd backend && ../.venv/Scripts/python -m scripts.run_crawl` against `https://www.dmv.ca.gov/portal/`. Run `3zfvSKW3hbNcP5GpL`, dataset `jQEqlksKPK3pw7XZb`: SUCCEEDED, 277 items, **271 pages with content** (median 1,172 characters), cost **$0.097**. `pytest tests/test_crawl.py` gives 2 passed. Demo-critical pages were crawled: disabled-person-parking-placards-plates, dpp-renewal, dpp-application, dpp-replacement, real-id, real-id-checklist, online-change-of-address.

**Still missing**: none. (The PDF note originally written here was revised in step 4; see DECISIONS #10.)

## Step 4: Custom Actor "PlainPath Gov Extractor" ✅

**Done**:
- `actor/src/extract.py`: pure-function, rule-based extraction (HTML to the section 6 record format): headings/accordions become sections; one page-level record per page plus one record per "how to" section; form links become `{name, number, url}`; mailing addresses, office links and fee sentences are extracted
- `actor/src/pdf.py`: per-origin robots.txt check (Crawlee `RobotsTxtFile`), download only when allowed, pypdf extracts field labels, page count and first-page text (parsed in a thread)
- `actor/src/main.py`: Crawlee `BeautifulSoupCrawler` (`respect_robots_txt_file=True`), www/non-www canonicalization, `maxCrawlDepth` input
- `actor/.actor/` (actor.json, input/dataset schema), `Dockerfile` (apify/actor-python:3.11), `README.md` (Store page)
- `backend/app/core/crawl.py`: `service_page_urls()` (picks service pages from WCC results), `start_extractor()`; `backend/scripts/run_extractor.py`
- Pipeline: **Website Content Crawler finds every page, then service pages go to Gov Extractor (maxCrawlDepth=0)**

**Verification**:
- `cd actor && .venv/Scripts/python -m pytest`: 8 passed (offline fixtures: REG 195 number/name/link, mailing address, fees, robots group merging)
- Local run (49 pages): REG 195 PDF parsed, 32 field labels
- Before each `apify push`, replayed the CLI's file selection: 17 files, no `.env`/`storage/`/`.venv/`, secret scan clean. Deployed: Actor `kaikeru/plainpath-gov-extractor` (ID `QK2F1eYw6diBYA55E`), build 0.1.3
- Platform run `qfcdZhdzWN0v2PIWh` (dataset `gkLtetSe66ciTqSyd`): SUCCEEDED, 110 start pages, **257 records**, 100 pages with records, 168 unique forms (163 PDFs parsed, 87 with form numbers, 99 with field labels), cost **$0.012**
- `cd backend && ../.venv/Scripts/python -m pytest tests/test_extractor.py`: 2 passed (≥5 records in the section 6 format; REG 195 present with PDF fields)
- Demo pages covered: disabled placard main page (3 records), REAL ID, change of address

**Earlier attempts** (kept for the record): a 150-page BFS from the home page succeeded but missed the main placard page; a 400-page BFS TIMED-OUT at 30 minutes because pypdf blocked the event loop. Fixed by threaded PDF parsing plus the WCC-to-Extractor pipeline.

**Output schema (for Store publication)**: added `.actor/output_schema.json` (`results` -> default dataset items) and a field-level JSON Schema in `dataset_schema.json`; validated with the CLI's official validators (actor/output/dataset) and AJV against all 257 platform items + fixture items. Build **0.1.4** SUCCEEDED; no Actor run started (run count 3 before and after push).

**Still missing (human)**: publish the Actor publicly on Apify Store (Console → Actor → Publication). Known small issue: PDFs over 15 MB are fully downloaded before being marked `too_large` (2 files).
