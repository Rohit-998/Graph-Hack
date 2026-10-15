"""Runtime configuration, read from environment (and an optional .env file)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    falkordb_host: str = os.getenv("FALKORDB_HOST", "localhost")
    falkordb_port: int = int(os.getenv("FALKORDB_PORT", "6379"))
    tenant: str = os.getenv("TENANT", "nimbuspay")
    llm_provider: str = os.getenv("LLM_PROVIDER", "none")

    @property
    def graph_name(self) -> str:
        # One FalkorDB graph per tenant.
        return f"fb_{self.tenant}"


settings = Settings()
