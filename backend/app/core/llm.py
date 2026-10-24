"""Single entry point for every LLM call — Bitdeer AI Model Studio.

Bitdeer's inference API is OpenAI-compatible (https://developers.bitdeer.ai/docs/api),
so we use the official `openai` client with Bitdeer's base_url. Swap models via .env only.
"""
import json
import re
from functools import lru_cache

from openai import OpenAI

from .config import env


@lru_cache(maxsize=1)
def client() -> OpenAI:
    return OpenAI(
        api_key=env("BITDEER_API_KEY", required=True),
        base_url=env("BITDEER_BASE_URL", "https://api-inference.bitdeer.ai/v1"),
        timeout=60,
        max_retries=2,  # openai client retries timeouts / 429 / 5xx with backoff
    )


def chat_model() -> str:
    return env("BITDEER_CHAT_MODEL", required=True)


def reasoning_effort() -> str:
    # DeepSeek-V4.x on Bitdeer is a reasoning model; "none" disables thinking (verified: 0 reasoning tokens),
    # which is right for grounded rewriting/translation and keeps max_tokens for the actual answer.
    return env("BITDEER_REASONING_EFFORT", "none")


def chat(
    messages: list[dict],
    *,
    temperature: float = 0.2,
    max_tokens: int = 1200,
    model: str | None = None,
    effort: str | None = None,
    json_mode: bool = False,
) -> str:
    """Plain chat completion; returns the assistant text."""
    extra = {"response_format": {"type": "json_object"}} if json_mode else {}
    resp = client().chat.completions.create(
        model=model or chat_model(),
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        reasoning_effort=effort or reasoning_effort(),
        **extra,
    )
    choice = resp.choices[0]
    if not choice.message.content and choice.finish_reason == "length":
        raise ValueError(f"LLM hit max_tokens={max_tokens} before producing an answer")
    return choice.message.content or ""


def chat_json(messages: list[dict], **kw) -> dict:
    """Chat completion that must return a JSON object.

    Uses JSON mode (response_format=json_object), which stops the model from emitting invalid JSON such as
    unescaped quotes inside non-English text; still tolerates ```json fences and surrounding prose.
    """
    text = chat(messages, json_mode=True, **kw)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"LLM did not return JSON: {text[:200]!r}")
    return json.loads(match.group(0))  # json.JSONDecodeError is a ValueError
