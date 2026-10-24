"""Text embeddings via Bitdeer AI Model Studio (BAAI/bge-m3, multilingual, 1024-dim).

bge-m3 is multilingual, so a Chinese question matches English DMV pages directly.
"""
from .config import env
from .llm import client

BATCH = 32


def embedding_model() -> str:
    return env("EMBEDDING_MODEL", "BAAI/bge-m3")


def embed(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        resp = client().embeddings.create(model=embedding_model(), input=texts[i : i + BATCH])
        out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
    return out


def embed_one(text: str) -> list[float]:
    return embed([text])[0]
