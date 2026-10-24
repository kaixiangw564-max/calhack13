# Decisions

When a detail is not specified, decisions follow this priority: ① meets the prize requirements → ② runs reliably in the demo → ③ simplest implementation.

| # | Decision | Reason |
|---|---|---|
| 1 | The repo root is the `plainpath/` layout itself, so `E:\calhack13` maps to `github.com/kaixiangw564-max/calhack13` | The GitHub repo is already named `calhack13`; an extra nesting level would only complicate paths |
| 2 | The first target site is `https://www.dmv.ca.gov/portal/` (instead of the county site) | The disabled parking placard (REG 195) is handled by CA DMV, which gives the demo questions authoritative answers |
| 3 | `MAX_PAGES=300` by default, configurable in `.env` | Apify credits are uncertain; 300 pages covers the key DMV services with headroom over the ≥50-page acceptance bar |
| 4 | The local machine only has Python 3.14, so use `uv venv --python 3.11` for a 3.11 virtualenv | The stack requires 3.11; uagents and its dependencies are more stable on 3.11 |
| 5 | Agent seeds are stored in `.env` (`*_SEED`) | Agent addresses come from their seeds; fixed seeds keep the Agentverse registration and ASI:One discovery addresses stable |
| 6 | Bitdeer calls use the official `openai` client with `base_url=https://api-inference.bitdeer.ai/v1` | The official docs (developers.bitdeer.ai/docs/api) state the API is OpenAI-compatible; no custom HTTP code needed. Changing the model only requires editing `.env` |
| 7 | Chat model is `deepseek-ai/DeepSeek-V4.1-Flash`; embeddings use Bitdeer's `BAAI/bge-m3` (1024-dim) | Picked from what `GET /v1/models` actually returns; bge-m3 is multilingual, so Chinese questions match English DMV pages directly, and embeddings also count toward Model Studio usage |
| 8 | `config.py` loads the repo-root `.env` centrally | The backend, agents and tests share one config, and nothing depends on the current working directory |
| 9 | Website Content Crawler uses `crawlerType: cheerio` (plain HTTP) | dmv.ca.gov is server-rendered WordPress (checked with curl: the static HTML already contains the full text). Cheapest and fastest: 300 pages cost $0.097 |
| 10 | Respect robots.txt: dmv.ca.gov disallows `/portal/wp-content/uploads/`, which is where its PDF forms live, so PDFs are not downloaded | Hard constraint from section 3. Form info comes from the form names, numbers and links on HTML pages; PDF links are shown to the user as "view original" |
| 11 | Each crawl run is bounded by `maxCrawlPages`, `memory_mbytes=2048` and `run_timeout=30min` | Apify free plan is $5/month; caps the cost of a single run |
| 12 | Tests and ingest read the latest successful WCC run (`last_run(status=SUCCEEDED)`) instead of a hard-coded dataset ID | After re-crawling, nothing needs to be edited |
| 13 | The same page can appear under both `www.dmv.ca.gov` and `dmv.ca.gov`; dedupe by URL path at ingest (step 5) | 1 of the 271 pages is a duplicate; handling it at ingest keeps the crawl input simple |
