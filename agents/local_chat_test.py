"""Local end-to-end chat test: a client agent talks to the Navigator over the Agent Chat Protocol inside one Bureau
with all four agents (no Agentverse). Sends each message in turn, waits for the expected number of replies, and
prints every reply with the Interactive Card kind it carries.

Usage (from repo root):
    .venv/Scripts/python agents/local_chat_test.py "<message>" [<replies to wait for>] ["<message 2>" <n2> ...]
Card clicks can be sent as JSON, e.g. '{"action": "submit_request", "service": "...", "language": "zh"}'.
"""
import asyncio
import json
import os
import sys

os.environ.setdefault("PLAINPATH_SKIP_AGENTVERSE", "1")

from answer import agent as answer_agent  # noqa: E402
from crawler import agent as crawler_agent  # noqa: E402
from form import agent as form_agent  # noqa: E402
from navigator import agent as navigator_agent  # noqa: E402
from uagents import Agent, Bureau, Context, Protocol  # noqa: E402
from uagents_core.contrib.protocols.chat import (  # noqa: E402
    ChatAcknowledgement, ChatMessage, MetadataContent, TextContent, chat_protocol_spec,
)

def decode_arg(a: str) -> str:
    # Windows command lines mangle non-ASCII text; pass it as \uXXXX escapes instead.
    return a.encode("ascii", "backslashreplace").decode("unicode_escape") if "\\u" in a else a


args = [decode_arg(a) for a in sys.argv[1:]] or ["How do I renew my disabled parking placard?", "2"]
script = [(args[i], int(args[i + 1]) if i + 1 < len(args) else 1) for i in range(0, len(args), 2)]
client = Agent(name="test-client", seed="plainpath-local-test-client")
proto = Protocol(spec=chat_protocol_spec)
inbox: asyncio.Queue = asyncio.Queue()


def out(s: str) -> None:
    sys.stdout.buffer.write((s + "\n").encode("utf-8"))
    sys.stdout.flush()


@client.on_event("startup")
async def run_script(ctx: Context) -> None:
    async def driver() -> None:
        for text, expected in script:
            out(f"\n>>> {text}")
            await ctx.send(navigator_agent.address, ChatMessage(content=[TextContent(text=text)]))
            for n in range(expected):
                try:
                    msg: ChatMessage = await asyncio.wait_for(inbox.get(), timeout=240)
                except asyncio.TimeoutError:
                    out(f"!!! timeout waiting for reply {n + 1}/{expected}")
                    os._exit(1)
                cards = [c.metadata for c in msg.content if isinstance(c, MetadataContent)]
                kind = cards[0].get("card_kind") if cards else "none"
                out(f"\n=== reply {n + 1}/{expected} [card: {kind}] ===\n{msg.text()[:1500]}")
                if cards:
                    payload = json.loads(cards[0]["card_payload"])
                    out(f"--- card payload keys: {sorted(payload)} | {json.dumps(payload, ensure_ascii=False)[:600]}")
        os._exit(0)

    asyncio.get_running_loop().create_task(driver())


@proto.on_message(ChatMessage)
async def on_reply(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
    await inbox.put(msg)


@proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    pass


client.include(proto)
bureau = Bureau(agents=[navigator_agent, crawler_agent, answer_agent, form_agent, client], port=8011)

if __name__ == "__main__":
    bureau.run()
