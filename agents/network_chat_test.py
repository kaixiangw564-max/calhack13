"""Network end-to-end check: a separate client agent sends a ChatMessage to the *running* Navigator through the
real Agentverse/Almanac path (the same inbound path ASI:One uses) and prints the reply.

Usage (from repo root, while agents/run_all.py is running):
    .venv/Scripts/python agents/network_chat_test.py "<question>"
"""
import os
import sys
import time

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec

NAVIGATOR = "agent1qd97m2my59lucx4aryd4x6tvwr9g3mxq8pdpgyj0rvesk0qdcxlvshpejz3"
QUESTION = sys.argv[1] if len(sys.argv) > 1 else "How do I renew my disabled parking placard?"
PORT = 8013

client = Agent(name="plainpath-net-test", seed="plainpath-network-test-client", port=PORT,
               endpoint=[f"http://127.0.0.1:{PORT}/submit"])
proto = Protocol(spec=chat_protocol_spec)
sent_at = 0.0


@client.on_event("startup")
async def send(ctx: Context) -> None:
    global sent_at
    sent_at = time.monotonic()
    status = await ctx.send(NAVIGATOR, ChatMessage(content=[TextContent(text=QUESTION)]))
    ctx.logger.info(f"sent to Navigator: {status.status} via {status.endpoint}")


@proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    ctx.logger.info(f"ACK from Navigator after {time.monotonic() - sent_at:.1f}s")


@proto.on_message(ChatMessage)
async def on_reply(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
    sys.stdout.buffer.write(f"\n=== reply after {time.monotonic() - sent_at:.1f}s ===\n{msg.text()[:600]}\n".encode("utf-8"))
    sys.stdout.flush()
    os._exit(0)


client.include(proto)

if __name__ == "__main__":
    client.run()
