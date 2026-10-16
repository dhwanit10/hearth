"""REST routes: accounts, the personas catalogue and companion management.

Every companion-scoped route requires a bearer token and only ever touches rows
owned by the authenticated user. Companion creation and message sending are
gated by quota rules in :mod:`app.auth`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Response,
    status,
)

from . import auth, db, personas as personas_module
from .auth import current_user, token_from_header
from .config import settings
from .personas import (
    ACCENTS,
    build_system_prompt,
    get_persona,
    list_personas,
    next_accent,
    random_name,
    suggest_names,
)
from .schemas import (
    AgentCreate,
    AgentUpdate,
    AuthOut,
    HealthOut,
    LoginIn,
    MeOut,
    SignupIn,
    UserUpdate,
)

router = APIRouter(prefix="/api", tags=["agents"])

# Prompt material stays server side except on the single-agent detail route,
# where it is exposed deliberately so the UI can show "how this character works".
PUBLIC_FIELDS = (
    "id", "name", "persona", "tagline", "accent", "temperature",
    "created_at", "updated_at", "message_count", "last_message",
    "last_message_at",
)
PREVIEW_CHARS = 140


def _public(agent: dict[str, Any]) -> dict[str, Any]:
    shaped = {key: agent.get(key) for key in PUBLIC_FIELDS}
    last = shaped.get("last_message")
    if isinstance(last, str):
        single_line = " ".join(last.split())
        shaped["last_message"] = (
            single_line
            if len(single_line) <= PREVIEW_CHARS
            else single_line[: PREVIEW_CHARS - 1] + "…"
        )
    return shaped


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    """Shape a user for the client, never exposing the raw API key."""
    return {
        "id": user["id"],
        "email": user["email"],
        "username": user["username"],
        "has_gemini_key": auth.is_byok(user),
        "created_at": user["created_at"],
        "updated_at": user["updated_at"],
        "quota": auth.quota_snapshot(user),
    }


async def _require_agent(agent_id: str, user_id: str) -> dict[str, Any]:
    agent = await asyncio.to_thread(db.get_agent, agent_id, user_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return agent


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #


@router.post(
    "/auth/signup",
    status_code=status.HTTP_201_CREATED,
    response_model=AuthOut,
)
async def signup(payload: SignupIn) -> AuthOut:
    """Create an account and return a session token.

    The very first account claims any companions created before accounts
    existed, so upgrading an existing install does not strand its data.
    """
    if await asyncio.to_thread(db.get_user_by_email, payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )

    first_user = await asyncio.to_thread(db.count_users) == 0
    password_hash = await asyncio.to_thread(auth.hash_password, payload.password)
    user = await asyncio.to_thread(
        db.create_user,
        email=payload.email,
        username=payload.username,
        password_hash=password_hash,
    )
    if first_user:
        await asyncio.to_thread(db.claim_unowned_agents, user["id"])
        user = await asyncio.to_thread(db.get_user, user["id"]) or user

    token = await asyncio.to_thread(auth.issue_session, user["id"])
    return AuthOut(token=token, user=await asyncio.to_thread(_public_user, user))


@router.post("/auth/login", response_model=AuthOut)
async def login(payload: LoginIn) -> AuthOut:
    """Exchange email + password for a session token."""
    user = await asyncio.to_thread(db.get_user_by_email, payload.email)
    if user is None or not auth.verify_password(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    token = await asyncio.to_thread(auth.issue_session, user["id"])
    return AuthOut(token=token, user=await asyncio.to_thread(_public_user, user))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    authorization: str | None = Header(default=None),
    _: dict[str, Any] = Depends(current_user),
) -> Response:
    """Revoke the caller's session token."""
    token = token_from_header(authorization)
    if token:
        await asyncio.to_thread(db.delete_session, token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/auth/me", response_model=MeOut)
async def read_me(user: dict[str, Any] = Depends(current_user)) -> MeOut:
    """The signed-in user plus current quota usage."""
    return MeOut(user=await asyncio.to_thread(_public_user, user))


@router.patch("/auth/me", response_model=MeOut)
async def update_me(
    payload: UserUpdate,
    user: dict[str, Any] = Depends(current_user),
) -> MeOut:
    """Rename the account, change the password, or set/clear the Gemini key."""
    changes: dict[str, Any] = {}
    if payload.username is not None:
        changes["username"] = payload.username
    if payload.gemini_api_key is not None:
        changes["gemini_api_key"] = payload.gemini_api_key
    if payload.new_password is not None:
        if not payload.current_password or not auth.verify_password(
            payload.current_password, user["password_hash"]
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your current password is incorrect.",
            )
        changes["password_hash"] = await asyncio.to_thread(
            auth.hash_password, payload.new_password
        )

    updated = await asyncio.to_thread(db.update_user, user["id"], changes)
    if updated is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    return MeOut(user=await asyncio.to_thread(_public_user, updated))


# --------------------------------------------------------------------------- #
# Personas
# --------------------------------------------------------------------------- #


@router.get("/personas")
async def read_personas() -> dict[str, Any]:
    """Catalogue of companion archetypes for the "new companion" dialog."""
    return {
        "personas": list_personas(),
        "accents": list(ACCENTS),
        "default": personas_module.DEFAULT_PERSONA,
    }


@router.get("/personas/{persona_id}/names")
async def read_name_suggestions(
    persona_id: str,
    count: int = Query(default=3, ge=1, le=10),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """Random names for a persona, skipping ones already in use by this user."""
    if persona_id not in personas_module.PERSONAS:
        raise HTTPException(status_code=404, detail="Persona not found.")
    taken = await asyncio.to_thread(db.taken_names, user["id"])
    return {"persona": persona_id, "names": suggest_names(persona_id, count=count, exclude=taken)}


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """Everything the UI needs to render its connection/LLM status pill."""
    from . import __version__
    from .gemini import llm_status

    return HealthOut(
        app="Hearth",
        version=__version__,
        database=str(settings.database_path.name),
        llm=llm_status(),
    )


# --------------------------------------------------------------------------- #
# Agents
# --------------------------------------------------------------------------- #


@router.get("/agents")
async def read_agents(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    agents = await asyncio.to_thread(db.list_agents, user["id"])
    return {"agents": [_public(agent) for agent in agents]}


@router.post("/agents", status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """Create a companion. Omit ``name`` to let the server pick one at random."""
    if not auth.is_byok(user):
        existing_count = await asyncio.to_thread(db.count_user_agents, user["id"])
        if existing_count >= settings.shared_key_max_agents:
            raise auth.agent_quota_error(user)

    persona = get_persona(payload.persona)
    taken = await asyncio.to_thread(db.taken_names, user["id"])

    name = payload.name or random_name(persona.id, exclude=taken)

    custom_prompt = payload.custom_prompt
    if persona.custom and not custom_prompt:
        raise HTTPException(
            status_code=422,
            detail="A custom companion needs a character brief (custom_prompt).",
        )

    accent = payload.accent
    if not accent:
        existing = await asyncio.to_thread(db.list_agents, user["id"])
        accent = next_accent([agent["accent"] for agent in existing])

    agent = await asyncio.to_thread(
        db.create_agent,
        name=name,
        persona=persona.id,
        tagline=payload.tagline or persona.tagline,
        system_prompt=build_system_prompt(persona.id, name, custom_prompt),
        custom_prompt=custom_prompt,
        accent=accent,
        temperature=persona.temperature,
        user_id=user["id"],
    )
    return {"agent": _public(agent)}


@router.get("/agents/{agent_id}")
async def read_agent(
    agent_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """Single agent, including the generated system prompt (transparency)."""
    agent = await _require_agent(agent_id, user["id"])
    shaped = _public(agent)
    shaped["system_prompt"] = agent["system_prompt"]
    shaped["custom_prompt"] = agent["custom_prompt"]
    return {"agent": shaped}


@router.patch("/agents/{agent_id}")
async def patch_agent(
    agent_id: str,
    payload: AgentUpdate,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """Rename, retag or rewrite a companion's brief."""
    agent = await _require_agent(agent_id, user["id"])
    changes: dict[str, Any] = {}

    if payload.name is not None:
        changes["name"] = payload.name
    if payload.tagline is not None:
        changes["tagline"] = payload.tagline
    if payload.accent is not None:
        changes["accent"] = payload.accent

    custom_prompt = (
        agent["custom_prompt"] if payload.custom_prompt is None
        else payload.custom_prompt
    )
    if payload.custom_prompt is not None:
        changes["custom_prompt"] = custom_prompt

    # The prompt depends on the name and the brief, so rebuild when either moves.
    name = changes.get("name", agent["name"])
    if "name" in changes or "custom_prompt" in changes:
        changes["system_prompt"] = build_system_prompt(
            agent["persona"], name, custom_prompt
        )

    updated = await asyncio.to_thread(db.update_agent, agent_id, changes)
    if updated is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return {"agent": _public(updated)}


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_agent(
    agent_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> Response:
    """Delete a companion and its whole conversation history."""
    from .ws import hub

    await _require_agent(agent_id, user["id"])
    deleted = await asyncio.to_thread(db.delete_agent, agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found.")
    # Hang up any live socket watching this agent.
    await hub.close_room(agent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #


@router.get("/agents/{agent_id}/messages")
async def read_messages(
    agent_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    before: int | None = Query(default=None, ge=1),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """Conversation history, oldest first. Page backwards with ``before``."""
    await _require_agent(agent_id, user["id"])
    messages = await asyncio.to_thread(
        db.list_messages, agent_id, limit=limit, before_id=before
    )
    total = await asyncio.to_thread(db.count_messages, agent_id)
    return {
        "agentId": agent_id,
        "messages": messages,
        "total": total,
        "hasMore": before is not None and len(messages) == limit,
    }


@router.delete("/agents/{agent_id}/messages", status_code=status.HTTP_200_OK)
async def clear_messages(
    agent_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """Wipe the conversation but keep the companion."""
    await _require_agent(agent_id, user["id"])
    removed = await asyncio.to_thread(db.clear_messages, agent_id)
    return {"agentId": agent_id, "deleted": removed}


@router.delete(
    "/agents/{agent_id}/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_message(
    agent_id: str,
    message_id: int,
    user: dict[str, Any] = Depends(current_user),
) -> Response:
    await _require_agent(agent_id, user["id"])
    deleted = await asyncio.to_thread(db.delete_message, agent_id, message_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Message not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/agents/{agent_id}/starters")
async def read_starters(
    agent_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    """Suggested opening prompts for an empty conversation."""
    agent = await _require_agent(agent_id, user["id"])
    persona = get_persona(agent["persona"])
    return {"agentId": agent_id, "starters": list(persona.starters)}
