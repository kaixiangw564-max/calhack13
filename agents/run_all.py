"""Run all PlainPath agents in one process (one Bureau, one port). Each agent keeps its own Agentverse mailbox.

Usage (from repo root):  .venv/Scripts/python agents/run_all.py
"""
from answer import agent as answer_agent
from crawler import agent as crawler_agent
from form import agent as form_agent
from navigator import agent as navigator_agent
from uagents import Bureau

from common import env

bureau = Bureau(
    agents=[navigator_agent, crawler_agent, answer_agent, form_agent],
    port=int(env("AGENTS_PORT", "8001")),
)

if __name__ == "__main__":
    bureau.run()
