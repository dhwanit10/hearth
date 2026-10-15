"""End to end tests for the Hearth backend (REST + websocket streaming)."""

from __future__ import annotations

from conftest import collect_reply


# --------------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------------- #


def test_health_reports_demo_mode(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["llm"]["mode"] == "demo"
    assert body["llm"]["configured"] is False


def test_persona_catalogue(client):
    body = client.get("/api/personas").json()
    ids = [persona["id"] for persona in body["personas"]]
    assert {"best_friend", "girlfriend", "teacher", "mentor", "custom"} <= set(ids)
    assert "clay" in body["accents"] and "ember" in body["accents"]
    for persona in body["personas"]:
        assert persona["starters"], f"{persona['id']} has no conversation starters"
        assert persona["traits"]


# --------------------------------------------------------------------------- #
# Agent lifecycle
# --------------------------------------------------------------------------- #


def test_create_agent_with_random_name(client):
    agent = client.post("/api/agents", json={"persona": "girlfriend"}).json()["agent"]
    assert agent["name"]
    assert agent["persona"] == "girlfriend"
    assert agent["accent"] in {"clay", "amber", "rust", "ember", "gold",
                               "cocoa", "chestnut", "graphite"}
    assert agent["message_count"] == 0


def test_custom_persona_requires_a_brief(client):
    response = client.post("/api/agents", json={"persona": "custom", "name": "Nova"})
    assert response.status_code == 422

    response = client.post(
        "/api/agents",
        json={
            "persona": "custom",
            "name": "Nova",
            "custom_prompt": "A terse ship's navigator who speaks in sea metaphors.",
        },
    )
    assert response.status_code == 201


def test_unknown_persona_is_rejected(client):
    response = client.post("/api/agents", json={"persona": "dragon"})
    assert response.status_code == 422


def test_name_suggestions_skip_names_already_in_use(client, make_agent):
    first = client.get("/api/personas/best_friend/names?count=10").json()["names"]
    assert len(first) == len(set(first))

    make_agent(name=first[0])
    second = client.get("/api/personas/best_friend/names?count=10").json()["names"]
    assert first[0] not in second


def test_rename_rebuilds_the_system_prompt(client, make_agent):
    agent = make_agent(name="OldName")
    before = client.get(f"/api/agents/{agent['id']}").json()["agent"]["system_prompt"]
    assert "OldName" in before

    client.patch(f"/api/agents/{agent['id']}", json={"name": "NewName"})
    detail = client.get(f"/api/agents/{agent['id']}").json()["agent"]
    assert detail["name"] == "NewName"
    assert "NewName" in detail["system_prompt"]
    assert "OldName" not in detail["system_prompt"]


def test_delete_agent_is_not_found_afterwards(client, make_agent):
    agent = make_agent()
    assert client.delete(f"/api/agents/{agent['id']}").status_code == 204
    assert client.get(f"/api/agents/{agent['id']}").status_code == 404


def test_list_agents_is_ordered_by_recent_activity(client, make_agent):
    first = make_agent(name="First")
    second = make_agent(name="Second")

    with client.websocket_connect(f"/ws/chat/{first['id']}") as socket:
        socket.receive_json()  # ready
        socket.send_json({"type": "message", "content": "hello there"})
        collect_reply(socket)

    names = [a["name"] for a in client.get("/api/agents").json()["agents"]]
    assert names[0] == "First"
    assert second["name"] in names


# --------------------------------------------------------------------------- #
# Streaming over the websocket
# --------------------------------------------------------------------------- #


def test_websocket_streams_and_persists_a_reply(client, make_agent):
    agent = make_agent()

    with client.websocket_connect(f"/ws/chat/{agent['id']}") as socket:
        ready = socket.receive_json()
        assert ready["type"] == "ready"
        assert ready["agentId"] == agent["id"]
        assert "system_prompt" not in ready["agent"]

        socket.send_json({"type": "message", "content": "what is up my guy"})

        echo = socket.receive_json()
        assert echo["type"] == "user_message"
        assert echo["message"]["content"] == "what is up my guy"
        assert echo["message"]["role"] == "user"

        transcript = collect_reply(socket)

    assert transcript["error"] is None
    assert transcript["events"].count("assistant_start") == 1
    assert len(transcript["deltas"]) > 1, "reply should arrive in multiple chunks"
    assert transcript["message"] is not None
    assert transcript["message"]["role"] == "assistant"
    assert transcript["message"]["status"] == "complete"
    assert "".join(transcript["deltas"]).strip() == transcript["message"]["content"]

    history = client.get(f"/api/agents/{agent['id']}/messages").json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant"]
    assert history["total"] == 2

    agents = client.get("/api/agents").json()["agents"]
    assert agents[0]["message_count"] == 2
    assert agents[0]["last_message"]


def test_websocket_rejects_blank_and_unknown_agents(client, make_agent):
    agent = make_agent()
    with client.websocket_connect(f"/ws/chat/{agent['id']}") as socket:
        socket.receive_json()
        socket.send_json({"type": "message", "content": "    "})
        assert socket.receive_json()["code"] == "empty"

        socket.send_json({"type": "nonsense"})
        assert socket.receive_json()["code"] == "bad_frame"

        socket.send_json({"type": "ping"})
        assert socket.receive_json()["type"] == "pong"

    with client.websocket_connect("/ws/chat/does-not-exist") as socket:
        assert socket.receive_json()["code"] == "not_found"


def test_invalid_json_frame_is_reported(client, make_agent):
    agent = make_agent()
    with client.websocket_connect(f"/ws/chat/{agent['id']}") as socket:
        socket.receive_json()
        socket.send_text("{not json")
        assert socket.receive_json()["code"] == "bad_json"


def test_history_limit_is_respected_in_model_context(client, make_agent):
    """The model must only ever see the tail of a long conversation."""
    from app.config import settings

    agent = make_agent()
    pairs = [(("user" if i % 2 == 0 else "assistant"), f"message {i}") for i in range(40)]
    for role, content in pairs:
        from app import db

        db.add_message(agent["id"], role, content)

    with client.websocket_connect(f"/ws/chat/{agent['id']}") as socket:
        socket.receive_json()
        socket.send_json({"type": "message", "content": "last one"})
        collect_reply(socket)

    history = client.get(f"/api/agents/{agent['id']}/messages?limit=10").json()
    assert len(history["messages"]) == 10
    assert history["messages"][-1]["content"].startswith("message ") or history["messages"][-1]["role"] == "assistant"

    from app import db as db_module

    context = db_module.recent_history(agent["id"], settings.chat_history_limit)
    assert len(context) <= settings.chat_history_limit


# --------------------------------------------------------------------------- #
# Conversation management
# --------------------------------------------------------------------------- #


def test_clear_conversation_keeps_the_agent(client, make_agent):
    agent = make_agent()
    with client.websocket_connect(f"/ws/chat/{agent['id']}") as socket:
        socket.receive_json()
        socket.send_json({"type": "message", "content": "remember this"})
        collect_reply(socket)

    cleared = client.delete(f"/api/agents/{agent['id']}/messages").json()
    assert cleared["deleted"] == 2
    assert client.get(f"/api/agents/{agent['id']}/messages").json()["messages"] == []
    assert client.get(f"/api/agents/{agent['id']}").status_code == 200


def test_starters_match_the_persona(client, make_agent):
    agent = make_agent(persona="teacher", name="Ms. Verma")
    body = client.get(f"/api/agents/{agent['id']}/starters").json()
    assert body["starters"]


def test_conversation_is_isolated_per_agent(client, make_agent):
    first = make_agent(name="A")
    second = make_agent(name="B")

    with client.websocket_connect(f"/ws/chat/{first['id']}") as socket:
        socket.receive_json()
        socket.send_json({"type": "message", "content": "only for A"})
        collect_reply(socket)

    assert client.get(f"/api/agents/{second['id']}/messages").json()["total"] == 0
    assert client.get(f"/api/agents/{first['id']}/messages").json()["total"] == 2
