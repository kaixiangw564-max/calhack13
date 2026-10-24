# Decisions

When a detail is not specified, decisions follow this priority: ① meets the prize requirements → ② runs reliably in the demo → ③ simplest implementation.

| # | Decision | Reason |
|---|---|---|
| 1 | The repo root is the `plainpath/` layout itself, so `E:\calhack13` maps to `github.com/kaixiangw564-max/calhack13` | The GitHub repo is already named `calhack13`; an extra nesting level would only complicate paths |
| 2 | The first target site is `https://www.dmv.ca.gov/portal/` (instead of the county site) | The disabled parking placard (REG 195) is handled by CA DMV, which gives the demo questions authoritative answers |
| 3 | `MAX_PAGES=300` by default, configurable in `.env` | Apify credits are uncertain; 300 pages covers the key DMV services with headroom over the ≥50-page acceptance bar |
| 4 | The local machine only has Python 3.14, so use `uv venv --python 3.11` for a 3.11 virtualenv | The stack requires 3.11; uagents and its dependencies are more stable on 3.11 |
| 5 | Agent seeds are stored in `.env` (`*_SEED`) | Agent addresses come from their seeds; fixed seeds keep the Agentverse registration and ASI:One discovery addresses stable |
