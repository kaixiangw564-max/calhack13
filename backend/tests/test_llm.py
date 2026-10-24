"""Step 2 acceptance: real calls to Bitdeer AI Model Studio (needs BITDEER_* in .env)."""
from app.core import embeddings, llm


def test_chat_returns_reply():
    reply = llm.chat([{"role": "user", "content": "Reply with exactly the word: PONG"}], max_tokens=20)
    assert "PONG" in reply.upper()


def test_chat_json():
    data = llm.chat_json(
        [{"role": "user", "content": 'Return only this JSON: {"language": "en", "ok": true}'}], max_tokens=50
    )
    assert data["ok"] is True


def test_embeddings_multilingual():
    placard, permit, other = embeddings.embed(
        ["renew disabled parking placard", "renew disabled parking permit", "fishing license fees"]
    )
    assert len(placard) == len(permit) > 0

    def cos(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        return dot / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5))

    assert cos(placard, permit) > cos(placard, other)
