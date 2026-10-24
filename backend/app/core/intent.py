"""Intent extraction for the Navigator: what the user wants, where, and in which language (Bitdeer)."""
import logging
from functools import lru_cache

from . import db, llm

log = logging.getLogger("plainpath.intent")

INTENT_SYSTEM = """You route requests for PlainPath, which explains official government websites.

Known official websites (crawled): {sites}

From the user's message, return ONLY a JSON object:
{{"language": "<ISO 639-1 code of the language the user wants the answer in>",
  "service": "<the government service they need, in English, short; null if unclear>",
  "location": "<county/city/state they mention, or null>",
  "site": "<one domain from the known list that handles this service, or null if none fits or it is unclear>",
  "question": "<the user's request restated as one clear English question, or null if there is no request yet>"}}

Rules:
- If the user says which language they speak or want (e.g. "I only speak Chinese"), use that language even if the message is written in another language. Otherwise use the language the message is written in.
- If the message is only a greeting, small talk, or asks about you / PlainPath itself (what you do, who made you, how you work), set "question" to null.
- Keep the user's exact action in "service" and "question": renew is not apply, replace is not renew, change of address is not a new license. Examples: Chinese "\u7eed\u529e" and Spanish "renovar" mean renew.
- Choose a site only if the service is handled by that website (e.g. disabled parking placards, driver licenses, REAL ID and vehicle registration are handled by the California DMV, dmv.ca.gov). Never invent domains.
"""


@lru_cache(maxsize=1)
def _known_sites_cached() -> tuple[str, ...]:
    return tuple(sorted(d["site"] for d in db.db().sites.find({"status": "ready"}, {"site": 1})))


def known_sites() -> list[str]:
    return list(_known_sites_cached())


def extract_intent(message: str) -> dict:
    """{language, service, location, site, question}; site is always one of known_sites() or None."""
    sites = known_sites()
    data = llm.chat_json(
        [
            {"role": "system", "content": INTENT_SYSTEM.format(sites=", ".join(sites) or "(none)")},
            {"role": "user", "content": message},
        ],
        max_tokens=300,
        temperature=0,
    )
    site = data.get("site")
    intent = {
        "language": (data.get("language") or "en").strip().lower()[:8],
        "service": data.get("service") or None,
        "location": data.get("location") or None,
        "site": site if site in sites else None,
        "question": data.get("question") or None,
    }
    log.info("intent: %s", intent)
    return intent
