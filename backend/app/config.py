"""Environment driven configuration.

Every knob the backend exposes lives here so the rest of the code never has to
read ``os.environ`` directly. Values come from a ``.env`` file next to the
``backend`` folder (see ``.env.example``) plus the real environment, with the
real environment winning - that keeps container/CI overrides working.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Load .env without clobbering anything already set in the environment.
load_dotenv(BACKEND_DIR / ".env", override=False)


def _str(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _int(name: str, default: int) -> int:
    raw = _str(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = _str(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = _str(name)
    if not raw:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _database_url() -> str:
    """Read ``DATABASE_URL`` and pin it to the psycopg2 driver.

    SQLAlchemy understands a bare ``postgresql://...`` string, but which driver
    it picks depends on the installed version. Normalising it to
    ``postgresql+psycopg2://...`` keeps the app on the pinned dependency no
    matter how the URL is written.
    """
    raw = _str(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/hearth",
    )
    if raw.startswith("postgresql://"):
        return "postgresql+psycopg2://" + raw[len("postgresql://"):]
    return raw


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the runtime configuration."""

    gemini_api_key: str = field(default_factory=lambda: _str("GEMINI_API_KEY"))
    gemini_model: str = field(
        default_factory=lambda: _str("GEMINI_MODEL", "gemini-3.8-flash")
    )
    gemini_fallback_model: str = field(
        default_factory=lambda: _str("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
    )
    gemini_thinking_level: str = field(
        default_factory=lambda: _str("GEMINI_THINKING_LEVEL", "low").lower()
    )
    gemini_max_output_tokens: int = field(
        default_factory=lambda: _int("GEMINI_MAX_OUTPUT_TOKENS", 1024)
    )
    chat_history_limit: int = field(
        default_factory=lambda: _int("CHAT_HISTORY_LIMIT", 24)
    )
    # --- Accounts / BYOK quota --------------------------------------------- #
    # Users who bring their own Gemini key get unlimited companions and
    # messages. Everyone else rides on the platform key (``GEMINI_API_KEY``)
    # and is capped at these numbers.
    shared_key_max_agents: int = field(
        default_factory=lambda: _int("SHARED_KEY_MAX_AGENTS", 3)
    )
    shared_key_daily_messages: int = field(
        default_factory=lambda: _int("SHARED_KEY_DAILY_MESSAGES", 10)
    )
    session_ttl_days: int = field(
        default_factory=lambda: _int("SESSION_TTL_DAYS", 30)
    )
    database_url: str = field(
        default_factory=_database_url
    )
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: _csv(
            "CORS_ORIGINS",
            ("http://localhost:5173", "http://127.0.0.1:5173"),
        )
    )
    host: str = field(default_factory=lambda: _str("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("PORT", 8000))

    @property
    def llm_configured(self) -> bool:
        """True when a Gemini API key is present, i.e. real replies are on."""
        return bool(self.gemini_api_key)

    @property
    def llm_mode(self) -> str:
        return "gemini" if self.llm_configured else "demo"

    @property
    def database_name(self) -> str:
        """Database name only (no host/credentials), for the health endpoint."""
        return make_url(self.database_url).database or ""


settings = Settings()
