"""SQLAlchemy models: the single source of truth for the schema.

Timestamps are ``String`` columns holding ISO-8601 UTC text
(``YYYY-MM-DDTHH:MM:SS.ffffff+00:00``) because the rest of the app compares and
sorts them lexicographically, so the stored format is part of the contract.

Schema changes are applied with Alembic (see ``backend/migrations``); this module
only describes the current shape.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base shared by every model and by Alembic's autogenerate."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    gemini_api_key: Mapped[str] = mapped_column(
        String, nullable=False, default="", server_default=text("''")
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class Session(Base):
    """Opaque bearer tokens. Named ``Session`` in SQL, ``SessionModel`` in code."""

    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (Index("idx_sessions_user_id", "user_id"),)


class UsageDaily(Base):
    """Per-user, per-UTC-day message counter used for shared-key quotas."""

    __tablename__ = "usage_daily"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[str] = mapped_column(String, primary_key=True)
    messages: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    persona: Mapped[str] = mapped_column(String, nullable=False)
    tagline: Mapped[str] = mapped_column(
        String, nullable=False, default="", server_default=text("''")
    )
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    custom_prompt: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    accent: Mapped[str] = mapped_column(
        String, nullable=False, default="clay", server_default=text("'clay'")
    )
    temperature: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.85, server_default=text("0.85")
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (Index("idx_agents_user_id", "user_id"),)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(
        String, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="complete", server_default=text("'complete'")
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')", name="ck_messages_role"
        ),
        CheckConstraint(
            "status IN ('complete', 'partial', 'error')", name="ck_messages_status"
        ),
        Index("idx_messages_agent_id", "agent_id", "id"),
    )
