"""PlainPath Crawler Agent: keeps official data fresh.

Given {site}: checks `sites` in MongoDB. Fresh (< CRAWL_MAX_AGE_HOURS) -> ready. Stale or missing -> starts the Apify
pipeline (Website Content Crawler -> ingest -> PlainPath Gov Extractor -> ingest), reports progress to the caller,
and after PROGRESS_WAIT_S answers from the cached data while the refresh finishes in the background. If Apify fails,
returns the cached data with its timestamp. Speaks the Agent Chat Protocol too ("refresh dmv.ca.gov").
"""
import asyncio

from common import (
    CrawlProgress,
    CrawlRequest,
    CrawlResult,
    ack,
    blocking,
    env,
    make_agent,
    reply,
    text_of,
)
from uagents import Context, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, chat_protocol_spec

from app.core import refresh
from app.core.intent import known_sites

PROGRESS_WAIT_S = int(env("CRAWL_PROGRESS_WAIT_S", "45"))
POLL_S = 10

agent = make_agent(
    name="PlainPath Crawler",
    seed_env="CRAWLER_SEED",
    handle="plainpath-crawler",
    description=(
        "Keeps PlainPath's copy of official government websites fresh with Apify (Website Content Crawler + "
        "PlainPath Gov Extractor). Reports crawl progress and falls back to cached data with its date if a crawl fails."
    ),
    readme="crawler.md",
    starter_prompts=["Is the dmv.ca.gov data fresh?", "refresh dmv.ca.gov"],
)

chat = Protocol(spec=chat_protocol_spec)
crawls = Protocol(name="PlainPathCrawl", version="0.1.0")
_background: set[asyncio.Task] = set()


async def ensure_fresh(ctx: Context, site: str, on_progress=None) -> CrawlResult:
    state = await blocking(refresh.check, site)
    if state["fresh"]:
        return CrawlResult(request_id="", ready=True, crawled_at=state["crawled_at"])
    try:
        started = await blocking(refresh.start, site)
    except Exception as exc:  # Apify down, quota exhausted, simulated failure...
        ctx.logger.warning(f"refresh of {site} failed to start: {exc}")
        return CrawlResult(
            request_id="", ready=state["exists"], crawled_at=state["crawled_at"], used_cache=state["exists"],
            error=f"{type(exc).__name__}: {exc}"[:300],
        )

    run_id = started["run_id"]
    if not started["joined"]:
        task = asyncio.get_running_loop().create_task(blocking(refresh.finish, site, run_id))
        _background.add(task)
        task.add_done_callback(_background.discard)

    waited = 0
    while waited < PROGRESS_WAIT_S:
        await asyncio.sleep(POLL_S)
        waited += POLL_S
        p = await blocking(refresh.progress, run_id)
        if on_progress:
            await on_progress(p)
        if p["done"]:
            break
    state = await blocking(refresh.check, site)
    still_running = state["refreshing_run_id"] is not None
    return CrawlResult(
        request_id="", ready=state["exists"], crawled_at=state["crawled_at"],
        used_cache=still_running, refreshing=still_running,
    )


@crawls.on_message(CrawlRequest, replies={CrawlProgress, CrawlResult})
async def on_crawl_request(ctx: Context, sender: str, req: CrawlRequest) -> None:
    async def progress(p: dict) -> None:
        await ctx.send(sender, CrawlProgress(request_id=req.request_id, pages_done=p["pages_done"], status=p["status"]))

    try:
        result = await ensure_fresh(ctx, req.site, progress)
    except Exception as exc:
        ctx.logger.exception("crawler failed")
        result = CrawlResult(request_id="", ready=False, error=f"{type(exc).__name__}: {exc}"[:300])
    result.request_id = req.request_id
    await ctx.send(sender, result)


@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ack(ctx, sender, msg)
    text = text_of(msg).lower()
    sites = await blocking(known_sites)
    site = next((s for s in sites if s in text), sites[0] if sites else None)
    if not site:
        await reply(ctx, sender, "No official websites have been crawled yet.")
        return
    if "refresh" not in text:
        s = await blocking(refresh.check, site)
        await reply(ctx, sender, f"{site}: last crawled {s['crawled_at']} ({s['age_hours']} h ago), fresh={s['fresh']}.")
        return

    async def progress(p: dict) -> None:
        await reply(ctx, sender, f"Crawling {site}: {p['pages_done']} pages ({p['status']})")

    r = await ensure_fresh(ctx, site, progress)
    note = "refresh continues in the background" if r.refreshing else ("using cached data" if r.used_cache else "fresh")
    await reply(ctx, sender, f"{site}: data from {r.crawled_at} ({note}){'; error: ' + r.error if r.error else ''}.")


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    pass


agent.include(chat, publish_manifest=True)
agent.include(crawls, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
