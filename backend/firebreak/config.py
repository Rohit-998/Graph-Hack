"""Runtime configuration, read from environment (and an optional .env file)."""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Searches upward from this file, so the repo-root .env is found from backend/.
load_dotenv()


def _keys() -> tuple[str, ...]:
    raw = os.getenv("LLM_API_KEYS") or os.getenv("LLM_API_KEY") or ""
    return tuple(k.strip() for k in raw.split(",") if k.strip())


@dataclass(frozen=True)
class Settings:
    falkordb_host: str = os.getenv("FALKORDB_HOST", "localhost")
    falkordb_port: int = int(os.getenv("FALKORDB_PORT", "6379"))
    tenant: str = os.getenv("TENANT", "nimbuspay")

    llm_provider: str = os.getenv("LLM_PROVIDER", "none")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    llm_model: str = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")
    llm_api_keys: tuple[str, ...] = field(default_factory=_keys)
    llm_rpm: int = int(os.getenv("LLM_RPM", "12"))
    llm_timeout_s: float = float(os.getenv("LLM_TIMEOUT_S", "12"))

    @property
    def graph_name(self) -> str:
        # One FalkorDB graph per tenant.
        return f"fb_{self.tenant}"

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider != "none" and bool(self.llm_api_keys)


settings = Settings()
