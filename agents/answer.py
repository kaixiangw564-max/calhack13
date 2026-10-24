"""PlainPath Answer Agent.

Given {question, language, site}, retrieves the top official chunks from MongoDB Atlas Vector Search and has
Bitdeer AI Model Studio write numbered plain-language steps, each with its official source URL and crawl time.
Speaks the Agent Chat Protocol (usable directly from ASI:One) and a typed AnswerRequest protocol for the Navigator.
"""
from common import (
    AnswerRequest,
    AnswerResponse,
    ack,
    blocking,
    core_answer,
    dumps,
    format_answer,
    make_agent,
    reply,
    text_of,
)
from uagents import Context, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, chat_protocol_spec

from app.core.intent import extract_intent

agent = make_agent(
    name="PlainPath Answer",
    seed_env="ANSWER_SEED",
    handle="plainpath-answer",
    description=(
        "Answers questions about government services using only crawled official website content. "
        "Returns simple numbered steps in your language, each with the official source link and crawl date."
    ),
    readme="answer.md",
    starter_prompts=[
        "How do I renew my disabled parking placard in California?",
        "What documents do I need for a REAL ID?",
    ],
)

chat = Protocol(spec=chat_protocol_spec)
answers = Protocol(name="PlainPathAnswer", version="0.1.0")


@answers.on_message(AnswerRequest, replies={AnswerResponse})
async def on_answer_request(ctx: Context, sender: str, req: AnswerRequest) -> None:
    try:
        result = await blocking(core_answer.ask, req.question, req.language, req.site)
        await ctx.send(sender, AnswerResponse(ok=True, result_json=dumps(result)))
    except Exception as exc:  # report the failure so the Navigator can recover
        ctx.logger.exception("answer failed")
        await ctx.send(sender, AnswerResponse(ok=False, error=f"{type(exc).__name__}: {exc}"[:500]))


@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ack(ctx, sender, msg)
    text = text_of(msg)
    if not text:
        return
    try:
        intent = await blocking(extract_intent, text)
        result = await blocking(core_answer.ask, intent["question"] or text, intent["language"], intent["site"])
        await reply(ctx, sender, await blocking(format_answer, result, intent["language"]))
    except Exception:
        ctx.logger.exception("chat answer failed")
        await reply(ctx, sender, "Sorry, I could not prepare an answer right now. Please try again in a moment.")


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    pass


agent.include(chat, publish_manifest=True)
agent.include(answers, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
