"""Shared pytest fixtures.

The environment is pinned *before* the app package is imported so the test run
never touches the developer's real database and always exercises the offline
demo engine (no network, no API key needed).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="hearth-tests-"))

os.environ["DATABASE_PATH"] = str(_TMP / "test.db")
os.environ["GEMINI_API_KEY"] = ""
os.environ["CHAT_HISTORY_LIMIT"] = "12"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_database():
    """Every test starts from an empty database."""
    db.init_db()
    with db.get_connection() as conn:
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM agents")
        conn.commit()
    yield


@pytest.fixture
def make_agent(client):
    """Factory: create a companion and return its public payload."""

    def _make(**overrides):
        payload = {"persona": "best_friend", "name": "TestFriend"}
        payload.update(overrides)
        response = client.post("/api/agents", json=payload)
        assert response.status_code == 201, response.text
        return response.json()["agent"]

    return _make


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
