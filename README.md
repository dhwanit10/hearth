# Hearth

A private chat app for **AI companions**. Each companion is its own character -
a sarcastic best friend, a flirty girlfriend, a patient teacher, a straight-talking
mentor, or someone you invent from scratch. Every companion has a name, a voice,
and a memory that persists across restarts.

Warm, flat, and quiet by design: no shadows, no emoji, no blue.

```
Hearth/
├─ backend/     FastAPI + PostgreSQL + Gemini, accounts + BYOK quota, streaming replies over WebSockets
└─ frontend/    React + Vite, light and dark themes
```

---

## What it does

- **Accounts, not a shared free-for-all.** Sign up with an email and password
  (hashed with PBKDF2) and every companion, message and setting is scoped to
  your account. Sessions are opaque bearer tokens; nothing else can see your
  chats.
- **Bring your own key.** Drop in your own Gemini API key in Settings and you
  get unlimited companions and messages - your key, your quota. Riding on the
  shared key instead caps you at 3 companions and 10 messages a day, and the UI
  keeps nudging you to add your own.
- **Companions, not assistants.** Five archetypes ship with hand-written
  personality prompts: `Best Friend` (sarcastic, roasts you, loyal underneath),
  `Girlfriend` (warm, flirty, notices your mood), `Teacher` (patient, checks you
  actually understood), `Mentor` (direct, one clear next action), and `Custom`
  (you write the character brief and the model performs it).
- **Random name or yours.** Creating a companion suggests names for the chosen
  archetype - shuffle until one fits, or type your own. Leave it blank and the
  server picks.
- **Persistent history.** Every message is stored in PostgreSQL. Close the tab,
  restart the machine, come back in a week: the conversation is waiting.
- **Token streaming over WebSockets.** Replies appear word by word, and two
  browser tabs watching the same companion stay in sync.
- **Streaming-aware UI.** Streaming text is coalesced to one paint per animation
  frame, so long answers stay smooth without dropping characters.
- **Light and dark themes**, both hand-tuned, both warm.

## Quick start

Two terminals. You need **Python 3.11+**, **Node 18+** and a running
**PostgreSQL** server (create a database and set `DATABASE_URL` in
`backend/.env`; the schema is created on first boot).

**1. Backend**

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
Copy-Item .env.example .env         # set DATABASE_URL, then add your GEMINI_API_KEY
uvicorn app.main:app --reload
```

The API is now on <http://127.0.0.1:8000> (interactive docs at `/docs`).

**2. Frontend**

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The Vite dev server proxies `/api` and `/ws` to
the backend, so nothing needs configuring.

### It runs without an API key

If `GEMINI_API_KEY` is empty the backend starts in **demo mode**: replies come
from a small offline engine that streams in-character text through the exact
same websocket protocol. You get the full app - creation, streaming,
persistence, themes - with zero setup. The UI shows a dismissible "Demo mode"
notice so this is never ambiguous.

Get a key at <https://aistudio.google.com/apikey>, put it in `backend/.env`, and
restart. The UI pill switches from `Demo` to the model name.

### The shared key vs. bring your own

`GEMINI_API_KEY` in `backend/.env` is the **shared** platform key. Users who
supply their own key in Settings ("BYOK") get unlimited companions and messages
and none of your tokens are spent; everyone on the shared key is capped at 3
companions and 10 messages per UTC day, and the UI prompts them to add their own
key. Every account is separate: companions, history and settings are scoped to
the signed-in user.

## How a reply is produced

```
browser ──POST /api/auth/login──► FastAPI ──► users / sessions (PostgreSQL)
   │                                   ▲
   └──POST /api/agents (bearer token)──┘──► agents / messages (PostgreSQL)
   │
   └──ws /ws/chat/{id}?token=…──► Hub room ──► build context (last N messages)
                                      │
                                      ├─► user key, else shared key, else demo
                                      │      chunks ──► {"type":"delta"} ──► browser
                                      └─► save final message ──► PostgreSQL
```

0. The client signs in and stores the bearer token; REST calls send it as an
   `Authorization` header and the websocket carries it in the query string.
1. The client sends `{"type": "message", "content": "..."}` over the socket.
2. The user turn is written to PostgreSQL **first**, then broadcast to every
   listener in that companion's room.
3. The last `CHAT_HISTORY_LIMIT` messages are replayed to Gemini as context,
   together with the companion's stored system prompt.
4. Gemini streams SSE chunks; each becomes a `delta` frame.
5. The finished reply is persisted once, at the end, and announced with
   `assistant_end`.

Because replies are persisted only when complete, a dropped connection never
leaves a half-written row behind. "Stop" is cooperative: the generation loop
checks a flag between chunks, saves what it has, and marks the message `partial`.

## Documentation

| Document | Contents |
| --- | --- |
| [`backend/README.md`](backend/README.md) | Endpoints, websocket protocol, personas, database schema, Gemini details, tests |
| [`frontend/README.md`](frontend/README.md) | Design system, theme tokens, component map, websocket hook, deployment |

## Verified

Both halves ship with tests that run offline - no API key, no network:

```powershell
cd backend  ; .\.venv\Scripts\python.exe -m pytest tests -q   # 30 passed
cd frontend ; npm test                                       # 108 passed
```

The backend suite drives the real ASGI app (including a websocket round trip and
PostgreSQL assertions). The frontend suite renders the actual React tree and includes
a **palette guard** that parses every colour literal in the stylesheet and fails
if any of them drifts out of the warm band - so "no blue, violet, purple, green
or pink" is enforced by a test rather than by trust.

For a full end-to-end pass against a running server:

```powershell
# with uvicorn already running
cd backend
.\.venv\Scripts\python.exe scripts\live_check.py
```

## Configuration

Both halves are configured through `.env` files (copied from the `.env.example`
in each folder). The backend reads:

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | *(empty)* | Empty means demo mode; with users this is the shared platform key |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Any Gemini model id |
| `GEMINI_FALLBACK_MODEL` | `gemini-3.5-flash-lite` | Backup model tried once if the primary fails before streaming (empty disables) |
| `GEMINI_THINKING_LEVEL` | `low` | `minimal`/`low`/`medium`/`high`, or empty for the model default |
| `GEMINI_MAX_OUTPUT_TOKENS` | `1024` | Ceiling per reply |
| `CHAT_HISTORY_LIMIT` | `24` | Messages of context replayed to the model |
| `SHARED_KEY_MAX_AGENTS` | `3` | Companions a shared-key user may create |
| `SHARED_KEY_DAILY_MESSAGES` | `10` | User messages a shared-key user may send per UTC day |
| `SESSION_TTL_DAYS` | `30` | Login session lifetime |
| `DATABASE_URL` | `postgresql+psycopg2://postgres:postgres@localhost:5432/hearth` | SQLAlchemy/psycopg2 connection string |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed browser origins |

The frontend reads `VITE_API_BASE`, `VITE_WS_BASE` (both empty = same origin via
the dev proxy) and `VITE_PROXY_TARGET`.

## Troubleshooting

**"Backend not reachable" in the UI.** The API is not listening on port 8000.
Start uvicorn in `backend/`, or set `VITE_PROXY_TARGET` if it runs elsewhere.

**`localhost` vs `127.0.0.1`.** Vite binds to `localhost`, which resolves to
IPv6 on some Windows setups. Open <http://localhost:5173>, not the IPv4 address.

**Replies are canned.** That is demo mode - no API key configured. Check
`/api/health`; `llm.mode` should read `gemini`.

**Gemini returns 404 for the model.** The model id in `GEMINI_MODEL` does not
exist for the current API version. Model names change often; the error message
names the model it tried. If you set `GEMINI_FALLBACK_MODEL`, the backend retries
once on it automatically before giving up.

## Notes

This is a personal companion app, so friendliness thresholds are relaxed
(`BLOCK_ONLY_HIGH`) in `backend/app/gemini.py`. Companions are instructed to
break character and point to real help if the conversation turns into a genuine
crisis. Flirting is capped at tasteful and suggestive by the persona prompt.
