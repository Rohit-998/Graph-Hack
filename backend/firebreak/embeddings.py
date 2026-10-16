"""Local text embeddings for incident memory (PRD §11.2).

BAAI/bge-small-en-v1.5 via fastembed (ONNX, 384-d): no API quota, deterministic,
works offline once downloaded. If the model can't be loaded, a hashed
bag-of-words vector of the same size is used so recall still works.
"""

import hashlib
import math
import os
import re
from functools import lru_cache
from pathlib import Path

DIM = 384
MODEL_NAME = "BAAI/bge-small-en-v1.5"
CACHE = Path(os.getenv("FASTEMBED_CACHE_PATH", Path(__file__).resolve().parents[1] / ".cache" / "fastembed"))


@lru_cache(maxsize=1)
def _model():
    if os.getenv("FIREBREAK_EMBEDDINGS", "fastembed") == "hash":
        return None
    try:
        from fastembed import TextEmbedding

        return TextEmbedding(MODEL_NAME, cache_dir=str(CACHE))
    except Exception as exc:  # offline first run, missing wheel, ...
        print(f"[embeddings] falling back to hashed vectors: {exc!r}")
        return None


def _hashed(text: str) -> list[float]:
    v = [0.0] * DIM
    for tok in re.findall(r"[a-z0-9\-]+", text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        v[h % DIM] += 1.0 if (h >> 9) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def backend() -> str:
    return MODEL_NAME if _model() is not None else "hashed-bow"


def embed(texts: list[str]) -> list[list[float]]:
    m = _model()
    if m is None:
        return [_hashed(t) for t in texts]
    return [[float(x) for x in v] for v in m.embed(texts)]


def incident_text(title: str, summary: str, components: list[str]) -> str:
    """What an incident 'is' for similarity: symptoms, cause and where it happened."""
    return f"{title}. {summary} Components: {', '.join(sorted(components))}."
