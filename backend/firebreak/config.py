"""Runtime configuration, read from environment (and an optional .env file)."""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# FIREBREAK_ENV_FILE picks an alternate env file (e.g. .env.cloud for FalkorDB Cloud); it is
# loaded first so its values win. Then the default .env (searched upward from backend/) fills gaps.
# Variables already set in the process environment always take precedence over both.
_alt = os.getenv("FIREBREAK_ENV_FILE")
if _alt:
    load_dotenv(_alt)
load_dotenv()


def _keys() -> tuple[str, ...]:
    raw = os.getenv("LLM_API_KEYS") or os.getenv("LLM_API_KEY") or ""
    return tuple(k.strip() for k in raw.split(",") if k.strip())


@dataclass(frozen=True)
class Settings:
    falkordb_host: str = os.getenv("FALKORDB_HOST", "localhost")
    falkordb_port: int = int(os.getenv("FALKORDB_PORT", "6379"))
    falkordb_username: str | None = os.getenv("FALKORDB_USERNAME") or None
    falkordb_password: str | None = os.getenv("FALKORDB_PASSWORD") or None
    falkordb_tls: bool = os.getenv("FALKORDB_TLS", "false").lower() in ("1", "true", "yes")
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
