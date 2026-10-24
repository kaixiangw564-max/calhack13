"""PlainPath Form Agent: required documents and plain-language form explanations.

Given {question, language, site, source_urls}: looks up the custom Apify Actor's records (`services`, `forms`) for the
pages an answer cited plus related pages and forms, then Bitdeer explains each document and the key fields of each
official form in the user's language. Links always come from the crawl.
"""
from common import (
    FormRequest,
    FormResponse,
    ack,
    blocking,
    dumps,
    format_checklist,
    make_agent,
    reply,
    text_of,
)
from uagents import Context, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, chat_protocol_spec

from app.core import forms
from app.core.intent import extract_intent

agent = make_agent(
    name="PlainPath Form",
    seed_env="FORM_SEED",
    handle="plainpath-forms",
    description=(
        "Lists the documents to bring and explains official government forms (e.g. DMV REG 195) field by field, in "
        "plain words and in your language, using forms crawled from the official website."
    ),
    readme="form.md",
    starter_prompts=["Which forms do I need to renew a disabled parking placard?", "What do I write on form REG 195?"],
)

chat = Protocol(spec=chat_protocol_spec)
form_proto = Protocol(name="PlainPathForm", version="0.1.0")


@form_proto.on_message(FormRequest, replies={FormResponse})
async def on_form_request(ctx: Context, sender: str, req: FormRequest) -> None:
    try:
        result = await blocking(forms.checklist, req.source_urls, req.language, req.site, req.question)
        await ctx.send(sender, FormResponse(ok=True, result_json=dumps(result)))
    except Exception as exc:
        ctx.logger.exception("form checklist failed")
        await ctx.send(sender, FormResponse(ok=False, error=f"{type(exc).__name__}: {exc}"[:500]))


@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ack(ctx, sender, msg)
    text = text_of(msg)
    if not text:
        return
    try:
        intent = await blocking(extract_intent, text)
        question = intent["question"] or text
        result = await blocking(forms.checklist, [], intent["language"], intent["site"], question)
        await reply(ctx, sender, await blocking(format_checklist, result, intent["language"]))
    except Exception:
        ctx.logger.exception("form chat failed")
        await reply(ctx, sender, "Sorry, I could not look up the forms right now. Please try again.")


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    pass


agent.include(chat, publish_manifest=True)
agent.include(form_proto, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
