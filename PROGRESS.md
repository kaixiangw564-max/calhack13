# Progress

| Step | Status |
|---|---|
| 1 Project skeleton | ✅ |
| 2 Bitdeer calls | ✅ |
| 3 Full-site crawl | ✅ |
| 4 Custom Actor | ⏳ |
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

**Still missing**: none. Known limitation: robots.txt disallows `/portal/wp-content/uploads/` (where the PDF forms live), so PDFs are not crawled (see DECISIONS #10).
