"""Pydantic request/response models for the REST API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .personas import ACCENTS, DEFAULT_PERSONA, PERSONAS

MAX_NAME = 40
MAX_CUSTOM_PROMPT = 4000


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
