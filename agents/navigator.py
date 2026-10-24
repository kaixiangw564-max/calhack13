"""PlainPath Navigator Agent: the ASI:One entry point and orchestrator.

Main flow (all inside the ASI:One chat):
1. Bitdeer extracts {language, service, location, site}. Missing information -> an Interactive Card form.
2. Crawler Agent checks data freshness; if a live Apify refresh runs, its progress is relayed into the chat.
3. Answer Agent returns cited steps -> carousel card (one card per step: text, official link, crawl date).
4. Form Agent returns documents + explained forms -> checklist card.
5. Any failing agent is recovered: Crawler failure -> cached data with its date; Answer/Form failure -> the same core
   pipeline in-process; nothing relevant on the official site -> "not found" + the agency's contact page.
Every card message also carries the full answer as text, so clients without card support lose nothing.
"""
import asyncio
import json
import time
import uuid

from answer import agent as answer_agent
from common import (
    AnswerRequest,
    AnswerResponse,
    CrawlProgress,
    CrawlRequest,
    CrawlResult,
    FormRequest,
    FormResponse,
    ack,
    blocking,
    card_selection,
    core_answer,
    day,
    format_answer,
    format_checklist,
    labels,
    make_agent,
    reply,
    reply_card,
    text_of,
    warm_up,
)
from crawler import PROGRESS_WAIT_S
from crawler import agent as crawler_agent
from form import agent as form_agent
from uagents import Context, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, chat_protocol_spec

from app.core import forms as core_forms
from app.core import refresh as core_refresh
from app.core.forms import LANGUAGE_NAMES
from app.core.intent import extract_intent, known_sites

ANSWER_TIMEOUT_S = 120
FORM_TIMEOUT_S = 90
CRAWL_TIMEOUT_S = PROGRESS_WAIT_S + 60

agent = make_agent(
    name="PlainPath Navigator",
    seed_env="NAVIGATOR_SEED",
    handle="plainpath",
    description=(
        "Plain-language help with government websites (e.g. California DMV) in any language: "
        "numbered steps, required documents and official forms, each linked to the official source."
    ),
    readme="navigator.md",
    starter_prompts=[
        "I want to renew my disabled parking placard in Contra Costa. I only speak Chinese.",
        "What documents do I need for a REAL ID?",
        "I moved. How do I change my address with the DMV?",
    ],
)

chat = Protocol(spec=chat_protocol_spec)
crawl_replies = Protocol(name="PlainPathCrawlClient", version="0.1.0")
_pending_crawls: dict[str, tuple[asyncio.Future, str, str]] = {}  # request_id -> (future, user, language)


# ---------------- agent calls with recovery ----------------


async def check_data(ctx: Context, user: str, site: str, language: str) -> CrawlResult:
    request_id = str(uuid.uuid4())
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    _pending_crawls[request_id] = (future, user, language)
    try:
        await ctx.send(crawler_agent.address, CrawlRequest(request_id=request_id, site=site))
        return await asyncio.wait_for(future, timeout=CRAWL_TIMEOUT_S)
    except Exception as exc:  # Crawler agent down or too slow: use whatever data we have
        ctx.logger.warning(f"Crawler Agent unavailable ({type(exc).__name__}); using cached data")
        state = await blocking(core_refresh.check, site)
        return CrawlResult(request_id=request_id, ready=state["exists"], crawled_at=state["crawled_at"],
                           used_cache=not state["fresh"], error="crawler unavailable")
    finally:
        _pending_crawls.pop(request_id, None)


@crawl_replies.on_message(CrawlProgress)
async def on_crawl_progress(ctx: Context, sender: str, msg: CrawlProgress) -> None:
    pending = _pending_crawls.get(msg.request_id)
    if not pending:
        return
    _, user, language = pending
    lab = await blocking(labels, language)
    await reply(ctx, user, f"{lab['crawl_progress']}: {msg.pages_done}")


@crawl_replies.on_message(CrawlResult)
async def on_crawl_result(ctx: Context, sender: str, msg: CrawlResult) -> None:
    pending = _pending_crawls.get(msg.request_id)
    if pending and not pending[0].done():
        pending[0].set_result(msg)


async def get_answer(ctx: Context, question: str, language: str, site: str | None) -> dict:
    response, status = await ctx.send_and_receive(
        answer_agent.address, AnswerRequest(question=question, language=language, site=site),
        response_type=AnswerResponse, timeout=ANSWER_TIMEOUT_S,
    )
    if isinstance(response, AnswerResponse) and response.ok:
        return json.loads(response.result_json)
    reason = response.error if isinstance(response, AnswerResponse) else status.detail
    ctx.logger.warning(f"Answer Agent unavailable ({reason}); answering in-process")
    return await blocking(core_answer.ask, question, language, site)


async def get_checklist(ctx: Context, question: str, language: str, site: str | None, urls: list[str]) -> dict:
    response, status = await ctx.send_and_receive(
        form_agent.address, FormRequest(question=question, language=language, site=site, source_urls=urls),
        response_type=FormResponse, timeout=FORM_TIMEOUT_S,
    )
    if isinstance(response, FormResponse) and response.ok:
        return json.loads(response.result_json)
    reason = response.error if isinstance(response, FormResponse) else status.detail
    ctx.logger.warning(f"Form Agent unavailable ({reason}); building checklist in-process")
    return await blocking(core_forms.checklist, urls, language, site, question)


# ---------------- cards ----------------


def steps_card(result: dict, site: str, lab: dict) -> dict:
    return {
        "title": lab["your_steps"],
        "subtitle": site,
        "items": [
            {
                "id": f"step-{i}",
                "title": f"{lab['step']} {i}",
                "subtitle": step["text"][:280],
                "secondary_text": f"{lab['checked']} {day(step['crawled_at'])}",
                "badges": [{"label": site, "variant": "info"}],
                "primary_cta": {"label": lab["source"], "selection": {"action": "open_step", "step": i, "url": step["source_url"]}},
            }
            for i, step in enumerate(result["steps"], start=1)
        ],
    }


def checklist_card(result: dict, lab: dict) -> dict:
    rows = [{"label": lab["bring"], "value": d["text"][:280]} for d in result["documents"]]
    rows += [
        {"label": f.get("number") or lab["form"], "value": f"{f['name']}: {f['purpose']}"[:280]}
        for f in result["forms"]
    ]
    ctas = [
        {"label": f"{lab['explain']} {f.get('number') or lab['form']}", "selection": {"action": "explain_form", "url": f["url"]}}
        for f in result["forms"]
        if f.get("fields")
    ][:3]
    ctas.append({"label": lab["done"], "selection": {"action": "done"}, "primary": True})
    return {"title": lab["checklist"], "summary_rows": rows, "ctas": ctas}


def request_form_card(lab: dict, sites: list[str]) -> dict:
    return {
        "title": lab["more_info_title"],
        "fields": [
            {"name": "service", "kind": "text", "label": lab["field_service"], "required": True},
            {"name": "location", "kind": "text", "label": lab["field_location"], "required": False},
            {
                "name": "site", "kind": "select", "label": lab["field_site"], "required": False,
                "options": [{"value": s, "label": s} for s in sites] + [{"value": "unsure", "label": lab["not_sure"]}],
            },
            {
                "name": "language", "kind": "select", "label": lab["field_language"], "required": True,
                "options": [{"value": code, "label": name} for code, name in LANGUAGE_NAMES.items()],
            },
        ],
        "submit_cta": {"label": lab["find_steps"], "selection": {"action": "submit_request"}, "primary": True},
    }


# ---------------- main flow ----------------


async def ask_for_details(ctx: Context, user: str, language: str, lead: str | None = None) -> None:
    lab = await blocking(labels, language)
    sites = await blocking(known_sites)
    text = lead or lab["more_info"]
    if not lead:
        text += "\n\n" + ", ".join(sites)
    await reply_card(ctx, user, text, "form", request_form_card(lab, sites))


async def serve(ctx: Context, user: str, question: str, language: str, site: str) -> None:
    started = time.monotonic()
    lab = await blocking(labels, language)

    data = await check_data(ctx, user, site, language)
    note = ""
    if data.error and data.used_cache:
        note = f"_{lab['crawl_failed']} {day(data.crawled_at)}._\n\n"
    elif data.refreshing:
        note = f"_{lab['crawl_continues']} {day(data.crawled_at)}._\n\n"

    result = await get_answer(ctx, question, language, site)
    if result.get("not_found") or not result.get("steps"):
        await reply(ctx, user, note + await blocking(format_answer, result, language))
        ctx.logger.info(f"answered (not found) in {time.monotonic() - started:.1f}s")
        return

    await reply_card(ctx, user, note + await blocking(format_answer, result, language), "carousel", steps_card(result, site, lab))

    urls = [s["source_url"] for s in result["steps"]] + [f["url"] for f in result.get("forms") or []]
    checklist = await get_checklist(ctx, question, language, site, urls)
    memory = ctx.storage.get(user) or {}
    memory["checklist"] = checklist
    ctx.storage.set(user, memory)
    if checklist.get("empty"):
        await reply(ctx, user, lab["no_forms"])
    else:
        await reply_card(ctx, user, await blocking(format_checklist, checklist, language), "detail", checklist_card(checklist, lab))
    ctx.logger.info(f"answered with steps + checklist in {time.monotonic() - started:.1f}s")


async def handle_card_action(ctx: Context, user: str, sel: dict) -> bool:
    """Returns True if the message was a card interaction that has been handled."""
    memory = ctx.storage.get(user) or {}
    language = sel.get("language") or memory.get("language", "en")
    lab = await blocking(labels, language)
    action = sel.get("action")
    if action == "submit_request":
        service = (sel.get("service") or "").strip()
        if not service:
            await ask_for_details(ctx, user, language)
            return True
        text = f"{service} {sel.get('location') or ''}".strip()
        intent = await blocking(extract_intent, text)
        site = sel.get("site") if sel.get("site") not in (None, "", "unsure") else intent["site"]
        await route(ctx, user, intent, language_override=language, site_override=site)
        return True
    if action == "open_step" and sel.get("url"):
        await reply(ctx, user, f"[{lab['source']}]({sel['url']})")
        return True
    if action == "explain_form":
        form = next((f for f in (memory.get("checklist") or {}).get("forms", []) if f["url"] == sel.get("url")), None)
        if form:
            title = f"{form['number']}: {form['name']}" if form.get("number") else form["name"]
            lines = [f"**[{title}]({form['url']})**", form.get("purpose", ""), "", f"**{lab['form_fields']}**"]
            lines += [f"- *{x['label']}*: {x['explain']}" for x in form.get("fields") or []]
            await reply(ctx, user, "\n".join(lines))
        return True
    return action == "done"


async def route(ctx: Context, user: str, intent: dict, language_override: str | None = None,
                site_override: str | None = None) -> None:
    memory = ctx.storage.get(user) or {}
    language = language_override or intent["language"] or memory.get("language", "en")
    # Reuse the previous site only for follow-ups without a service of their own; a new request that no crawled
    # official website handles must not be answered from the last site.
    site = site_override or intent["site"] or (memory.get("site") if not intent["service"] else None)
    memory.update({"language": language})
    ctx.storage.set(user, memory)
    lab = await blocking(labels, language)

    if not intent["question"]:  # greeting or "what can you do": introduce + offer the form card
        await ask_for_details(ctx, user, language, lead=lab["greeting"])
        return
    if not site:
        if intent["service"]:  # a real request, but no crawled official website handles it
            sites = await blocking(known_sites)
            await ask_for_details(ctx, user, language, lead=f"{lab['not_covered']} {', '.join(sites)}")
        else:
            await ask_for_details(ctx, user, language)
        return
    memory.update({"site": site, "service": intent["service"]})
    ctx.storage.set(user, memory)
    await serve(ctx, user, intent["question"], language, site)


@agent.on_event("startup")
async def _warm(ctx: Context) -> None:
    asyncio.get_running_loop().create_task(blocking(warm_up))


@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ack(ctx, sender, msg)
    text = text_of(msg)
    if not text:
        return
    ctx.logger.info(f"chat from {sender[:16]}... ({len(text)} chars)")
    try:
        sel = card_selection(text)
        if sel and await handle_card_action(ctx, sender, sel):
            return
        intent = await blocking(extract_intent, text)
        await route(ctx, sender, intent)
    except Exception:
        ctx.logger.exception("navigator failed")
        await reply(ctx, sender, "Sorry, something went wrong while preparing your answer. Please try again.")


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    pass


agent.include(chat, publish_manifest=True)
agent.include(crawl_replies)

if __name__ == "__main__":
    agent.run()
