"""Websocket hub: the live chat transport.

Connect with a session token: ``/ws/chat/{agent_id}?token=<bearer>``. The token
is validated before anything else and the companion must belong to that user.

Protocol (JSON frames, all events carry ``agentId`` so a client can never
mistake a message from another conversation for its own):

    client -> server
        {"type": "message", "content": "..."}   send a chat message
        {"type": "stop"}                        stop the in-flight reply
        {"type": "ping"}                        keepalive

    server -> client
        {"type": "ready",           agent: {...} }
        {"type": "user_message",    message: {...} }
        {"type": "assistant_start", message: {...placeholder} }
        {"type": "delta",           content: "..." }
        {"type": "assistant_end",   message: {...} , stopped: bool }
        {"type": "quota",           quota: {...} }
        {"type": "error",           message: "...", code: "..." }
        {"type": "cancelled" }

Design notes
------------
* Each agent id gets a *room*. Every browser tab watching that agent receives
  the same stream, so two windows stay perfectly in sync.
* Only one generation may run per room at a time; a second message while the
  model is talking is rejected with ``code="busy"``.
* Replies are streamed to the client as they arrive and persisted once, at the
  end, so a dropped connection never leaves a half-written row behind.
* "Stop" is cooperative (an ``asyncio.Event`` checked between chunks) rather
  than a task cancellation, which keeps the persistence path predictable.
* Shared-key users are capped at ``SHARED_KEY_DAILY_MESSAGES`` messages per UTC
  day; users who bring their own Gemini key are unlimited. The user's key, when
  present, is the one used for the request.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import auth, db
from .config import settings
from .gemini import LLMError, stream_reply

logger = logging.getLogger("hearth.ws")

router = APIRouter()

# 4404 mirrors HTTP 404 so the frontend can tell "no such agent" from a drop.
WS_NOT_FOUND = 4404
# 4401 mirrors HTTP 401: the token was missing or expired.
WS_UNAUTHORIZED = 4401


@dataclass
class Room:
    """All live connections for one agent plus its generation state."""

    agent_id: str
    connections: set[WebSocket] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None

    @property
    def busy(self) -> bool:
        return self.task is not None and not self.task.done()

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """Send to every listener, pruning sockets that have gone away."""
        if not self.connections:
            return
        payload.setdefault("agentId", self.agent_id)
        dead: list[WebSocket] = []
        for socket in list(self.connections):
            try:
                await socket.send_json(payload)
            except Exception:  # noqa: BLE001 - any failure means drop the socket
                dead.append(socket)
        for socket in dead:
            self.connections.discard(socket)


class Hub:
    """Process-wide registry of rooms."""

    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._guard = asyncio.Lock()

    async def join(self, agent_id: str, socket: WebSocket) -> Room:
        async with self._guard:
            room = self._rooms.get(agent_id)
            if room is None:
                room = Room(agent_id)
                self._rooms[agent_id] = room
        room.connections.add(socket)
        return room

    async def leave(self, room: Room, socket: WebSocket) -> None:
        room.connections.discard(socket)
        async with self._guard:
            if not room.connections:
                self._rooms.pop(room.agent_id, None)

    async def close_room(self, agent_id: str) -> None:
        """Called when an agent is deleted: stop work and hang up."""
        async with self._guard:
            room = self._rooms.pop(agent_id, None)
        if room is None:
            return
        room.stop.set()
        for socket in list(room.connections):
            try:
                await socket.close(code=1000, reason="agent deleted")
            except Exception:  # noqa: BLE001
                pass
        room.connections.clear()

    async def disconnect_agent(self, agent_id: str) -> None:
        await self.close_room(agent_id)


hub = Hub()


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #


async def _generate(
    room: Room,
    agent: dict[str, Any],
    user_text: str,
    api_key: str | None = None,
) -> None:
    """Stream one assistant reply for ``agent``, persisting it at the end."""
    agent_id = room.agent_id
    parts: list[str] = []
    stopped = False
    failure: str | None = None

    placeholder = {
        "id": None,
        "agent_id": agent_id,
        "role": "assistant",
        "content": "",
        "status": "partial",
        "created_at": db.utcnow(),
    }
    await room.broadcast({"type": "assistant_start", "message": placeholder})

    history = await asyncio.to_thread(
        db.recent_history, agent_id, settings.chat_history_limit
    )

    try:
        async for piece in stream_reply(
            system_prompt=agent["system_prompt"],
            history=history,
            temperature=float(agent.get("temperature") or 0.85),
            persona=agent.get("persona") or "custom",
            api_key=api_key,
        ):
            if room.stop.is_set():
                stopped = True
                break
            parts.append(piece)
            await room.broadcast({"type": "delta", "content": piece})
    except LLMError as exc:
        failure = exc.message
        logger.warning("LLM error for agent %s: %s", agent_id, exc.message)
    except Exception as exc:  # noqa: BLE001 - never kill the socket
        failure = "Something went wrong while generating that reply."
        logger.exception("Unexpected generation failure for agent %s", agent_id)
        logger.debug("cause: %s", exc)
    finally:
        room.stop.clear()

    text = "".join(parts).strip()

    # The agent may have been deleted while the model was talking.
    if not await asyncio.to_thread(db.agent_exists, agent_id):
        return

    message: dict[str, Any] | None = None
    if text:
        status = "partial" if (stopped or failure) else "complete"
        message = await asyncio.to_thread(
            db.add_message, agent_id, "assistant", text, status=status
        )

    if message is None:
        # Nothing usable was produced: tell the client to drop its placeholder.
        await room.broadcast(
            {
                "type": "assistant_end",
                "message": None,
                "stopped": stopped,
                "error": failure,
            }
        )
    else:
        await room.broadcast(
            {
                "type": "assistant_end",
                "message": message,
                "stopped": stopped,
                "error": failure,
            }
        )

    if stopped:
        await room.broadcast({"type": "cancelled", "reason": "stopped"})
    elif failure:
        await room.broadcast({
            "type": "error",
            "code": "llm_error",
            "message": failure,
        })


# --------------------------------------------------------------------------- #
# Socket endpoint
# --------------------------------------------------------------------------- #


@router.websocket("/ws/chat/{agent_id}")
async def chat_socket(websocket: WebSocket, agent_id: str) -> None:
    await websocket.accept()

    # Browsers cannot set headers on a WebSocket, so the bearer token rides in
    # the query string instead.
    token = websocket.query_params.get("token")
    user = await asyncio.to_thread(auth.user_for_token, token)
    if user is None:
        await websocket.send_json(
            {"type": "error", "code": "unauthorized",
             "message": "Your session has expired. Please sign in again."}
        )
        await websocket.close(code=WS_UNAUTHORIZED)
        return

    agent = await asyncio.to_thread(db.get_agent, agent_id, user["id"])
    if agent is None:
        await websocket.send_json(
            {"type": "error", "code": "not_found", "message": "Unknown agent."}
        )
        await websocket.close(code=WS_NOT_FOUND)
        return

    room = await hub.join(agent_id, websocket)
    await websocket.send_json(
        {"type": "ready", "agentId": agent_id, "agent": _public_agent(agent)}
    )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {"type": "error", "code": "bad_json", "message": "Malformed frame."}
                )
                continue

            kind = payload.get("type")

            if kind == "ping":
                await websocket.send_json({"type": "pong", "agentId": agent_id})
                continue

            if kind == "stop":
                if room.busy:
                    room.stop.set()
                else:
                    await websocket.send_json(
                        {"type": "error", "code": "idle",
                         "message": "Nothing is being generated right now."}
                    )
                continue

            if kind != "message":
                await websocket.send_json(
                    {"type": "error", "code": "bad_frame",
                     "message": f"Unknown frame type: {kind!r}"}
                )
                continue

            content = str(payload.get("content") or "").strip()
            if not content:
                await websocket.send_json(
                    {"type": "error", "code": "empty",
                     "message": "Message content cannot be empty."}
                )
                continue

            if len(content) > 8000:
                await websocket.send_json(
                    {"type": "error", "code": "too_long",
                     "message": "That message is too long (8000 character limit)."}
                )
                continue

            if room.busy:
                await websocket.send_json({
                    "type": "error",
                    "code": "busy",
                    "message": "Still answering the previous message.",
                })
                continue

            # The account can change while this socket is open: the Settings
            # dialog saves a BYOK key over REST, so re-read the user now. This
            # makes a newly added key take effect immediately and stops BYOK
            # accounts from being counted against the shared-key quota.
            fresh_user = await asyncio.to_thread(db.get_user, user["id"])
            if fresh_user is not None:
                user = fresh_user

            # Shared-key users get a small daily allowance; BYOK users do not.
            if not auth.is_byok(user):
                used = await asyncio.to_thread(db.daily_message_count, user["id"])
                if used >= settings.shared_key_daily_messages:
                    await websocket.send_json({
                        "type": "error",
                        "code": auth.QUOTA_MESSAGES,
                        "message": (
                            f"You have used all "
                            f"{settings.shared_key_daily_messages} messages for "
                            "today on the shared key. Add your own Gemini API "
                            "key in Settings for unlimited messages."
                        ),
                        "quota": await asyncio.to_thread(auth.quota_snapshot, user),
                    })
                    continue

            # Re-read the agent: its prompt may have been edited since connect.
            fresh = await asyncio.to_thread(db.get_agent, agent_id, user["id"])
            if fresh is None:
                await websocket.send_json(
                    {"type": "error", "code": "not_found", "message": "Unknown agent."}
                )
                await websocket.close(code=WS_NOT_FOUND)
                return

            saved = await asyncio.to_thread(db.add_message, agent_id, "user", content)
            await room.broadcast(
                {"type": "user_message", "message": _public_message(saved)}
            )

            if not auth.is_byok(user):
                await asyncio.to_thread(db.record_daily_message, user["id"])
                await websocket.send_json({
                    "type": "quota",
                    "quota": await asyncio.to_thread(auth.quota_snapshot, user),
                })

            room.task = asyncio.create_task(
                _generate(room, fresh, content, user.get("gemini_api_key") or None)
            )

    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("Websocket failure for agent %s", agent_id)
    finally:
        room.stop.set()
        await hub.leave(room, websocket)


# --------------------------------------------------------------------------- #
# Serialisation helpers
# --------------------------------------------------------------------------- #

HIDDEN_AGENT_FIELDS = {"system_prompt", "custom_prompt"}


def _public_agent(agent: dict[str, Any]) -> dict[str, Any]:
    """Strip internal prompt material before it leaves the server."""
    return {k: v for k, v in agent.items() if k not in HIDDEN_AGENT_FIELDS}


def _public_message(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": message["id"],
        "agent_id": message["agent_id"],
        "role": message["role"],
        "content": message["content"],
        "status": message.get("status", "complete"),
        "created_at": message["created_at"],
    }
