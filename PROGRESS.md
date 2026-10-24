# Progress

| Step | Status |
|---|---|
| 1 Project skeleton | ✅ |
| 2 Bitdeer calls | ✅ |
| 3 Full-site crawl | ✅ |
| 4 Custom Actor | ✅ (Store publishing pending: human) |
| 5 Ingest | ✅ |
| 6 Q&A endpoint | ✅ |
| 7 Accessible website | ✅ |
| 8 Navigator + Answer Agent | 🟡 Code + network path verified; ASI:One UI acceptance pending |
| 9 Crawler + Form Agent + Cards | 🟡 Flow + live crawl verified; ASI:One UI acceptance pending |
| 10 Deployment | 🟡 Deploy-ready, not deployed (team decision: local demo) |
| 11 README and submission | ✅ README; Devpost / ASI:One submission by the team |

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

## Step 5: Ingest ✅

**Done**:
- `backend/app/core/db.py`: Atlas client, regular indexes, and the Vector Search index `chunks_vector` (1024-dim cosine, filters `site` and `kind`); waits until queryable
- `backend/app/core/ingest.py`: WCC pages become heading-based chunks (title prefix, links stripped, www/non-www deduped, site title suffix removed). Extractor records are written to `services`; each unique form goes to `forms` plus one form chunk (number, name, official PDF URL, services, source pages, first-page instructions, field labels). `sites` is updated. Idempotent re-ingest
- `backend/app/core/retrieval.py`: `vector_search()` (`$vectorSearch` + score), `exact_form_chunks()` (form-number match), `search()` (hybrid, top 8)
- `backend/app/main.py`: `GET /health`, `POST /webhook/apify` (shared-secret header, background ingest)
- `backend/app/core/crawl.py`: both Actor starts attach the ingest webhook when `BACKEND_PUBLIC_URL` is public
- `backend/scripts/run_ingest.py`: ingests the latest successful runs (same code as the webhook)
- `.env.example`: `APIFY_WEBHOOK_SECRET`; requirements: `pymongo[srv]`

**Verification**:
- `python -m scripts.run_ingest`: 270 pages, 1,245 page chunks; 257 extractor records (256 unique services), 168 forms, 168 form chunks; index `chunks_vector` READY/queryable
- `pytest tests/test_retrieval.py`: 6 passed against Atlas. Placard-renewal (English and Chinese), REAL ID documents and change-of-address queries hit the right pages in the top 5; "What is form REG 195?" returns the REG 195 form chunk first (exact match); "Which form do I fill out to apply for a disabled person placard?" finds REG 195 among form chunks
- `pytest tests/test_ingest_unit.py`: 9 passed (offline: chunking, form numbers, URL canonicalization, title suffix, webhook auth, /health)
- Full backend suite: 22 passed

**Still missing**: webhook not yet exercised end-to-end by Apify (needs the public backend URL from step 10; until then ingest runs via the script).

## Step 6: Q&A endpoint ✅

**Done**:
- `backend/app/core/answer.py`: `ask(question, language, site)` does hybrid retrieval (plus an English rewrite for non-English questions), applies the score gate, has Bitdeer produce grounded JSON (steps/documents/forms with excerpt citations), maps citations to `source_url`/`crawled_at`, resolves forms from the `forms` collection, and adds a localized disclaimer. The not_found path returns a localized message plus the site's contact page
- `backend/app/core/llm.py`: `reasoning_effort` (default `none`); clear error when the model hits max_tokens with no answer
- `backend/app/main.py`: `POST /ask`, `POST /crawl`, `GET /crawl/{run_id}` (with pydantic validation)
- `backend/tests/test_ask.py`: acceptance tests (Chinese questions as Unicode escapes; the file is ASCII-only)

**Verification**: `cd backend && ../.venv/Scripts/python -m pytest tests/test_ask.py`: 6 passed
- 3 Chinese questions (renew disabled placard, REAL ID documents, change of address): every step is in Chinese, has a `https://www.dmv.ca.gov/` `source_url` and a `crawled_at`, the sources include the expected page (dpp-renewal / real-id / change-of-address), and there are no leftover `[n]` markers
- Unrelated question (California fishing license): `not_found: true`, Chinese message, contact page `contacting-dmv`
- "What is form REG 195 used for?": forms include REG 195 with its official PDF link
- Manual review: answers are short and plain, restate the official text (e.g. REAL ID: identity proof, name-change docs, 2 residency proofs, SSN, in-person visit). About 10 s per answer; not-found takes about 2 s
- Full backend suite: 28 passed

**Still missing**: none for step 6. Known nit: the REAL ID answer can list related unnumbered PDFs (e.g. a translated fact sheet) as forms; to refine in the Form agent (step 9).

## Step 7: Accessible website ✅

**Done** (`web/`, Next.js 16.4.3 App Router + TypeScript + Tailwind 4):
- `app/page.tsx`: header, a single question form, footer note (official sources only, no legal/medical advice)
- `app/components/AskPanel.tsx`: textarea (Enter submits), answer-language picker, "Speak your question" (Web Speech recognition, auto-submits), "Get the steps", example questions; results in large type with per-step "View original" link, "Read aloud" button and "Checked on <date>"; "Read all steps aloud"; documents; official forms; not-found message with contact link; localized disclaimer
- `app/api/ask/route.ts`: server-side proxy to FastAPI (`BACKEND_URL`)
- `app/globals.css`: high-contrast tokens, 20px base, focus ring, skip link, reduced motion; `app/layout.tsx`: Atkinson Hyperlegible
- Backend hardening found during testing: JSON mode for model output, 503 instead of 500 on unusable output

**Verification** (backend on :8000, `npm run dev` on :3000, built-in browser):
- Keyboard only: Tab focuses "Skip to main content" (visible focus ring); Enter, then Tab, lands on the question box (accessible name "What do you need to do?"); typed the question and pressed Enter; the status live region announced "Answer ready with 9 steps." and focus moved to the "Your steps" heading. Tab order continues "Read all steps aloud", "View original official page for step 1 (opens in a new tab)" (dpp-renewal, `target=_blank`), "Read aloud step 1"; Enter starts speech (`aria-pressed=true`, speechSynthesis speaking), Enter again stops it
- axe-core 4.14 (wcag2a/2aa/21a/21aa/22aa + best-practice): **0 violations** on the initial page (42 passes) and on the results page (44 passes), 0 incomplete, including color-contrast
- `npm run lint` clean, `tsc --noEmit` clean, `npm run build` succeeds; backend suite 28 passed

**Voice input (manual stop)**: recording runs until the user presses "Stop listening" (continuous recognition with live interim text; if the browser ends a session on silence/network, it restarts and keeps the transcript). Verified with a simulated SpeechRecognition in the built-in browser (auto-restart, transcript accumulation, submit on manual stop, 10-step answer) and by the user with a real microphone in Chrome.

**Still missing**: none.

## Step 8: Navigator + Answer Agent 🟡

**Done**:
- `backend/app/core/intent.py`: Bitdeer intent extraction {language, service, location, site, question}
- `agents/common.py`: agent factory (mailbox, handle, README, description), automatic Agentverse registration via `AGENTVERSE_API_KEY`, chat helpers, typed `AnswerRequest`/`AnswerResponse`, Markdown answer formatting with localized labels, warm-up
- `agents/answer.py`: Answer Agent (Agent Chat Protocol plus the typed `PlainPathAnswer` protocol)
- `agents/navigator.py`: Navigator Agent (ASI:One entry; intent, then Answer Agent, then cited Markdown reply; in-process fallback on failure/timeout; per-conversation memory of site/language; timing logs)
- `agents/run_all.py` (Bureau, port 8001); `agents/readme/*.md` (Agentverse profiles); `agents/local_chat_test.py`, `agents/network_chat_test.py`
- Agent seeds in `.env` (stable addresses)

**Agents**:
- PlainPath Navigator `@plainpath`: `agent1qd97m2my59lucx4aryd4x6tvwr9g3mxq8pdpgyj0rvesk0qdcxlvshpejz3`
- PlainPath Answer `@plainpath-answer`: `agent1qf73u7yaea87dcldq0prx4luz4kw6fq8geu38rnuu56clxffxe0cjcwm0j3`

**Verification**:
- Local Bureau test (`agents/local_chat_test.py`, Chinese demo question): Navigator replied with Chinese numbered steps, each with a dmv.ca.gov link and check date, plus the REG 195 form link
- Agentverse: both registered as mailbox agents ("Successfully registered as mailbox agent in Agentverse"); profile read back via the API (name, handle, README, description, starter prompts); Almanac API registration and Chat Protocol manifests published
- Network path (`agents/network_chat_test.py`): a separate agent sent a ChatMessage through `agentverse.ai/v2/agents/mailbox/submit`, the same inbound path as ASI:One: DELIVERED, ACK after 1.5 s, full cited answer after 7.4 s
- ASI:One: the agent profile page (`@plainpath`) shows our description; earlier, ASI:One's planner reached the Navigator 3 times (intent logged), which led to fix #41

**Still missing**: completing a Q&A in the ASI:One chat UI. After the fixes, messages typed in the ASI:One chat stay "loading" and never reach the agent (no "chat from" log), while the same mailbox path works from our test agent, so this is a platform-side issue to retest later. Agentverse mailbox polling also shows intermittent 401/503 from Agentverse. Mitigation planned for step 10: public endpoint instead of mailbox polling.

## Step 9: Crawler + Form Agent + Interactive Cards 🟡

**Done**:
- `backend/app/core/refresh.py`: freshness check, start/join a refresh, progress, finish (WCC -> ingest -> Gov Extractor -> ingest), simulated failure switch
- `backend/app/core/forms.py`: checklist (documents plus explained forms) from `services`/`forms` with action-specific filtering and language-matched guides
- `agents/crawler.py` (`@plainpath-crawler`), `agents/form.py` (`@plainpath-forms`): Chat Protocol plus typed protocols (`PlainPathCrawl`, `PlainPathForm`)
- `agents/navigator.py`: full orchestration with cards (form / carousel / detail), card-click handling (submit_request, open_step, explain_form, done), crawl progress relay, recovery paths
- `agents/common.py`: card helpers, new messages, localized UI labels; `agents/run_all.py`: Bureau with 4 agents; `agents/local_chat_test.py`: multi-message script with card kinds and escaped non-ASCII input

**Agents** (all registered as Agentverse mailbox agents):
- Navigator `@plainpath`: agent1qd97m2my59lucx4aryd4x6tvwr9g3mxq8pdpgyj0rvesk0qdcxlvshpejz3
- Crawler `@plainpath-crawler`: agent1qgv9epq0fl82vwmgjpsm84a0d2xl8ml7wm3rjkxfz57caw8q2hq4qpycqwv
- Answer `@plainpath-answer`: agent1qf73u7yaea87dcldq0prx4luz4kw6fq8geu38rnuu56clxffxe0cjcwm0j3
- Form `@plainpath-forms`: agent1q0tltskhqswrthpdtnuy72hxyuaxyu3jcn6ggechsdfu38ttfly6vaxpyu4

**Verification** (local Bureau, `agents/local_chat_test.py`):
1. "hi" -> self-introduction plus `form` card (service, location, website, language)
2. Card submit (renew disabled parking placard, Contra Costa, dmv.ca.gov, zh) -> `carousel` card (9 Chinese steps, each with the dpp-renewal link and date) -> `detail` checklist (renewal requirements, REG 195A with 8 explained fields, "Explain REG 195A" CTA)
3. "Explain REG 195A" click -> purpose plus field explanations
4. Chinese demo question -> carousel plus checklist (crawler check: fresh, 3.8 h old)
5. Failure: `CRAWL_MAX_AGE_HOURS=0 CRAWLER_SIMULATE_FAILURE=1` -> Crawler logs the simulated Apify failure; the answer starts with "could not refresh ... saved official data from 2026-10-24" and still returns steps plus checklist
6. Unrelated (fishing license) -> "not covered, currently: dmv.ca.gov" plus form card
- Network: `agents/network_chat_test.py` through `agentverse.ai/v2/agents/mailbox/submit` -> DELIVERED, ACK 1.8 s, first answer 6.5 s
- Backend suite: 28 passed

**Live refresh** (approved; `CRAWL_MAX_AGE_HOURS=0`, local Bureau, Chinese demo question): the chat received 5 progress messages with real Apify page counts (4, 18, 30, 49, 64 pages), then the carousel answer prefixed with "the refresh continues in the background; answering from saved official data from 2026-10-24", then the checklist. The background refresh finished on its own: WCC 264 pages -> 1,151 page chunks; Gov Extractor 224 records / 147 forms -> 147 form chunks. `sites.last_crawled_at` moved to 2026-10-24T11:20:48Z (fresh), status back to `ready`; only the two new ingest batches remain in `chunks`. Apify spend for the month after the refresh: $0.378. On the refreshed data, the retrieval/ask/crawl/extractor acceptance tests pass (16 passed) and the checklist still picks REG 195A (renew), REG 195 (apply), REG 156 (replace).

**Still missing**: the 6-step flow inside the ASI:One UI (blocked by the platform-side "loading" issue from step 8).

## Step 10: Deployment 🟡 (deploy-ready, not deployed)

**Done**: `backend/Dockerfile`, `web/Dockerfile`, `agents/Dockerfile`, `.dockerignore` files, `.do/app.yaml` (App Platform:
services `api` + `web`, worker `agents`, ingress `/backend` -> api, `/` -> web, website -> API via `${api.PRIVATE_URL}`,
secrets as `type: SECRET` without values), `scripts/deploy_do.py` (fills secrets from `.env`, then propose/create/update via the
DigitalOcean Apps API; `--dry-run` prints the redacted spec), `scripts/run_local.py` (one-command local demo).

**Verification**: `scripts/deploy_do.py --dry-run` builds the full spec from `.env` with no missing secrets. Docker is not
installed locally, so images were not built; the Dockerfiles use the same commands that run locally.

**Not done (team decision)**: no DigitalOcean credit is available and DigitalOcean requires a payment method, so the app was
not created. The demo runs locally; the agents are online through Agentverse mailboxes while `scripts/run_local.py` runs.
The MLH DigitalOcean requirement and "keeps running after the event" are therefore not met (see DECISIONS #49-51).

## Step 11: README and submission ✅

**Done**: `README.md` (English): demo walkthrough (ASI:One 6-step flow, website, 3-minute script), architecture diagram and answer
pipeline, local setup and run steps, configuration reference, API, agent list with addresses, a requirement-by-requirement
prize table with honest status, "How we use Bitdeer AI Model Studio", "How we use Apify", accessibility, guardrails, testing,
deployment and known limitations.

**Verification**: backend 28 passed, actor 8 passed, web lint + `tsc --noEmit` clean.

**Still missing (team)**: push to the public GitHub repo (after a full-history secret scan), Devpost submission, ASI:One / Cal Hacks
agent registration form, demo video; ASI:One UI acceptance of the main flow when the platform delivers messages again.
