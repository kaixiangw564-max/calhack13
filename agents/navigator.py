"""PlainPath Navigator Agent: the ASI:One entry point.

1. Bitdeer extracts {language, service, location, site} from the user's message.
2. Delegates to the Answer Agent (typed AnswerRequest) and relays numbered, cited steps in the user's language.
3. If the Answer Agent fails or times out, it recovers by running the same core answer pipeline in-process.
Crawler and Form agents (data freshness, form checklists) and Interactive Cards are added in step 9.
"""
import asyncio
import json
import time

from answer import agent as answer_agent
from common import (
    AnswerRequest,
    AnswerResponse,
    ack,
    blocking,
    core_answer,
    format_answer,
    labels,
    make_agent,
    reply,
    text_of,
    warm_up,
)
from uagents import Context, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, chat_protocol_spec

from app.core.intent import extract_intent

ANSWER_TIMEOUT_S = 120

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


async def get_answer(ctx: Context, question: str, language: str, site: str | None) -> dict:
    """Ask the Answer Agent; on failure or timeout, recover with the in-process core pipeline."""
    response, status = await ctx.send_and_receive(
        answer_agent.address,
        AnswerRequest(question=question, language=language, site=site),
        response_type=AnswerResponse,
        timeout=ANSWER_TIMEOUT_S,
    )
    if isinstance(response, AnswerResponse) and response.ok:
        return json.loads(response.result_json)
    reason = response.error if isinstance(response, AnswerResponse) else status.detail
    ctx.logger.warning(f"Answer Agent unavailable ({reason}); answering in-process")
    return await blocking(core_answer.ask, question, language, site)


@agent.on_event("startup")
async def _warm(ctx: Context) -> None:
    asyncio.get_running_loop().create_task(blocking(warm_up))


@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    started = time.monotonic()
    await ack(ctx, sender, msg)
    text = text_of(msg)
    if not text:
        return
    ctx.logger.info(f"chat from {sender[:16]}... ({len(text)} chars)")
    try:
        intent = await blocking(extract_intent, text)
        memory = ctx.storage.get(sender) or {}
        site = intent["site"] or memory.get("site")
        language = intent["language"] or memory.get("language", "en")
        lab = await blocking(labels, language)
        if not intent["question"]:
            await reply(ctx, sender, lab["greeting"])
            return
        ctx.storage.set(sender, {"site": site, "language": language, "service": intent["service"]})
        # No separate "searching..." message: ASI:One's planner treats the first reply as the agent's answer.
        # Progress messages are reserved for long operations (live crawls, step 9).
        result = await get_answer(ctx, intent["question"], language, site)
        await reply(ctx, sender, await blocking(format_answer, result, language))
        ctx.logger.info(f"answered in {time.monotonic() - started:.1f}s (not_found={result.get('not_found')})")
    except Exception:
        ctx.logger.exception("navigator failed")
        await reply(ctx, sender, "Sorry, something went wrong while preparing your answer. Please try again.")


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    pass


agent.include(chat, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
