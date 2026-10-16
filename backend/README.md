# Hearth - backend

FastAPI service that owns companions, conversations and the Gemini connection.
Streams replies to the browser over WebSockets and keeps everything in SQLite.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1       # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
Copy-Item .env.example .env        # add GEMINI_API_KEY (optional, see below)
uvicorn app.main:app --reload
```

- API root: <http://127.0.0.1:8000>
- Interactive docs: <http://127.0.0.1:8000/docs>
- Health + LLM status: <http://127.0.0.1:8000/api/health>

`python -m app` is equivalent to the uvicorn command and reads `HOST`/`PORT`
from `.env`.

### Demo mode

With no `GEMINI_API_KEY`, `app/gemini.py` swaps in `DemoEngine`, a small offline
responder that streams in-character lines through the identical code path. Every
endpoint, the websocket protocol, persistence and the UI work exactly as they do
with a real key, which makes the project runnable with zero setup and keeps the
test suite hermetic.

## Configuration

All settings live in `app/config.py` and are read from `.env` (real environment
variables win). See `.env.example` for the full list with commentary.

| Variable | Default | Notes |
| --- | --- | --- |
| `GEMINI_API_KEY` | *(empty)* | Empty enables demo mode; with users this is the *shared* platform key |
| `GEMINI_MODEL` | `gemini-3.8-flash` | `gemini-3.5-flash-lite` / `gemini-3.1-flash-lite` are cheaper and lower latency |
| `GEMINI_FALLBACK_MODEL` | `gemini-3.5-flash-lite` | Tried once if the primary model fails before streaming anything (empty disables) |
| `GEMINI_THINKING_LEVEL` | `low` | Gemini 3 thinking budget; lower is snappier for chat |
| `GEMINI_MAX_OUTPUT_TOKENS` | `1024` | |
| `CHAT_HISTORY_LIMIT` | `24` | Messages of context per request |
| `SHARED_KEY_MAX_AGENTS` | `3` | Companions a shared-key user may create |
| `SHARED_KEY_DAILY_MESSAGES` | `10` | User messages a shared-key user may send per UTC day |
| `SESSION_TTL_DAYS` | `30` | Login session lifetime |
| `DATABASE_PATH` | `data/hearth.db` | Relative to `backend/` |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma separated |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Used by `python -m app` |

## Accounts, BYOK and quota

Every companion and conversation belongs to a user. Accounts are `email` +
`username` + password (hashed with PBKDF2-HMAC-SHA256, stdlib only). Signing in
returns an opaque bearer token stored in the `sessions` table; REST calls send it
as `Authorization: Bearer <token>` and the websocket carries it in the query
string (`/ws/chat/{id}?token=...`), because browsers cannot set headers on a
WebSocket handshake.

Users may store their **own** Gemini API key ("bring your own key"). It is kept
in the `users` table (a local SQLite file), used only for that user's requests,
and never returned to the client. The quota rules are:

- **Own key (BYOK):** unlimited companions, unlimited messages.
- **Shared key:** `SHARED_KEY_MAX_AGENTS` companions and
  `SHARED_KEY_DAILY_MESSAGES` messages per UTC day, counted in `usage_daily`.
  Going over returns a `quota_agents` / `quota_messages` error the UI turns into
  a "add your own key" prompt.

The first account created claims any companions that existed before accounts
were introduced (`db.claim_unowned_agents`), so upgrading an existing database
does not strand its data.

## REST API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Status plus the active LLM mode/model |
| `POST` | `/api/auth/signup` | Create an account, return a token |
| `POST` | `/api/auth/login` | Exchange email + password for a token |
| `POST` | `/api/auth/logout` | Revoke the caller's token |
| `GET` | `/api/auth/me` | Current user + quota usage |
| `PATCH` | `/api/auth/me` | Rename, change password, set/clear the Gemini key |
| `GET` | `/api/personas` | Archetype catalogue, accent list, default |
| `GET` | `/api/personas/{id}/names?count=3` | Random names, skipping ones already in use |
| `GET` | `/api/agents` | Companions with preview, message count, sorted by activity |
| `POST` | `/api/agents` | Create; omit `name` for a server-chosen random one |
| `GET` | `/api/agents/{id}` | One companion, including its generated system prompt |
| `PATCH` | `/api/agents/{id}` | Rename, retag, recolor, rewrite the brief |
| `DELETE` | `/api/agents/{id}` | Delete the companion and its history, and close its socket |
| `GET` | `/api/agents/{id}/messages?limit&before` | History, oldest first; `before` pages backwards |
| `DELETE` | `/api/agents/{id}/messages` | Clear the conversation, keep the companion |
| `DELETE` | `/api/agents/{id}/messages/{messageId}` | Delete one message |
| `GET` | `/api/agents/{id}/starters` | Suggested opening prompts |

Everything except `/api/health` and `/api/personas` requires a bearer token, and
companion routes only ever see the caller's own rows.

`system_prompt` and `custom_prompt` are stripped from list responses and returned
only on the single-companion route.

## WebSocket protocol

`ws://127.0.0.1:8000/ws/chat/{agent_id}?token={bearer}`

The token is validated on connect (close code `4401` if it is missing or stale)
and the companion must belong to that user (close code `4404` otherwise). Every
frame carries `agentId`. One generation may run per companion at a time.

**Client to server**

```jsonc
{ "type": "message", "content": "hey, you around?" }  // send a turn
{ "type": "stop" }                                    // stop the current reply
{ "type": "ping" }                                    // keepalive
```

**Server to client**

```jsonc
{ "type": "ready",           "agent": { ... } }
{ "type": "user_message",    "message": { ... } }        // persisted + echoed
{ "type": "assistant_start", "message": { ... } }        // placeholder, id null
{ "type": "delta",           "content": "partial text" } // one per chunk
{ "type": "assistant_end",   "message": { ... }, "stopped": false, "error": null }
{ "type": "quota",           "quota": { ... } }          // shared-key usage
{ "type": "cancelled",       "reason": "stopped" }
{ "type": "pong" }
{ "type": "error",           "code": "busy", "message": "..." }
```

Error codes: `bad_json`, `bad_frame`, `empty`, `too_long`, `busy`, `idle`,
`not_found`, `unauthorized`, `quota_messages`, `llm_error`. Close codes `4401`
and `4404` mean "session expired" and "no such companion".

Rooms fan out to every connection, so a second tab sees the same stream. When a
reply ends with partial text (stopped, or the provider failed mid-stream) the
message is still saved, with `status` set to `partial`, and `error` carries the
reason. Shared-key users receive a `quota` frame after each accepted turn and an
error with `code="quota_messages"` once the daily allowance is spent; BYOK users
are unlimited.

## Personas and prompting

`app/personas.py` holds one `Persona` record per archetype: label, tagline,
description, trait chips, starters, a temperature, a pool of names, and a
`role_prompt`.

`build_system_prompt(persona_id, name, custom_prompt)` composes the final system
instruction from three parts:

1. **Who you are** - the archetype's role prompt, with the companion's name and
   (for `custom`) the user's character brief interpolated.
2. **Voice** - how that specific archetype should sound and what it must not do.
3. **House rules** - shared across every companion: text like a real person in
   short messages, no emoji, never mention being an AI or having instructions,
   never invent personal facts about the user, mirror the user's language
   (including Hinglish), and drop the act for one message to point at real help
   in a genuine crisis.

The runner-up rule matters most: it is what keeps a companion from saying "As an
AI language model..." mid-conversation.

### Adding an archetype

Append a `_register(Persona(...))` block in `app/personas.py`. The REST
catalogue, the name generator, and the frontend dialog (which is data-driven off
`GET /api/personas`) all pick it up with no other changes. The only frontend
addition is an icon mapping in `frontend/src/components/personaIcons.js`.

## Talking to Gemini

`app/gemini.py` is a thin `httpx` client - no vendor SDK, so there is nothing to
version-pin or churn.

- `POST /v1beta/models/{model}:streamGenerateContent?alt=sse`, authenticated with
  the `x-goog-api-key` header.
- `system_instruction` carries the persona prompt; the last
  `CHAT_HISTORY_LIMIT` turns are sent as `contents` with `assistant` mapped to
  the `model` role.
- Gemini 3 returns internal reasoning as parts flagged `thought: true`; those are
  skipped so only the visible answer reaches the user.
- `thinkingConfig` is set from `GEMINI_THINKING_LEVEL`. If a model or API version
  rejects it with a 400, the request is retried once without it instead of
  failing the conversation.
- If the primary model fails before emitting anything with a model-specific or
  transient error (404 unknown model, 429 rate limit, 5xx upstream, or a
  persistent 400), the request is retried once on `GEMINI_FALLBACK_MODEL`.
  Rejected keys (401/403) and content the model declined to produce are not
  retried, and a reply that already started streaming is never discarded.
- Provider failures become readable messages (401/403 key rejected, 404 unknown
  model, 429 rate limited, 5xx upstream) and surface in the UI as a dismissible
  notice, never as a broken socket.
- Safety thresholds are relaxed to `BLOCK_ONLY_HIGH`: this is a personal
  companion app, not a general-purpose assistant.

## Database

SQLite via stdlib `sqlite3`, opened per call (WAL, `foreign_keys=ON`,
`busy_timeout=5000`) and run inside `asyncio.to_thread` so the event loop never
blocks on disk. `init_db()` runs on startup and only issues
`CREATE TABLE IF NOT EXISTS`.

```sql
users       (id, email UNIQUE, username, password_hash, gemini_api_key,
             created_at, updated_at)
sessions    (token PK, user_id → users.id ON DELETE CASCADE,
             created_at, expires_at)
usage_daily (user_id → users.id, day, messages, PRIMARY KEY (user_id, day))

agents      (id, user_id → users.id ON DELETE CASCADE, name, persona, tagline,
             system_prompt, custom_prompt, accent, temperature,
             created_at, updated_at)

messages    (id, agent_id → agents.id ON DELETE CASCADE, role, content,
             status, created_at)          -- status: complete | partial | error
```

Deleting a companion cascades to its messages and closes any live socket.
Deleting a user cascades to their companions, sessions and usage rows.

`init_db()` runs on startup, issues `CREATE TABLE IF NOT EXISTS`, and then
patches older databases (currently by adding `agents.user_id`) so an existing
file upgrades in place.

## Tests

```powershell
pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q          # 30 tests
.\.venv\Scripts\python.exe scripts\live_check.py       # against a running server
```

`tests/conftest.py` pins a temporary database and forces the offline demo engine
**before** importing the app, so the suite never touches your real data and never
reaches the network - even the BYOK paths run against a stand-in Gemini client
that records the key it was handed. Coverage includes signup/login/logout, token
enforcement on REST and WebSocket, per-user data isolation, first-signup claiming
of legacy companions, the companion and daily-message quotas (and their removal
via BYOK), agent CRUD, prompt rebuilding on rename, name suggestions avoiding
collisions, the blank/unknown/bad-JSON frame paths, multi-chunk streaming with
byte-exact persistence, history trimming and clearing.

`scripts/live_check.py` is the opposite: it signs in as a throwaway account and
drives a real uvicorn server over real TCP sockets, asserting the full happy
path, then cleans up after itself.
