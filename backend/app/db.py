"""PostgreSQL persistence layer built on SQLAlchemy.

The public helpers here keep the exact signatures the API layer already calls,
and stay synchronous: the API wraps every call in ``asyncio.to_thread`` so a slow
database never blocks the event loop. SQLAlchemy's connection pool is thread
safe, so each call simply borrows a short lived ``Session`` and returns plain
dicts (never live ORM objects), which keeps callers decoupled from the ORM.

The schema is owned by Alembic. ``init_db`` upgrades the database to ``head`` on
startup, so a fresh database (or a new revision) is applied automatically without
anyone running a manual SQL step.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Sequence

from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from .config import BACKEND_DIR, settings
from .models import Agent, Message, UsageDaily, User
from .models import Session as SessionModel

# ``pool_pre_ping`` transparently recycles connections dropped by Postgres
# (restart, idle timeout) instead of failing the request that finds them stale.
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

# ``expire_on_commit=False`` keeps loaded values usable after commit, which lets
# the helpers below return plain dicts without an extra refresh round-trip.
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)

# Columns the API is allowed to patch, guarding against dynamic SQL injection.
AGENT_COLUMNS = frozenset(
    {"name", "persona", "tagline", "system_prompt", "custom_prompt",
     "accent", "temperature"}
)
USER_COLUMNS = frozenset({"username", "gemini_api_key", "password_hash"})


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a session, committing on success and rolling back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _to_dict(row: Any) -> dict[str, Any]:
    """Turn an ORM row into the plain dict the rest of the app expects."""
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def utcnow() -> str:
    """Current UTC time as a stable, sortable, JSON friendly string.

    Microsecond precision keeps activity ordering deterministic when several
    rows are written within the same second (e.g. two companions created, then
    a message sent, all back to back).
    """
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def today() -> str:
    """Current UTC day as ``YYYY-MM-DD``; the bucket used for daily quotas."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def new_id() -> str:
    return uuid.uuid4().hex


def init_db() -> None:
    """Bring the schema up to the latest Alembic revision (idempotent)."""
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(config, "head")


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #


def count_users() -> int:
    with session_scope() as session:
        return int(session.scalar(select(func.count()).select_from(User)) or 0)


def create_user(
    *,
    email: str,
    username: str,
    password_hash: str,
    gemini_api_key: str = "",
) -> dict[str, Any]:
    now = utcnow()
    user = User(
        id=new_id(),
        email=email.strip().lower(),
        username=username.strip(),
        password_hash=password_hash,
        gemini_api_key=(gemini_api_key or "").strip(),
        created_at=now,
        updated_at=now,
    )
    with session_scope() as session:
        session.add(user)
        session.flush()
        return _to_dict(user)


def get_user(user_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        user = session.get(User, user_id)
        return _to_dict(user) if user else None


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with session_scope() as session:
        user = session.scalar(
            select(User).where(User.email == email.strip().lower())
        )
        return _to_dict(user) if user else None


def update_user(user_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    fields = {k: v for k, v in changes.items() if k in USER_COLUMNS}
    if not fields:
        return get_user(user_id)
    fields["updated_at"] = utcnow()
    with session_scope() as session:
        user = session.get(User, user_id)
        if user is None:
            return None
        for key, value in fields.items():
            setattr(user, key, value)
        session.flush()
        return _to_dict(user)


def claim_unowned_agents(user_id: str) -> int:
    """Give companions created before accounts existed to ``user_id``.

    Called once, for the very first account, so pre-login data is not orphaned.
    """
    with session_scope() as session:
        result = session.execute(
            update(Agent).where(Agent.user_id.is_(None)).values(user_id=user_id)
        )
        return int(result.rowcount or 0)


# --------------------------------------------------------------------------- #
# Sessions (opaque bearer tokens)
# --------------------------------------------------------------------------- #


def create_session(
    *, token: str, user_id: str, created_at: str, expires_at: str
) -> None:
    with session_scope() as session:
        session.add(
            SessionModel(
                token=token,
                user_id=user_id,
                created_at=created_at,
                expires_at=expires_at,
            )
        )


def get_session(token: str) -> dict[str, Any] | None:
    """Return the session row when it exists and has not expired."""
    with session_scope() as session:
        row = session.get(SessionModel, token)
        if row is None:
            return None
        if row.expires_at <= utcnow():
            session.delete(row)
            return None
        return _to_dict(row)


def delete_session(token: str) -> bool:
    with session_scope() as session:
        result = session.execute(
            delete(SessionModel).where(SessionModel.token == token)
        )
        return bool(result.rowcount)


# --------------------------------------------------------------------------- #
# Daily usage (quota accounting for shared-key users)
# --------------------------------------------------------------------------- #


def daily_message_count(user_id: str, day: str | None = None) -> int:
    bucket = day or today()
    with session_scope() as session:
        value = session.scalar(
            select(UsageDaily.messages).where(
                UsageDaily.user_id == user_id, UsageDaily.day == bucket
            )
        )
    return int(value or 0)


def record_daily_message(user_id: str, day: str | None = None) -> int:
    """Increment today's user-message counter and return the new total."""
    bucket = day or today()
    with session_scope() as session:
        session.execute(
            pg_insert(UsageDaily)
            .values(user_id=user_id, day=bucket, messages=1)
            .on_conflict_do_update(
                index_elements=[UsageDaily.user_id, UsageDaily.day],
                set_={"messages": UsageDaily.messages + 1},
            )
        )
        value = session.scalar(
            select(UsageDaily.messages).where(
                UsageDaily.user_id == user_id, UsageDaily.day == bucket
            )
        )
    return int(value or 0)


# --------------------------------------------------------------------------- #
# Agents
# --------------------------------------------------------------------------- #


def list_agents(user_id: str) -> list[dict[str, Any]]:
    message_count = (
        select(func.count(Message.id))
        .where(Message.agent_id == Agent.id)
        .correlate(Agent)
        .scalar_subquery()
        .label("message_count")
    )
    last_message = (
        select(Message.content)
        .where(Message.agent_id == Agent.id)
        .order_by(Message.id.desc())
        .limit(1)
        .correlate(Agent)
        .scalar_subquery()
        .label("last_message")
    )
    last_message_at = (
        select(Message.created_at)
        .where(Message.agent_id == Agent.id)
        .order_by(Message.id.desc())
        .limit(1)
        .correlate(Agent)
        .scalar_subquery()
        .label("last_message_at")
    )
    statement = (
        select(Agent, message_count, last_message, last_message_at)
        .where(Agent.user_id == user_id)
        .order_by(
            func.coalesce(last_message_at, Agent.created_at).desc(),
            Agent.created_at.desc(),
        )
    )
    with session_scope() as session:
        rows = session.execute(statement).all()

    agents: list[dict[str, Any]] = []
    for agent, count, last, last_at in rows:
        shaped = _to_dict(agent)
        shaped.update(
            message_count=int(count or 0),
            last_message=last,
            last_message_at=last_at,
        )
        agents.append(shaped)
    return agents


def count_user_agents(user_id: str) -> int:
    with session_scope() as session:
        return int(
            session.scalar(
                select(func.count(Agent.id)).where(Agent.user_id == user_id)
            )
            or 0
        )


def get_agent(agent_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    with session_scope() as session:
        agent = session.get(Agent, agent_id)
        if agent is None:
            return None
        if user_id is not None and agent.user_id != user_id:
            return None
        agent_data = _to_dict(agent)
        message_count = int(
            session.scalar(
                select(func.count(Message.id)).where(Message.agent_id == agent_id)
            )
            or 0
        )
        latest = session.execute(
            select(Message.content, Message.created_at)
            .where(Message.agent_id == agent_id)
            .order_by(Message.id.desc())
            .limit(1)
        ).first()

    agent_data.update(
        message_count=message_count,
        last_message=latest[0] if latest else None,
        last_message_at=latest[1] if latest else None,
    )
    return agent_data


def create_agent(
    *,
    name: str,
    persona: str,
    tagline: str,
    system_prompt: str,
    custom_prompt: str = "",
    accent: str = "clay",
    temperature: float = 0.85,
    user_id: str | None = None,
) -> dict[str, Any]:
    agent_id = new_id()
    now = utcnow()
    with session_scope() as session:
        session.add(
            Agent(
                id=agent_id,
                user_id=user_id,
                name=name,
                persona=persona,
                tagline=tagline,
                system_prompt=system_prompt,
                custom_prompt=custom_prompt,
                accent=accent,
                temperature=float(temperature),
                created_at=now,
                updated_at=now,
            )
        )
    created = get_agent(agent_id)
    assert created is not None  # just inserted
    return created


def update_agent(agent_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    fields = {k: v for k, v in changes.items() if k in AGENT_COLUMNS}
    if not fields:
        return get_agent(agent_id)
    fields["updated_at"] = utcnow()
    with session_scope() as session:
        agent = session.get(Agent, agent_id)
        if agent is None:
            return None
        for key, value in fields.items():
            setattr(agent, key, value)
    return get_agent(agent_id)


def delete_agent(agent_id: str) -> bool:
    with session_scope() as session:
        result = session.execute(delete(Agent).where(Agent.id == agent_id))
        return bool(result.rowcount)


def taken_names(user_id: str) -> set[str]:
    with session_scope() as session:
        names = session.scalars(
            select(Agent.name).where(Agent.user_id == user_id)
        ).all()
    return {name.casefold() for name in names}


# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #


def add_message(
    agent_id: str,
    role: str,
    content: str,
    *,
    status: str = "complete",
) -> dict[str, Any]:
    message = Message(
        agent_id=agent_id,
        role=role,
        content=content,
        status=status,
        created_at=utcnow(),
    )
    with session_scope() as session:
        session.add(message)
        session.flush()
        return _to_dict(message)


def list_messages(
    agent_id: str,
    *,
    limit: int = 200,
    before_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return up to ``limit`` messages, oldest first.

    ``before_id`` pages backwards through history (used by "load older").
    """
    limit = max(1, min(limit, 500))
    statement = select(Message).where(Message.agent_id == agent_id)
    if before_id is not None:
        statement = statement.where(Message.id < before_id)
    statement = statement.order_by(Message.id.desc()).limit(limit)
    with session_scope() as session:
        rows = session.scalars(statement).all()
    return [_to_dict(row) for row in reversed(rows)]


def recent_history(agent_id: str, limit: int) -> list[tuple[str, str]]:
    """Last ``limit`` (role, content) pairs, oldest first, for model context."""
    limit = max(1, min(limit, 200))
    statement = (
        select(Message.role, Message.content)
        .where(Message.agent_id == agent_id, Message.role.in_(("user", "assistant")))
        .order_by(Message.id.desc())
        .limit(limit)
    )
    with session_scope() as session:
        rows = session.execute(statement).all()
    return [(role, content) for role, content in reversed(rows)]


def count_messages(agent_id: str) -> int:
    with session_scope() as session:
        return int(
            session.scalar(
                select(func.count(Message.id)).where(Message.agent_id == agent_id)
            )
            or 0
        )


def clear_messages(agent_id: str) -> int:
    with session_scope() as session:
        result = session.execute(
            delete(Message).where(Message.agent_id == agent_id)
        )
        return int(result.rowcount or 0)


def delete_message(agent_id: str, message_id: int) -> bool:
    with session_scope() as session:
        result = session.execute(
            delete(Message).where(
                Message.id == message_id, Message.agent_id == agent_id
            )
        )
        return bool(result.rowcount)


def bulk_insert(agent_id: str, rows: Sequence[tuple[str, str]]) -> None:
    """Test helper: insert several (role, content) pairs at once."""
    now = utcnow()
    with session_scope() as session:
        session.add_all(
            [
                Message(
                    agent_id=agent_id,
                    role=role,
                    content=content,
                    status="complete",
                    created_at=now,
                )
                for role, content in rows
            ]
        )


def agent_exists(agent_id: str) -> bool:
    with session_scope() as session:
        return session.get(Agent, agent_id) is not None


def iter_agents(user_id: str) -> Iterable[dict[str, Any]]:
    yield from list_agents(user_id)
