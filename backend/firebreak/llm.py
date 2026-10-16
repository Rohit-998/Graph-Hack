"""Provider-agnostic LLM gateway (PRD §11).

- One OpenAI-compatible endpoint; Gemini by default.
- Several API keys, rotated on 429 / quota errors.
- Token-bucket rate limit, short timeout, prompt-hash disk cache.
- Never raises: on any failure it returns None and the caller uses its
  deterministic template. The graph answer is always correct without it.
"""

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .config import settings

CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "llm"


@dataclass
class Usage:
    calls: int = 0
    cached: int = 0
    failures: int = 0
    rate_limited: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    last_error: str | None = None
    last_latency_ms: float | None = None
    per_key_calls: dict[int, int] = field(default_factory=dict)


class Gateway:
    def __init__(self) -> None:
        self.usage = Usage()
        self._lock = threading.Lock()
        self._key_idx = 0
        self._cooldown: dict[int, float] = {}   # key index -> unix time it may be retried
        self._stamps: list[float] = []          # call times in the last minute

    # -- status ---------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return settings.llm_enabled

    @property
    def model(self) -> str:
        return settings.llm_model if self.enabled else "deterministic"

    def status(self) -> dict:
        u = self.usage
        return {
            "enabled": self.enabled, "provider": settings.llm_provider, "model": self.model,
            "keys": len(settings.llm_api_keys), "calls": u.calls, "cached": u.cached, "failures": u.failures,
            "rate_limited": u.rate_limited, "prompt_tokens": u.prompt_tokens,
            "completion_tokens": u.completion_tokens, "last_error": u.last_error,
            "last_latency_ms": u.last_latency_ms,
        }

    # -- internals -------------------------------------------------------------

    def _take_slot(self) -> bool:
        now = time.time()
        with self._lock:
            self._stamps = [t for t in self._stamps if now - t < 60]
            if len(self._stamps) >= settings.llm_rpm:
                return False
            self._stamps.append(now)
            return True

    def _pick_key(self) -> int | None:
        now = time.time()
        n = len(settings.llm_api_keys)
        with self._lock:
            for i in range(n):
                idx = (self._key_idx + i) % n
                if self._cooldown.get(idx, 0) <= now:
                    self._key_idx = idx
                    return idx
        return None

    def _bench(self, idx: int, seconds: float) -> None:
        with self._lock:
            self._cooldown[idx] = time.time() + seconds
            self._key_idx = (idx + 1) % len(settings.llm_api_keys)

    @staticmethod
    def _cache_path(payload: dict) -> Path:
        h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]
        return CACHE_DIR / f"{h}.json"

    # -- public ------------------------------------------------------------------

    def chat(self, system: str, user: str, *, max_tokens: int = 300, json_mode: bool = False,
             use_cache: bool = True) -> str | None:
        """Returns the completion text, or None if the LLM is off or failed."""
        if not self.enabled:
            return None
        payload = {
            "model": settings.llm_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        path = self._cache_path(payload)
        if use_cache and path.exists():
            self.usage.cached += 1
            return json.loads(path.read_text(encoding="utf-8"))["text"]

        for _attempt in range(len(settings.llm_api_keys)):
            if not self._take_slot():
                self.usage.rate_limited += 1
                self.usage.last_error = "local rate limit"
                return None
            idx = self._pick_key()
            if idx is None:
                self.usage.rate_limited += 1
                self.usage.last_error = "all keys cooling down"
                return None
            t0 = time.perf_counter()
            try:
                res = httpx.post(
                    settings.llm_base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {settings.llm_api_keys[idx]}"},
                    json=payload, timeout=settings.llm_timeout_s,
                )
            except httpx.HTTPError as exc:
                self.usage.failures += 1
                self.usage.last_error = type(exc).__name__
                return None
            self.usage.last_latency_ms = round((time.perf_counter() - t0) * 1000, 1)

            if res.status_code == 429:
                self.usage.rate_limited += 1
                self.usage.last_error = f"429 on key {idx + 1}"
                self._bench(idx, 60)
                continue
            if res.status_code >= 400:
                self.usage.failures += 1
                self.usage.last_error = f"HTTP {res.status_code}"
                if res.status_code in (401, 403):
                    self._bench(idx, 3600)
                    continue
                return None

            body = res.json()
            # Gemini's OpenAI endpoint sometimes wraps responses in a list.
            if isinstance(body, list):
                body = body[0]
            try:
                text = body["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError):
                self.usage.failures += 1
                self.usage.last_error = "malformed response"
                return None
            usage = body.get("usage") or {}
            self.usage.calls += 1
            self.usage.per_key_calls[idx] = self.usage.per_key_calls.get(idx, 0) + 1
            self.usage.prompt_tokens += usage.get("prompt_tokens", 0)
            self.usage.completion_tokens += usage.get("completion_tokens", 0)
            self.usage.last_error = None
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"text": text}), encoding="utf-8")
            return text.strip()
        return None

    def chat_json(self, system: str, user: str, **kw) -> dict | None:
        text = self.chat(system, user, json_mode=True, **kw)
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        try:
            out = json.loads(text)
        except json.JSONDecodeError:
            self.usage.failures += 1
            self.usage.last_error = "invalid JSON from model"
            return None
        return out if isinstance(out, dict) else None


gateway = Gateway()
