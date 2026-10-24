"""Shared helpers for the PlainPath agents. All business logic lives in backend/app/core; this module only
wires it into uAgents (Agent Chat Protocol, Agentverse mailbox registration, inter-agent messages)."""
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from uagents import Agent, Context, Model  # noqa: E402
from uagents.mailbox import register_in_agentverse  # noqa: E402
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, MetadataContent, TextContent  # noqa: E402
from uagents_core.registration import AgentProfile, AgentverseConnectRequest, RegistrationRequest  # noqa: E402

from app.core import answer as core_answer  # noqa: E402,F401  (re-exported for agents)
from app.core.config import env  # noqa: E402

log = logging.getLogger("plainpath.agents")
README_DIR = Path(__file__).resolve().parent / "readme"


# ---- inter-agent messages (typed protocol next to the chat protocol) ----


class AnswerRequest(Model):
    question: str
    language: str = "en"
    site: str | None = None


class AnswerResponse(Model):
    ok: bool
    result_json: str = "{}"  # core.answer.ask() output
    error: str | None = None


class CrawlRequest(Model):
    request_id: str
    site: str


class CrawlProgress(Model):
    request_id: str
    pages_done: int
    status: str


class CrawlResult(Model):
    request_id: str
    ready: bool  # there is data to answer from
    crawled_at: str | None = None
    used_cache: bool = False  # answering from older data (refresh failed or still running)
    refreshing: bool = False  # a refresh continues in the background
    error: str | None = None


class FormRequest(Model):
    question: str
    language: str = "en"
    site: str | None = None
    source_urls: list[str] = []


class FormResponse(Model):
    ok: bool
    result_json: str = "{}"  # core.forms.checklist() output
    error: str | None = None


# ---- agent construction and Agentverse registration ----


def make_agent(name: str, seed_env: str, handle: str, description: str, readme: str, starter_prompts: list[str]) -> Agent:
    seed = env(seed_env, required=True)
    agent = Agent(
        name=name,
        seed=seed,
        mailbox=True,
        handle=handle,
        description=description,
        readme_path=str(README_DIR / readme),
        publish_agent_details=True,
        handle_messages_concurrently=True,
    )

    @agent.on_event("startup")
    async def _register(ctx: Context) -> None:
        await register_agent(agent, ctx, starter_prompts)

    return agent


WARM_LANGUAGES = ("en", "zh", "es", "vi", "ko", "tl", "ru", "ar")


def warm_up() -> None:
    """Open the Atlas connection and pre-translate chat labels so the first real request has no cold start."""
    import time

    from app.core import db
    from app.core.intent import known_sites

    t = time.time()
    db.client().admin.command("ping")
    known_sites()
    for lang in WARM_LANGUAGES:
        try:
            labels(lang)
        except Exception as exc:  # warm-up must never stop the agent
            log.warning("label warm-up failed for %s: %s", lang, exc)
    log.warning("warm-up done in %.1fs", time.time() - t)


async def register_agent(agent: Agent, ctx: Context, starter_prompts: list[str]) -> None:
    """Register this mailbox agent in Agentverse with AGENTVERSE_API_KEY (same flow as the inspector's Connect)."""
    if env("PLAINPATH_SKIP_AGENTVERSE") == "1":  # local tests
        return
    token = env("AGENTVERSE_API_KEY")
    if not token:
        ctx.logger.warning("AGENTVERSE_API_KEY not set; connect this agent manually from the Agent Inspector")
        return
    readme = agent._readme or ""  # loaded by uagents from readme_path
    details = RegistrationRequest(
        address=agent.address,
        name=agent.name,
        handle=agent._handle,
        agent_type="mailbox",
        profile=AgentProfile(description=agent._description or "", readme=readme, starter_prompts=starter_prompts),
        endpoints=agent._endpoints,
        protocols=list(agent.protocols.keys()),
        metadata=agent.metadata,
    )
    result = await register_in_agentverse(
        request=AgentverseConnectRequest(user_token=token, agent_type="mailbox"),
        identity=agent._identity,
        prefix=agent._prefix,
        agentverse=agent._agentverse,
        agent_details=details,
    )
    if result.success:
        ctx.logger.info(f"Registered in Agentverse as mailbox agent {agent.address}")
    else:
        ctx.logger.error(f"Agentverse registration failed: {result.detail}")


# ---- chat helpers ----


async def ack(ctx: Context, sender: str, msg: ChatMessage) -> None:
    await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))


async def reply(ctx: Context, sender: str, text: str, metadata: dict[str, str] | None = None) -> None:
    content = [TextContent(text=text)]
    if metadata:
        content.append(MetadataContent(metadata=metadata))
    await ctx.send(sender, ChatMessage(content=content))


def text_of(msg: ChatMessage) -> str:
    return msg.text().strip()


async def reply_card(ctx: Context, sender: str, text: str, kind: str, payload: dict, terminal: bool = False) -> None:
    """ASI Interactive Card (card_protocol_version 1). `text` is shown above the card and must stand on its own,
    because clients that don't render cards show only the text."""
    metadata = {
        "card_protocol_version": "1",
        "requires_card_interaction": "false" if terminal else "true",
        "card_kind": kind,
        "card_payload": json.dumps(payload, ensure_ascii=False),
    }
    if terminal:
        metadata["is_terminal"] = "true"
    await reply(ctx, sender, text, metadata)


def card_selection(text: str) -> dict | None:
    """Card clicks arrive as a JSON object (direct chat) or as prose (ASI:One planner). Returns the JSON or None."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("action") else None


async def blocking(fn, *args, **kwargs):
    """Run synchronous core code (pymongo, HTTP to Bitdeer/Apify) without blocking the agent event loop."""
    return await asyncio.to_thread(fn, *args, **kwargs)


# ---- answer formatting for chat (Markdown) ----

LABELS_EN = {
    "steps": "Steps",
    "source": "Official page",
    "checked": "checked",
    "documents": "What to bring",
    "forms": "Official forms",
    "contact": "Contact the agency",
    "searching": "Searching the official website",
    "greeting": (
        "Hi! I'm PlainPath. Tell me what you need to do with a government office, in any language, "
        "and I'll give you simple steps from the official website."
    ),
    "step": "Step",
    "your_steps": "Your steps",
    "bring": "Bring",
    "form": "Form",
    "checklist": "What to bring and which forms to use",
    "explain": "Explain",
    "done": "Done",
    "form_fields": "What to write on this form",
    "more_info": "Tell me a bit more so I can find the right official page.",
    "more_info_title": "What do you need?",
    "field_service": "What do you need to do? (for example: renew a disabled parking placard)",
    "field_location": "City or county (optional)",
    "field_site": "Government website",
    "field_language": "Answer language",
    "not_sure": "Not sure",
    "find_steps": "Find the steps",
    "not_covered": "I don't have an official website for this yet. I currently cover:",
    "crawl_started": "The official data is older than one day, so I'm refreshing it from the official website now.",
    "crawl_progress": "Refreshing the official website: pages read so far",
    "crawl_continues": "The refresh continues in the background. For now I'm answering from the saved official data from",
    "crawl_failed": "I couldn't refresh the official website right now. I'm answering from the saved official data from",
    "no_forms": "No forms or document list were found on the official pages for this.",
}


@lru_cache(maxsize=32)
def labels(language: str) -> dict[str, str]:
    return core_answer.localized(dict(LABELS_EN), language)


def day(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%d")
    except ValueError:
        return iso[:10]


def format_checklist(result: dict, language: str) -> str:
    """Markdown for the Form agent's checklist (documents + explained forms)."""
    lab = labels(language)
    if result.get("empty"):
        return lab["no_forms"]
    lines = [f"**{lab['checklist']}**"]
    if result["documents"]:
        lines.append("")
        lines += [f"- [ ] {d['text']} ([{lab['source']}]({d['source_url']}))" for d in result["documents"]]
    for f in result["forms"]:
        title = f"{f['number']}: {f['name']}" if f.get("number") else f["name"]
        lines += ["", f"**[{title}]({f['url']})**"]
        if f.get("purpose"):
            lines.append(f["purpose"])
        lines += [f"- *{x['label']}*: {x['explain']}" for x in f.get("fields") or []]
    lines += ["", f"_{result.get('disclaimer') or core_answer.DISCLAIMER_EN}_"]
    return "\n".join(lines)


def format_answer(result: dict, language: str) -> str:
    """Markdown for ASI:One: numbered steps, each with its official link and crawl date."""
    lab = labels(language)
    if result.get("not_found"):
        lines = [result.get("message") or core_answer.NOT_FOUND_EN]
        contact = result.get("contact")
        if contact:
            lines.append(f"\n{lab['contact']}: [{contact['title']}]({contact['url']})")
        lines.append(f"\n_{result.get('disclaimer') or core_answer.DISCLAIMER_EN}_")
        return "\n".join(lines)

    lines = [f"**{lab['steps']}**", ""]
    for i, step in enumerate(result["steps"], start=1):
        lines.append(f"{i}. {step['text']}  ")
        lines.append(f"   [{lab['source']}]({step['source_url']}) · {lab['checked']} {day(step['crawled_at'])}")
    if result.get("documents"):
        lines += ["", f"**{lab['documents']}**"]
        lines += [f"- {d['text']} ([{lab['source']}]({d['source_url']}))" for d in result["documents"]]
    if result.get("forms"):
        lines += ["", f"**{lab['forms']}**"]
        for f in result["forms"]:
            label = f"{f['number']}: {f['name']}" if f.get("number") else f["name"]
            lines.append(f"- [{label}]({f['url']})")
    lines += ["", f"_{result.get('disclaimer') or core_answer.DISCLAIMER_EN}_"]
    return "\n".join(lines)


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
