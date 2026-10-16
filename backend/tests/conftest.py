"""Shared pytest fixtures.

The environment is pinned *before* the app package is imported so the test run
never touches the developer's real database and always exercises the offline
demo engine (no network, no API key needed).
"""

from __future__ import annotations

import itertools
import os
import tempfile
import uuid
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="hearth-tests-"))

os.environ["DATABASE_PATH"] = str(_TMP / "test.db")
os.environ["GEMINI_API_KEY"] = ""
os.environ["CHAT_HISTORY_LIMIT"] = "12"
os.environ["SHARED_KEY_MAX_AGENTS"] = "3"
os.environ["SHARED_KEY_DAILY_MESSAGES"] = "10"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402

# Every account gets a unique email so signups never collide within a run.
_email_counter = itertools.count(1)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


class FakeGeminiClient:
    """Records the key it was constructed with, streams offline text.

    ``app.gemini.get_engine`` returns a real client whenever a key is present.
    Tests must never hit the network, so this stand-in keeps the BYOK selection
    path exercised (the user's key is passed through) while staying offline.
    """

    instances: list["FakeGeminiClient"] = []

    def __init__(self, api_key, model, **kwargs):
        self.api_key = api_key
        self.model = model
        self.kwargs = kwargs
        FakeGeminiClient.instances.append(self)

    async def stream_reply(self, *, system_prompt, history, temperature=0.9):
        for word in ("This ", "is ", "an ", "offline ", "reply."):
            yield word


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    """Keep every test offline and instant, even when a BYOK key is set."""
    from app import gemini

    gemini._demo_engine.chunk_delay = 0
    FakeGeminiClient.instances = []
    monkeypatch.setattr(gemini, "GeminiClient", FakeGeminiClient)
    return FakeGeminiClient


@pytest.fixture(autouse=True)
def clean_database():
    """Every test starts from an empty database."""
    db.init_db()
    with db.get_connection() as conn:
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM agents")
        conn.execute("DELETE FROM usage_daily")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM users")
        conn.commit()
    yield


@pytest.fixture
def account(client):
    """Factory: sign up a fresh account and return its token + auth headers."""

    def _signup(**overrides):
        payload = {
            "email": f"user{next(_email_counter)}-{uuid.uuid4().hex[:6]}@example.com",
            "username": "Tester",
            "password": "supersecret1",
        }
        payload.update(overrides)
        response = client.post("/api/auth/signup", json=payload)
        assert response.status_code == 201, response.text
        body = response.json()
        return {
            "token": body["token"],
            "user": body["user"],
            "headers": {"Authorization": f"Bearer {body['token']}"},
        }

    return _signup


@pytest.fixture
def user(account):
    """A signed-in account for tests that do not care about the signup itself."""
    return account()


@pytest.fixture
def auth(client, user):
    """The shared client, defaulting to the ``user`` fixture's bearer token."""
    previous = client.headers.get("Authorization")
    client.headers["Authorization"] = user["headers"]["Authorization"]
    yield client
    if previous is None:
        client.headers.pop("Authorization", None)
    else:
        client.headers["Authorization"] = previous


@pytest.fixture
def make_agent(auth):
    """Factory: create a companion and return its public payload."""

    def _make(**overrides):
        payload = {"persona": "best_friend", "name": "TestFriend"}
        payload.update(overrides)
        response = auth.post("/api/agents", json=payload)
        assert response.status_code == 201, response.text
        return response.json()["agent"]

    return _make


def ws_path(agent_id: str, user: dict) -> str:
    """Websocket path carrying the session token in the query string."""
    return f"/ws/chat/{agent_id}?token={user['token']}"


def collect_reply(socket, timeout_events: int = 4000) -> dict:
    """Read frames until the assistant finishes; return the full transcript."""
    transcript = {"deltas": [], "message": None, "events": [], "error": None}
    for _ in range(timeout_events):
        event = socket.receive_json()
        transcript["events"].append(event["type"])
        kind = event["type"]
        if kind == "delta":
            transcript["deltas"].append(event["content"])
        elif kind == "assistant_end":
            transcript["message"] = event.get("message")
            return transcript
        elif kind == "error":
            transcript["error"] = event.get("message")
    raise AssertionError(f"No assistant_end received. Events: {transcript['events']}")
