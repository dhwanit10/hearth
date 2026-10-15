"""End to end check against a *running* Hearth backend.

Unlike the pytest suite (which drives the ASGI app in-process), this talks to a
real uvicorn server over a real TCP socket, which also proves the websocket
upgrade and JSON framing work outside of the test client.

Usage:
    uvicorn app.main:app --port 8000      # in one terminal
    python scripts/live_check.py          # in another
    python scripts/live_check.py http://127.0.0.1:9000
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx
import websockets

TIMEOUT = 30.0
ok = True


def report(label: str, value: str) -> None:
    print(f"  {label:<14}{value}")


def check(condition: bool, label: str) -> None:
    global ok
    ok = ok and bool(condition)
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")


async def main(base_url: str) -> int:
    print(f"\nHearth live check -> {base_url}\n")

    async with httpx.AsyncClient(base_url=base_url, timeout=TIMEOUT) as client:
        # --- REST ---------------------------------------------------------- #
        print("REST")
        health = (await client.get("/api/health")).json()
        report("health", health["status"])
        report("llm mode", f"{health['llm']['mode']} ({health['llm']['model']})")
        check(health["status"] == "ok", "health endpoint responds")

        catalogue = (await client.get("/api/personas")).json()
        ids = [persona["id"] for persona in catalogue["personas"]]
        report("personas", ", ".join(ids))
        check(len(ids) >= 4, "persona catalogue is populated")

        created = await client.post("/api/agents", json={"persona": "girlfriend"})
        check(created.status_code == 201, "agent created")
        agent = created.json()["agent"]
        report("created", f"{agent['name']} (accent={agent['accent']})")
        check(bool(agent["name"]), "server assigned a random name")

        try:
            # --- WebSocket ------------------------------------------------- #
            print("\nWebSocket")
            url = base_url.replace("https://", "wss://").replace("http://", "ws://")
            async with websockets.connect(f"{url}/ws/chat/{agent['id']}") as socket:
                ready = json.loads(await asyncio.wait_for(socket.recv(), TIMEOUT))
                check(ready["type"] == "ready", "ready frame received")

                await socket.send(json.dumps({"type": "message", "content": "hey, how are you?"}))

                echo = json.loads(await asyncio.wait_for(socket.recv(), TIMEOUT))
                check(echo["type"] == "user_message", "user message persisted and echoed")

                first = json.loads(await asyncio.wait_for(socket.recv(), TIMEOUT))
                check(first["type"] == "assistant_start", "streaming started")

                chunks: list[str] = []
                final = None
                while True:
                    event = json.loads(await asyncio.wait_for(socket.recv(), TIMEOUT))
                    if event["type"] == "delta":
                        chunks.append(event["content"])
                    elif event["type"] == "assistant_end":
                        final = event
                        break

                text = "".join(chunks).strip()
                report("chunks", str(len(chunks)))
                report("reply", (text[:70] + "...") if len(text) > 70 else text)
                check(len(chunks) > 1, "reply arrived as multiple streamed chunks")
                check(bool(text), "reply text is not empty")
                check(final["message"] is not None, "assistant message was saved")
                if final.get("error"):
                    check(False, f"no error expected (got: {final['error']})")
                else:
                    check(True, "no error during generation")

            # --- Persistence ------------------------------------------------- #
            print("\nPersistence")
            history = (await client.get(f"/api/agents/{agent['id']}/messages")).json()
            roles = [message["role"] for message in history["messages"]]
            report("stored", f"{history['total']} messages ({roles})")
            check(roles == ["user", "assistant"], "both turns are stored in SQLite")
            check(
                history["messages"][-1]["content"] == text,
                "stored reply matches the streamed text",
            )

            agents = (await client.get("/api/agents")).json()["agents"]
            check(
                any(item["id"] == agent["id"] for item in agents),
                "agent appears in the sidebar listing",
            )
        finally:
            await client.delete(f"/api/agents/{agent['id']}")
            print("\ncleanup: test companion deleted")

    print(f"\n{'ALL CHECKS PASSED' if ok else 'SOME CHECKS FAILED'}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    raise SystemExit(asyncio.run(main(target)))
