"""End to end tests for the Hearth backend (accounts, quota, REST + websocket)."""

from __future__ import annotations

from conftest import collect_reply, ws_path


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
# Accounts
# --------------------------------------------------------------------------- #


def test_signup_returns_token_and_user(client):
    response = client.post(
        "/api/auth/signup",
        json={"email": "New@Example.com", "username": "Nova", "password": "supersecret1"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["token"]
    assert body["user"]["email"] == "new@example.com"  # normalised
    assert body["user"]["username"] == "Nova"
    assert body["user"]["has_gemini_key"] is False
    assert body["user"]["quota"]["unlimited"] is False
    assert body["user"]["quota"]["agents_limit"] == 3
    assert body["user"]["quota"]["messages_limit"] == 10


def test_signup_rejects_duplicate_email_and_weak_input(client):
    payload = {"email": "dupe@example.com", "username": "Dupe", "password": "supersecret1"}
    assert client.post("/api/auth/signup", json=payload).status_code == 201
    assert client.post("/api/auth/signup", json=payload).status_code == 409
    assert client.post(
        "/api/auth/signup",
        json={"email": "bad", "username": "X", "password": "short"},
    ).status_code == 422


def test_login_and_me_and_logout(client, user):
    assert client.get("/api/auth/me").status_code == 401

    me = client.get("/api/auth/me", headers=user["headers"])
    assert me.status_code == 200
    assert me.json()["user"]["email"] == user["user"]["email"]

    login = client.post(
        "/api/auth/login",
        json={"email": user["user"]["email"], "password": "supersecret1"},
    )
    assert login.status_code == 200
    fresh_token = login.json()["token"]

    wrong = client.post(
        "/api/auth/login",
        json={"email": user["user"]["email"], "password": "not-the-password"},
    )
    assert wrong.status_code == 401

    assert client.post("/api/auth/logout", headers=user["headers"]).status_code == 204
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {fresh_token}"}
    ).status_code == 200


def test_update_me_sets_key_and_changes_password(client, user):
    response = client.patch(
        "/api/auth/me",
        headers=user["headers"],
        json={"username": "Renamed", "gemini_api_key": "AIza-personal-key"},
    )
    assert response.status_code == 200
    body = response.json()["user"]
    assert body["username"] == "Renamed"
    assert body["has_gemini_key"] is True
    assert body["quota"]["unlimited"] is True
    assert "AIza-personal-key" not in response.text  # key is never echoed back

    bad = client.patch(
        "/api/auth/me",
        headers=user["headers"],
        json={"current_password": "wrong", "new_password": "brandnewpass"},
    )
    assert bad.status_code == 400

    good = client.patch(
        "/api/auth/me",
        headers=user["headers"],
        json={"current_password": "supersecret1", "new_password": "brandnewpass"},
    )
    assert good.status_code == 200
    assert client.post(
        "/api/auth/login",
        json={"email": user["user"]["email"], "password": "brandnewpass"},
    ).status_code == 200


def test_first_signup_claims_legacy_companions(client):
    from app import db

    legacy = db.create_agent(
        name="Old Buddy",
        persona="best_friend",
        tagline="pre-account",
        system_prompt="hi",
    )
    assert legacy["user_id"] is None

    token = client.post(
        "/api/auth/signup",
        json={"email": "owner@example.com", "username": "Owner", "password": "supersecret1"},
    ).json()["token"]
    agents = client.get(
        "/api/agents", headers={"Authorization": f"Bearer {token}"}
    ).json()["agents"]
    assert [a["name"] for a in agents] == ["Old Buddy"]


# --------------------------------------------------------------------------- #
# Authorisation boundaries
# --------------------------------------------------------------------------- #


def test_agents_require_a_token(client):
    assert client.get("/api/agents").status_code == 401
    assert client.post("/api/agents", json={"persona": "girlfriend"}).status_code == 401


def test_companions_are_private_to_their_owner(client, account, make_agent, auth, user):
    agent = make_agent(name="Mine")

    other = account(username="Other")
    response = client.get("/api/agents", headers=other["headers"])
    assert response.json()["agents"] == []
    assert client.get(
        f"/api/agents/{agent['id']}", headers=other["headers"]
    ).status_code == 404
    assert client.delete(
        f"/api/agents/{agent['id']}", headers=other["headers"]
    ).status_code == 404


# --------------------------------------------------------------------------- #
# Agent lifecycle
# --------------------------------------------------------------------------- #


def test_create_agent_with_random_name(auth):
    agent = auth.post("/api/agents", json={"persona": "girlfriend"}).json()["agent"]
    assert agent["name"]
    assert agent["persona"] == "girlfriend"
    assert agent["accent"] in {"clay", "amber", "rust", "ember", "gold",
                               "cocoa", "chestnut", "graphite"}
    assert agent["message_count"] == 0


def test_custom_persona_requires_a_brief(auth):
    response = auth.post("/api/agents", json={"persona": "custom", "name": "Nova"})
    assert response.status_code == 422

    response = auth.post(
        "/api/agents",
        json={
            "persona": "custom",
            "name": "Nova",
            "custom_prompt": "A terse ship's navigator who speaks in sea metaphors.",
        },
    )
    assert response.status_code == 201


def test_unknown_persona_is_rejected(auth):
    response = auth.post("/api/agents", json={"persona": "dragon"})
    assert response.status_code == 422


def test_name_suggestions_skip_names_already_in_use(auth, make_agent):
    first = auth.get("/api/personas/best_friend/names?count=10").json()["names"]
    assert len(first) == len(set(first))

    make_agent(name=first[0])
    second = auth.get("/api/personas/best_friend/names?count=10").json()["names"]
    assert first[0] not in second


def test_rename_rebuilds_the_system_prompt(auth, make_agent):
    agent = make_agent(name="OldName")
    before = auth.get(f"/api/agents/{agent['id']}").json()["agent"]["system_prompt"]
    assert "OldName" in before

    auth.patch(f"/api/agents/{agent['id']}", json={"name": "NewName"})
    detail = auth.get(f"/api/agents/{agent['id']}").json()["agent"]
    assert detail["name"] == "NewName"
    assert "NewName" in detail["system_prompt"]
    assert "OldName" not in detail["system_prompt"]


def test_delete_agent_is_not_found_afterwards(auth, make_agent):
    agent = make_agent()
    assert auth.delete(f"/api/agents/{agent['id']}").status_code == 204
    assert auth.get(f"/api/agents/{agent['id']}").status_code == 404


def test_list_agents_is_ordered_by_recent_activity(auth, user, make_agent):
    first = make_agent(name="First")
    second = make_agent(name="Second")

    with auth.websocket_connect(ws_path(first["id"], user)) as socket:
        socket.receive_json()  # ready
        socket.send_json({"type": "message", "content": "hello there"})
        collect_reply(socket)

    names = [a["name"] for a in auth.get("/api/agents").json()["agents"]]
    assert names[0] == "First"
    assert second["name"] in names


# --------------------------------------------------------------------------- #
# Streaming over the websocket
# --------------------------------------------------------------------------- #


def test_websocket_streams_and_persists_a_reply(auth, user, make_agent):
    agent = make_agent()

    with auth.websocket_connect(ws_path(agent["id"], user)) as socket:
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

    history = auth.get(f"/api/agents/{agent['id']}/messages").json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant"]
    assert history["total"] == 2

    agents = auth.get("/api/agents").json()["agents"]
    assert agents[0]["message_count"] == 2
    assert agents[0]["last_message"]


def test_websocket_requires_a_token(client, make_agent):
    agent = make_agent()
    with client.websocket_connect(f"/ws/chat/{agent['id']}") as socket:
        assert socket.receive_json()["code"] == "unauthorized"
    with client.websocket_connect(
        f"/ws/chat/{agent['id']}?token=not-a-real-token"
    ) as socket:
        assert socket.receive_json()["code"] == "unauthorized"


def test_websocket_rejects_blank_and_unknown_agents(auth, user, make_agent):
    agent = make_agent()
    with auth.websocket_connect(ws_path(agent["id"], user)) as socket:
        socket.receive_json()
        socket.send_json({"type": "message", "content": "    "})
        assert socket.receive_json()["code"] == "empty"

        socket.send_json({"type": "nonsense"})
        assert socket.receive_json()["code"] == "bad_frame"

        socket.send_json({"type": "ping"})
        assert socket.receive_json()["type"] == "pong"

    with auth.websocket_connect(f"/ws/chat/does-not-exist?token={user['token']}") as socket:
        assert socket.receive_json()["code"] == "not_found"


def test_invalid_json_frame_is_reported(auth, user, make_agent):
    agent = make_agent()
    with auth.websocket_connect(ws_path(agent["id"], user)) as socket:
        socket.receive_json()
        socket.send_text("{not json")
        assert socket.receive_json()["code"] == "bad_json"


def test_history_limit_is_respected_in_model_context(auth, user, make_agent):
    """The model must only ever see the tail of a long conversation."""
    from app.config import settings

    agent = make_agent()
    pairs = [(("user" if i % 2 == 0 else "assistant"), f"message {i}") for i in range(40)]
    from app import db

    for role, content in pairs:
        db.add_message(agent["id"], role, content)

    with auth.websocket_connect(ws_path(agent["id"], user)) as socket:
        socket.receive_json()
        socket.send_json({"type": "message", "content": "last one"})
        collect_reply(socket)

    history = auth.get(f"/api/agents/{agent['id']}/messages?limit=10").json()
    assert len(history["messages"]) == 10

    context = db.recent_history(agent["id"], settings.chat_history_limit)
    assert len(context) <= settings.chat_history_limit


# --------------------------------------------------------------------------- #
# Quota: shared key
# --------------------------------------------------------------------------- #


def test_shared_key_companion_limit(auth):
    for index in range(3):
        assert auth.post(
            "/api/agents", json={"persona": "mentor", "name": f"Pal{index}"}
        ).status_code == 201

    blocked = auth.post("/api/agents", json={"persona": "mentor", "name": "OneTooMany"})
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "quota_agents"


def test_byok_removes_the_companion_limit(auth, user):
    auth.patch("/api/auth/me", json={"gemini_api_key": "AIza-personal"})
    for index in range(5):
        assert auth.post(
            "/api/agents", json={"persona": "mentor", "name": f"Pal{index}"}
        ).status_code == 201


def test_shared_key_daily_message_limit(auth, user, make_agent):
    agent = make_agent()

    with auth.websocket_connect(ws_path(agent["id"], user)) as socket:
        socket.receive_json()
        for index in range(10):
            socket.send_json({"type": "message", "content": f"message {index}"})
            socket.receive_json()  # user_message echo
            socket.receive_json()  # quota frame
            collect_reply(socket)

        socket.send_json({"type": "message", "content": "one too many"})
        blocked = socket.receive_json()
        assert blocked["type"] == "error"
        assert blocked["code"] == "quota_messages"
        assert blocked["quota"]["messages_used_today"] == 10


def test_byok_removes_the_daily_message_limit(auth, user, make_agent):
    auth.patch("/api/auth/me", json={"gemini_api_key": "AIza-personal"})
    agent = make_agent(name="Unlimited")

    with auth.websocket_connect(ws_path(agent["id"], user)) as socket:
        socket.receive_json()
        for index in range(12):
            socket.send_json({"type": "message", "content": f"message {index}"})
            echo = socket.receive_json()
            assert echo["type"] == "user_message"
            collect_reply(socket)


def test_byok_requests_use_the_users_own_key(auth, user, make_agent, offline_llm):
    auth.patch("/api/auth/me", json={"gemini_api_key": "AIza-personal"})
    agent = make_agent(name="BYOK")

    with auth.websocket_connect(ws_path(agent["id"], user)) as socket:
        socket.receive_json()
        socket.send_json({"type": "message", "content": "hi"})
        collect_reply(socket)

    assert offline_llm.instances
    assert offline_llm.instances[-1].api_key == "AIza-personal"


def test_key_added_mid_session_is_used_and_stops_counting(auth, user, make_agent, offline_llm):
    """Adding a key while the socket is open must take effect immediately.

    The Settings dialog saves the key over REST; the already-open websocket used
    to keep the stale user, so the key was ignored *and* every message kept
    counting against the shared-key quota.
    """
    agent = make_agent(name="MidSession")

    with auth.websocket_connect(ws_path(agent["id"], user)) as socket:
        socket.receive_json()  # ready

        # First turn runs on the shared key: it counts and echoes a quota frame.
        socket.send_json({"type": "message", "content": "first"})
        assert socket.receive_json()["type"] == "user_message"
        assert socket.receive_json()["type"] == "quota"
        collect_reply(socket)

        # Add a BYOK key over REST without reopening the socket.
        auth.patch("/api/auth/me", json={"gemini_api_key": "AIza-mid-session"})

        # Second turn must use the fresh key and must not be counted.
        socket.send_json({"type": "message", "content": "second"})
        assert socket.receive_json()["type"] == "user_message"
        collect_reply(socket)

    assert offline_llm.instances[-1].api_key == "AIza-mid-session"
    quota = auth.get("/api/auth/me").json()["user"]["quota"]
    assert quota["unlimited"] is True
    assert quota["messages_used_today"] == 1  # only the pre-key turn counted


def test_key_removed_mid_session_resumes_the_shared_quota(auth, user, make_agent):
    """Removing the key again puts the account back on the shared allowance."""
    auth.patch("/api/auth/me", json={"gemini_api_key": "AIza-personal"})
    agent = make_agent(name="Dropped")

    with auth.websocket_connect(ws_path(agent["id"], user)) as socket:
        socket.receive_json()

        # On BYOK: no counting, no quota frame.
        socket.send_json({"type": "message", "content": "byok turn"})
        assert socket.receive_json()["type"] == "user_message"
        collect_reply(socket)

        # Clear the key over REST while the socket stays open.
        auth.patch("/api/auth/me", json={"gemini_api_key": ""})

        # Back on the shared key: the turn counts and a quota frame arrives.
        socket.send_json({"type": "message", "content": "shared turn"})
        assert socket.receive_json()["type"] == "user_message"
        quota_frame = socket.receive_json()
        assert quota_frame["type"] == "quota"
        assert quota_frame["quota"]["messages_used_today"] == 1
        collect_reply(socket)


def test_engine_is_wired_with_the_configured_models(auth, user, make_agent, offline_llm):
    from app.config import settings

    auth.patch("/api/auth/me", json={"gemini_api_key": "AIza-personal"})
    agent = make_agent(name="Routed")

    with auth.websocket_connect(ws_path(agent["id"], user)) as socket:
        socket.receive_json()
        socket.send_json({"type": "message", "content": "hi"})
        collect_reply(socket)

    engine = offline_llm.instances[-1]
    assert engine.model == settings.gemini_model
    assert engine.kwargs["fallback_model"] == settings.gemini_fallback_model


def test_shared_key_requests_stay_on_the_platform_engine(auth, user, make_agent, offline_llm):
    agent = make_agent(name="HouseKey")

    with auth.websocket_connect(ws_path(agent["id"], user)) as socket:
        socket.receive_json()
        socket.send_json({"type": "message", "content": "hi"})
        collect_reply(socket)

    # No personal key (and no platform key in tests) -> the offline demo engine,
    # never a per-user Gemini client.
    assert offline_llm.instances == []


# --------------------------------------------------------------------------- #
# Conversation management
# --------------------------------------------------------------------------- #


def test_clear_conversation_keeps_the_agent(auth, user, make_agent):
    agent = make_agent()
    with auth.websocket_connect(ws_path(agent["id"], user)) as socket:
        socket.receive_json()
        socket.send_json({"type": "message", "content": "remember this"})
        collect_reply(socket)

    cleared = auth.delete(f"/api/agents/{agent['id']}/messages").json()
    assert cleared["deleted"] == 2
    assert auth.get(f"/api/agents/{agent['id']}/messages").json()["messages"] == []
    assert auth.get(f"/api/agents/{agent['id']}").status_code == 200


def test_starters_match_the_persona(auth, make_agent):
    agent = make_agent(persona="teacher", name="Ms. Verma")
    body = auth.get(f"/api/agents/{agent['id']}/starters").json()
    assert body["starters"]


def test_conversation_is_isolated_per_agent(auth, user, make_agent):
    first = make_agent(name="A")
    second = make_agent(name="B")

    with auth.websocket_connect(ws_path(first["id"], user)) as socket:
        socket.receive_json()
        socket.send_json({"type": "message", "content": "only for A"})
        collect_reply(socket)

    assert auth.get(f"/api/agents/{second['id']}/messages").json()["total"] == 0
    assert auth.get(f"/api/agents/{first['id']}/messages").json()["total"] == 2
