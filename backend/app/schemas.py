"""Pydantic request/response models for the REST API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .auth import (
    MAX_PASSWORD,
    MAX_USERNAME,
    MIN_PASSWORD,
    MIN_USERNAME,
    normalize_email,
    valid_email,
)
from .personas import ACCENTS, DEFAULT_PERSONA, PERSONAS

MAX_NAME = 40
MAX_CUSTOM_PROMPT = 4000
MAX_API_KEY = 200


class AgentCreate(BaseModel):
    """Body for POST /api/agents. Only ``persona`` is required."""

    persona: str = Field(default=DEFAULT_PERSONA)
    name: str | None = Field(default=None, max_length=MAX_NAME)
    tagline: str | None = Field(default=None, max_length=120)
    custom_prompt: str = Field(default="", max_length=MAX_CUSTOM_PROMPT)
    accent: str | None = None

    @field_validator("persona")
    @classmethod
    def _known_persona(cls, value: str) -> str:
        value = (value or "").strip() or DEFAULT_PERSONA
        if value not in PERSONAS:
            raise ValueError(
                f"Unknown persona '{value}'. "
                f"Choose one of: {', '.join(PERSONAS)}"
            )
        return value

    @field_validator("name", "tagline")
    @classmethod
    def _clean_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned[:MAX_NAME] if cleaned else None

    @field_validator("custom_prompt")
    @classmethod
    def _clean_prompt(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("accent")
    @classmethod
    def _known_accent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        return value if value in ACCENTS else None


class AgentUpdate(BaseModel):
    """Body for PATCH /api/agents/{id}. Every field is optional."""

    name: str | None = Field(default=None, max_length=MAX_NAME)
    tagline: str | None = Field(default=None, max_length=120)
    custom_prompt: str | None = Field(default=None, max_length=MAX_CUSTOM_PROMPT)
    accent: str | None = None

    @field_validator("name", "tagline")
    @classmethod
    def _clean_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned[:MAX_NAME] if cleaned else None

    @field_validator("accent")
    @classmethod
    def _known_accent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        return value if value in ACCENTS else None


class MessageIn(BaseModel):
    """A chat message arriving over the websocket."""

    type: Literal["message"] = "message"
    content: str = Field(min_length=1, max_length=8000)

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Message content cannot be blank.")
        return cleaned


class Agent(BaseModel):
    id: str
    name: str
    persona: str
    tagline: str = ""
    accent: str = "clay"
    temperature: float = 0.85
    custom_prompt: str = ""
    created_at: str
    updated_at: str
    message_count: int = 0
    last_message: str | None = None
    last_message_at: str | None = None


class Message(BaseModel):
    id: int
    agent_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    status: Literal["complete", "partial", "error"] = "complete"
    created_at: str


class PersonaOut(BaseModel):
    id: str
    label: str
    tagline: str
    description: str
    traits: list[str]
    starters: list[str]
    names: list[str]
    custom: bool = False


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"
    app: str
    version: str
    database: str
    llm: dict[str, Any]


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #


class SignupIn(BaseModel):
    """Body for POST /api/auth/signup."""

    email: str
    username: str = Field(min_length=MIN_USERNAME, max_length=MAX_USERNAME)
    password: str = Field(min_length=MIN_PASSWORD, max_length=MAX_PASSWORD)

    @field_validator("email")
    @classmethod
    def _clean_email(cls, value: str) -> str:
        cleaned = normalize_email(value)
        if not valid_email(cleaned):
            raise ValueError("Enter a valid email address.")
        return cleaned

    @field_validator("username")
    @classmethod
    def _clean_username(cls, value: str) -> str:
        cleaned = " ".join((value or "").split())
        if len(cleaned) < MIN_USERNAME:
            raise ValueError(f"Username must be at least {MIN_USERNAME} characters.")
        return cleaned[:MAX_USERNAME]

    @field_validator("password")
    @classmethod
    def _clean_password(cls, value: str) -> str:
        if len(value or "") < MIN_PASSWORD:
            raise ValueError(f"Password must be at least {MIN_PASSWORD} characters.")
        return value


class LoginIn(BaseModel):
    """Body for POST /api/auth/login."""

    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _clean_email(cls, value: str) -> str:
        return normalize_email(value)


class UserUpdate(BaseModel):
    """Body for PATCH /api/auth/me. Every field is optional.

    ``gemini_api_key`` may be set to an empty string to fall back to the shared
    key (and its limits). Changing the password requires ``current_password``.
    """

    username: str | None = Field(default=None, max_length=MAX_USERNAME)
    gemini_api_key: str | None = Field(default=None, max_length=MAX_API_KEY)
    current_password: str | None = None
    new_password: str | None = Field(default=None, max_length=MAX_PASSWORD)

    @field_validator("username")
    @classmethod
    def _clean_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        if len(cleaned) < MIN_USERNAME:
            raise ValueError(f"Username must be at least {MIN_USERNAME} characters.")
        return cleaned[:MAX_USERNAME]

    @field_validator("gemini_api_key")
    @classmethod
    def _clean_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("new_password")
    @classmethod
    def _clean_new_password(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) < MIN_PASSWORD:
            raise ValueError(f"Password must be at least {MIN_PASSWORD} characters.")
        return value


class QuotaOut(BaseModel):
    """Usage vs. limits. ``None`` limits mean unlimited (BYOK)."""

    unlimited: bool
    agents_used: int
    agents_limit: int | None = None
    messages_used_today: int
    messages_limit: int | None = None


class UserOut(BaseModel):
    id: str
    email: str
    username: str
    has_gemini_key: bool = False
    created_at: str
    updated_at: str
    quota: QuotaOut


class AuthOut(BaseModel):
    token: str
    user: UserOut


class MeOut(BaseModel):
    """Response for /auth/me routes - the user, without minting a new token."""

    user: UserOut
