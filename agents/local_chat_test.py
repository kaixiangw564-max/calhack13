"""Local end-to-end chat test: a client agent talks to the Navigator over the Agent Chat Protocol inside one Bureau
(no Agentverse). Prints every ChatMessage the Navigator sends back and exits after the answer arrives.

Usage (from repo root):  PLAINPATH_SKIP_AGENTVERSE=1 .venv/Scripts/python agents/local_chat_test.py "<question>"
"""
import os
import sys

os.environ.setdefault("PLAINPATH_SKIP_AGENTVERSE", "1")

from answer import agent as answer_agent  # noqa: E402
from navigator import agent as navigator_agent  # noqa: E402
from uagents import Agent, Bureau, Context, Protocol  # noqa: E402
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec  # noqa: E402

QUESTION = sys.argv[1] if len(sys.argv) > 1 else "How do I renew my disabled parking placard?"
client = Agent(name="test-client", seed="plainpath-local-test-client")
proto = Protocol(spec=chat_protocol_spec)
received: list[str] = []


@client.on_event("startup")
async def send_question(ctx: Context) -> None:
    ctx.logger.info(f"sending: {QUESTION}")
    await ctx.send(navigator_agent.address, ChatMessage(content=[TextContent(text=QUESTION)]))


@proto.on_message(ChatMessage)
async def on_reply(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
    received.append(msg.text())
    sys.stdout.buffer.write(f"\n=== reply {len(received)} ===\n{msg.text()}\n".encode("utf-8"))
    sys.stdout.flush()
    if "](http" in msg.text() or len(received) >= 3:  # the final answer contains source links
        os._exit(0)


@proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    ctx.logger.info("navigator acknowledged")


client.include(proto)
bureau = Bureau(agents=[navigator_agent, answer_agent, client], port=8011)

if __name__ == "__main__":
    bureau.run()
