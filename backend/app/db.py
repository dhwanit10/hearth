"""SQLite persistence layer.

Deliberately dependency free (stdlib ``sqlite3`` only) and synchronous. The API
layer wraps these calls in ``asyncio.to_thread`` so a slow disk never blocks the
event loop, and every call opens its own short lived connection which keeps the
module safe to use from FastAPI's threadpool.

The schema is created on startup and is intentionally additive: ``init_db`` runs
``CREATE TABLE IF NOT EXISTS`` statements so it can be called on every boot.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id             TEXT PRIMARY KEY,
    email          TEXT NOT NULL UNIQUE,
    username       TEXT NOT NULL,
    password_hash  TEXT NOT NULL,
    gemini_api_key TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id);

CREATE TABLE IF NOT EXISTS usage_daily (
    user_id  TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day      TEXT    NOT NULL,
    messages INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

CREATE TABLE IF NOT EXISTS agents (
    id            TEXT PRIMARY KEY,
    user_id       TEXT REFERENCES users(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL,
    persona       TEXT    NOT NULL,
    tagline       TEXT    NOT NULL DEFAULT '',
    system_prompt TEXT    NOT NULL,
    custom_prompt TEXT    NOT NULL DEFAULT '',
    accent        TEXT    NOT NULL DEFAULT 'clay',
    temperature   REAL    NOT NULL DEFAULT 0.85,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agents_user_id ON agents (user_id);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id   TEXT    NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    role       TEXT    NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content    TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'complete'
                       CHECK (status IN ('complete', 'partial', 'error')),
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_agent_id ON messages (agent_id, id);
"""

# Columns added after the first release; ``init_db`` patches old databases so
# ``CREATE TABLE IF NOT EXISTS`` alone never leaves a table half-upgraded.
MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("agents", "user_id", "ALTER TABLE agents ADD COLUMN user_id TEXT"),
)

# Columns the API is allowed to patch, guarding against dynamic SQL injection.
AGENT_COLUMNS = frozenset(
    {"name", "persona", "tagline", "system_prompt", "custom_prompt",
     "accent", "temperature"}
)


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


def get_connection() -> sqlite3.Connection:
    """Open a tuned connection. Caller owns it (use ``closing``)."""
    conn = sqlite3.connect(str(settings.database_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db() -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(get_connection()) as conn:
        conn.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            existing = {
                row["name"]
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if column not in existing:
                conn.execute(ddl)
        conn.commit()


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #

# Columns the API is allowed to patch directly.
USER_COLUMNS = frozenset({"username", "gemini_api_key", "password_hash"})


def count_users() -> int:
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()
    return int(row["total"]) if row else 0


def create_user(
    *,
    email: str,
    username: str,
    password_hash: str,
    gemini_api_key: str = "",
) -> dict[str, Any]:
    user_id = new_id()
    now = utcnow()
    with closing(get_connection()) as conn:
        conn.execute(
            """INSERT INTO users (id, email, username, password_hash,
                                  gemini_api_key, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, email.strip().lower(), username.strip(), password_hash,
             (gemini_api_key or "").strip(), now, now),
        )
        conn.commit()
    created = get_user(user_id)
    assert created is not None  # just inserted
    return created


def get_user(user_id: str) -> dict[str, Any] | None:
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    return dict(row) if row else None


def update_user(user_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    fields = {k: v for k, v in changes.items() if k in USER_COLUMNS}
    if not fields:
        return get_user(user_id)
    fields["updated_at"] = utcnow()
    assignments = ", ".join(f"{column} = ?" for column in fields)
    with closing(get_connection()) as conn:
        cur = conn.execute(
            f"UPDATE users SET {assignments} WHERE id = ?",
            (*fields.values(), user_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
    return get_user(user_id)


def claim_unowned_agents(user_id: str) -> int:
    """Give companions created before accounts existed to ``user_id``.

    Called once, for the very first account, so pre-login data is not orphaned.
    """
    with closing(get_connection()) as conn:
        cur = conn.execute(
            "UPDATE agents SET user_id = ? WHERE user_id IS NULL", (user_id,)
        )
        conn.commit()
        return cur.rowcount


# --------------------------------------------------------------------------- #
# Sessions (opaque bearer tokens)
# --------------------------------------------------------------------------- #


def create_session(
    *, token: str, user_id: str, created_at: str, expires_at: str
) -> None:
    with closing(get_connection()) as conn:
        conn.execute(
            """INSERT INTO sessions (token, user_id, created_at, expires_at)
               VALUES (?, ?, ?, ?)""",
            (token, user_id, created_at, expires_at),
        )
        conn.commit()


def get_session(token: str) -> dict[str, Any] | None:
    """Return the session row when it exists and has not expired."""
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE token = ?", (token,)
        ).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= utcnow():
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            return None
    return dict(row)


def delete_session(token: str) -> bool:
    with closing(get_connection()) as conn:
        cur = conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Daily usage (quota accounting for shared-key users)
# --------------------------------------------------------------------------- #


def daily_message_count(user_id: str, day: str | None = None) -> int:
    bucket = day or today()
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT messages FROM usage_daily WHERE user_id = ? AND day = ?",
            (user_id, bucket),
        ).fetchone()
    return int(row["messages"]) if row else 0


def record_daily_message(user_id: str, day: str | None = None) -> int:
    """Increment today's user-message counter and return the new total."""
    bucket = day or today()
    with closing(get_connection()) as conn:
        conn.execute(
            """INSERT INTO usage_daily (user_id, day, messages)
               VALUES (?, ?, 1)
               ON CONFLICT(user_id, day)
               DO UPDATE SET messages = messages + 1""",
            (user_id, bucket),
        )
        conn.commit()
        row = conn.execute(
            "SELECT messages FROM usage_daily WHERE user_id = ? AND day = ?",
            (user_id, bucket),
        ).fetchone()
    return int(row["messages"]) if row else 0


# --------------------------------------------------------------------------- #
# Agents
# --------------------------------------------------------------------------- #

_LIST_AGENTS_SQL = """
SELECT
    a.id, a.name, a.persona, a.tagline, a.system_prompt, a.custom_prompt,
    a.accent, a.temperature, a.created_at, a.updated_at,
    (SELECT COUNT(*) FROM messages m WHERE m.agent_id = a.id)      AS message_count,
    (SELECT m.content FROM messages m WHERE m.agent_id = a.id
     ORDER BY m.id DESC LIMIT 1)                                   AS last_message,
    (SELECT m.created_at FROM messages m WHERE m.agent_id = a.id
     ORDER BY m.id DESC LIMIT 1)                                   AS last_message_at
FROM agents a
WHERE a.user_id = ?
ORDER BY COALESCE(last_message_at, a.created_at) DESC, a.created_at DESC
"""


def _agent_row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def list_agents(user_id: str) -> list[dict[str, Any]]:
    with closing(get_connection()) as conn:
        rows = conn.execute(_LIST_AGENTS_SQL, (user_id,)).fetchall()
    return [_agent_row(row) for row in rows]


def count_user_agents(user_id: str) -> int:
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM agents WHERE user_id = ?", (user_id,)
        ).fetchone()
    return int(row["total"]) if row else 0


def get_agent(agent_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT * FROM agents WHERE id = ?", (agent_id,)
        ).fetchone()
        if row is None:
            return None
        agent = dict(row)
        if user_id is not None and agent.get("user_id") != user_id:
            return None
        stats = conn.execute(
            """SELECT COUNT(*) AS message_count,
                      (SELECT content FROM messages WHERE agent_id = ?
                       ORDER BY id DESC LIMIT 1) AS last_message,
                      (SELECT created_at FROM messages WHERE agent_id = ?
                       ORDER BY id DESC LIMIT 1) AS last_message_at
               FROM messages WHERE agent_id = ?""",
            (agent_id, agent_id, agent_id),
        ).fetchone()
    agent.update(dict(stats))
    return agent


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
    with closing(get_connection()) as conn:
        conn.execute(
            """INSERT INTO agents (id, user_id, name, persona, tagline,
                                   system_prompt, custom_prompt, accent,
                                   temperature, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (agent_id, user_id, name, persona, tagline, system_prompt,
             custom_prompt, accent, float(temperature), now, now),
        )
        conn.commit()
    created = get_agent(agent_id)
    assert created is not None  # just inserted
    return created


def update_agent(agent_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    fields = {k: v for k, v in changes.items() if k in AGENT_COLUMNS}
    if not fields:
        return get_agent(agent_id)
    fields["updated_at"] = utcnow()
    assignments = ", ".join(f"{column} = ?" for column in fields)
    values: list[Any] = list(fields.values())
    with closing(get_connection()) as conn:
        cur = conn.execute(
            f"UPDATE agents SET {assignments} WHERE id = ?", (*values, agent_id)
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
    return get_agent(agent_id)


def delete_agent(agent_id: str) -> bool:
    with closing(get_connection()) as conn:
        cur = conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        conn.commit()
        return cur.rowcount > 0


def taken_names(user_id: str) -> set[str]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT name FROM agents WHERE user_id = ?", (user_id,)
        ).fetchall()
    return {row["name"].casefold() for row in rows}


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
    now = utcnow()
    with closing(get_connection()) as conn:
        cur = conn.execute(
            """INSERT INTO messages (agent_id, role, content, status, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (agent_id, role, content, status, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    assert row is not None
    return dict(row)


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
    sql = "SELECT * FROM messages WHERE agent_id = ?"
    params: list[Any] = [agent_id]
    if before_id is not None:
        sql += " AND id < ?"
        params.append(before_id)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with closing(get_connection()) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in reversed(rows)]


def recent_history(agent_id: str, limit: int) -> list[tuple[str, str]]:
    """Last ``limit`` (role, content) pairs, oldest first, for model context."""
    limit = max(1, min(limit, 200))
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """SELECT role, content FROM messages
               WHERE agent_id = ? AND role IN ('user', 'assistant')
               ORDER BY id DESC LIMIT ?""",
            (agent_id, limit),
        ).fetchall()
    return [(row["role"], row["content"]) for row in reversed(rows)]


def count_messages(agent_id: str) -> int:
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM messages WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
    return int(row["total"]) if row else 0


def clear_messages(agent_id: str) -> int:
    with closing(get_connection()) as conn:
        cur = conn.execute("DELETE FROM messages WHERE agent_id = ?", (agent_id,))
        conn.commit()
        return cur.rowcount


def delete_message(agent_id: str, message_id: int) -> bool:
    with closing(get_connection()) as conn:
        cur = conn.execute(
            "DELETE FROM messages WHERE id = ? AND agent_id = ?",
            (message_id, agent_id),
        )
        conn.commit()
        return cur.rowcount > 0


def bulk_insert(agent_id: str, rows: Sequence[tuple[str, str]]) -> None:
    """Test helper: insert several (role, content) pairs at once."""
    now = utcnow()
    with closing(get_connection()) as conn:
        conn.executemany(
            """INSERT INTO messages (agent_id, role, content, status, created_at)
               VALUES (?, ?, ?, 'complete', ?)""",
            [(agent_id, role, content, now) for role, content in rows],
        )
        conn.commit()


def agent_exists(agent_id: str) -> bool:
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT 1 FROM agents WHERE id = ?", (agent_id,)
        ).fetchone()
    return row is not None


def iter_agents(user_id: str) -> Iterable[dict[str, Any]]:
    yield from list_agents(user_id)
