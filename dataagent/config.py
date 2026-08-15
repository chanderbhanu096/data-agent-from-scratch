"""Typed configuration, loaded once from the environment.

Everything the agent is allowed to do is bounded by a value in here. That is
deliberate: when you want to know what the agent *can't* do, this is the only
file you have to read.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
WAREHOUSE_PATH = DATA_DIR / "taxi.duckdb"


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    base_url: str | None

    # Safety rails. Chapter 07 is entirely about why each of these exists.
    max_steps: int
    max_usd: float
    sql_row_limit: int

    # How long to wait on one model call. Generous, because a local model that
    # doesn't fit in GPU memory runs on the CPU and gets very slow.
    timeout_s: float


def _model_for(provider: str) -> tuple[str, str | None]:
    """Return (model, base_url) for the chosen provider."""
    if provider == "ollama":
        return (
            os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
            os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_MODEL", "claude-opus-5"), None
    if provider == "openai":
        return os.getenv("OPENAI_MODEL", "gpt-4o-mini"), None
    if provider == "azure":
        # For Azure, "model" is the *deployment name* you chose in the portal,
        # and base_url is the resource endpoint. Name the deployment after the
        # model (e.g. gpt-4o-mini) so the cost tracker can price it.
        return (
            os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
            os.getenv("AZURE_OPENAI_ENDPOINT"),
        )
    raise ValueError(
        f"Unknown provider {provider!r}. Set DATAAGENT_PROVIDER to one of: "
        "ollama, anthropic, openai, azure"
    )


def load_settings() -> Settings:
    provider = os.getenv("DATAAGENT_PROVIDER", "ollama").strip().lower()
    model, base_url = _model_for(provider)
    return Settings(
        provider=provider,
        model=model,
        base_url=base_url,
        max_steps=int(os.getenv("DATAAGENT_MAX_STEPS", "12")),
        max_usd=float(os.getenv("DATAAGENT_MAX_USD", "0.50")),
        sql_row_limit=int(os.getenv("DATAAGENT_SQL_ROW_LIMIT", "1000")),
        timeout_s=float(os.getenv("DATAAGENT_TIMEOUT_S", "600")),
    )
