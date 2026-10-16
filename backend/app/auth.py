"""Accounts, sessions and quota rules.

Three small responsibilities, kept out of the route layer:

* **Password hashing** - PBKDF2-HMAC-SHA256 with a per-user random salt, using
  only the standard library so there is no crypto dependency to pin. The hash
  is stored self-describing: ``pbkdf2_sha256$<iterations>$<salt-hex>$<hash-hex>``.
* **Sessions** - opaque bearer tokens (``secrets.token_urlsafe``) recorded in the
  ``sessions`` table with an expiry. The browser keeps the token; the server
  never trusts anything else.
* **Quota** - bring-your-own-key users are unlimited; everyone else rides on the
  platform key and is capped at ``SHARED_KEY_MAX_AGENTS`` companions and
  ``SHARED_KEY_DAILY_MESSAGES`` messages per UTC day.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, Header, HTTPException, status

from . import db
from .config import settings

PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 240_000

MIN_PASSWORD = 8
MAX_PASSWORD = 128
MAX_USERNAME = 40
MIN_USERNAME = 3

# Deliberately permissive: good enough to catch typos, not a validity oracle.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Error codes the frontend keys its "add your own key" prompts off.
QUOTA_AGENTS = "quota_agents"
QUOTA_MESSAGES = "quota_messages"


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return (
        f"{PBKDF2_ALGORITHM}${PBKDF2_ITERATIONS}"
        f"${salt.hex()}${digest.hex()}"
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != PBKDF2_ALGORITHM:
            return False
        expected = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(expected.hex(), digest_hex)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email or ""))


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def issue_session(user_id: str) -> str:
    """Create a session row and return the raw bearer token."""
    token = new_session_token()
    created = _now()
    expires = created + timedelta(days=max(1, settings.session_ttl_days))
    db.create_session(
        token=token,
        user_id=user_id,
        created_at=created.isoformat(timespec="seconds"),
        expires_at=expires.isoformat(timespec="seconds"),
    )
    return token


def user_for_token(token: str | None) -> dict[str, Any] | None:
    """Resolve a raw bearer token to a user row, or ``None``."""
    if not token:
        return None
    session = db.get_session(token)
    if session is None:
        return None
    return db.get_user(session["user_id"])


def _bearer(header: str | None) -> str | None:
    if not header:
        return None
    prefix, _, value = header.partition(" ")
    if prefix.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def token_from_header(header: str | None) -> str | None:
    """Public helper: pull the raw token out of an ``Authorization`` header."""
    return _bearer(header)


async def current_user(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """FastAPI dependency: the authenticated user, or a 401."""
    token = _bearer(authorization)
    user = await asyncio.to_thread(user_for_token, token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# --------------------------------------------------------------------------- #
# Quota
# --------------------------------------------------------------------------- #


def is_byok(user: dict[str, Any]) -> bool:
    """True when the user supplied their own Gemini key (unlimited plan)."""
    return bool((user.get("gemini_api_key") or "").strip())


def quota_snapshot(user: dict[str, Any]) -> dict[str, Any]:
    """Current usage vs. limits, shaped for the frontend."""
    unlimited = is_byok(user)
    used_today = db.daily_message_count(user["id"])
    return {
        "unlimited": unlimited,
        "agents_used": db.count_user_agents(user["id"]),
        "agents_limit": None if unlimited else settings.shared_key_max_agents,
        "messages_used_today": used_today,
        "messages_limit": None if unlimited else settings.shared_key_daily_messages,
    }


def agent_quota_error(user: dict[str, Any]) -> HTTPException:
    limit = settings.shared_key_max_agents
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": QUOTA_AGENTS,
            "message": (
                f"You have reached the {limit}-companion limit on the shared "
                "key. Add your own Gemini API key in Settings for unlimited "
                "companions."
            ),
        },
    )


def message_quota_error(user: dict[str, Any]) -> HTTPException:
    limit = settings.shared_key_daily_messages
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": QUOTA_MESSAGES,
            "message": (
                f"You have used all {limit} messages for today on the shared "
                "key. Add your own Gemini API key in Settings for unlimited "
                "messages, or come back tomorrow."
            ),
        },
    )
