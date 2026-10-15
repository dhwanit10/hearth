"""LLM access layer.

Two interchangeable engines behind one async generator interface:

* :class:`GeminiClient` - real replies from the Gemini API using the REST
  ``streamGenerateContent`` endpoint with ``alt=sse``.
* :class:`DemoEngine` - an offline, in-character responder used when no API key
  is configured, so the whole app (websocket protocol, streaming, persistence)
  is demonstrable with zero setup.

Both yield plain text chunks. Nothing in here knows about databases or
websockets, which keeps it trivially testable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import AsyncIterator, Iterable, Sequence

import httpx

from .config import settings

logger = logging.getLogger("hearth.llm")

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent"
)

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
]

VALID_THINKING_LEVELS = {"minimal", "low", "medium", "high"}


class LLMError(RuntimeError):
    """Raised when the provider cannot produce a reply."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# --------------------------------------------------------------------------- #
# Gemini
# --------------------------------------------------------------------------- #


class GeminiClient:
    """Thin, dependency-light Gemini streaming client over httpx."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.8-flash",
        *,
        thinking_level: str = "",
        max_output_tokens: int = 1024,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.thinking_level = (thinking_level or "").lower()
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout

    # -- payload shaping ---------------------------------------------------- #

    def _payload(
        self,
        system_prompt: str,
        history: Sequence[tuple[str, str]],
        temperature: float,
        *,
        include_thinking: bool,
    ) -> dict:
        contents = [
            {
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": text}],
            }
            for role, text in history
            if text and text.strip()
        ]
        generation_config: dict = {
            "temperature": round(float(temperature), 2),
            "topP": 0.95,
            "maxOutputTokens": self.max_output_tokens,
        }
        if include_thinking and self.thinking_level in VALID_THINKING_LEVELS:
            generation_config["thinkingConfig"] = {
                "thinkingLevel": self.thinking_level.upper()
            }

        return {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": generation_config,
            "safetySettings": SAFETY_SETTINGS,
        }

    # -- streaming ---------------------------------------------------------- #

    async def _stream_once(
        self,
        payload: dict,
    ) -> AsyncIterator[str]:
        url = GEMINI_ENDPOINT.format(model=self.model)
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(self.timeout, connect=15.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", url, headers=headers, json=payload,
                params={"alt": "sse"},
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise LLMError(
                        self._describe_error(response.status_code, body),
                        status_code=response.status_code,
                    )

                blocked: str | None = None
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if not chunk or chunk == "[DONE]":
                        continue
                    try:
                        event = json.loads(chunk)
                    except json.JSONDecodeError:
                        logger.debug("Skipping malformed SSE chunk: %.120s", chunk)
                        continue

                    feedback = event.get("promptFeedback") or {}
                    if feedback.get("blockReason"):
                        blocked = feedback["blockReason"]
                        break

                    for candidate in event.get("candidates") or []:
                        finish = candidate.get("finishReason")
                        if finish in {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"}:
                            blocked = finish
                        for part in (candidate.get("content") or {}).get("parts") or []:
                            # Gemini 3 emits internal reasoning as thought parts.
                            if part.get("thought"):
                                continue
                            text = part.get("text")
                            if text:
                                yield text

                if blocked:
                    raise LLMError(
                        "The model declined to answer that one "
                        f"({blocked}). Try rephrasing it."
                    )

    async def stream_reply(
        self,
        *,
        system_prompt: str,
        history: Sequence[tuple[str, str]],
        temperature: float = 0.9,
    ) -> AsyncIterator[str]:
        """Yield reply chunks. Falls back once if thinking config is rejected."""
        wants_thinking = self.thinking_level in VALID_THINKING_LEVELS
        payload = self._payload(
            system_prompt, history, temperature, include_thinking=wants_thinking
        )
        produced = False
        try:
            async for piece in self._stream_once(payload):
                produced = True
                yield piece
            return
        except LLMError as exc:
            # Some models / API versions reject thinkingConfig with a 400. As
            # long as nothing was streamed yet, retry once without it instead of
            # failing the whole conversation.
            if produced or exc.status_code != 400 or not wants_thinking:
                raise
            logger.warning(
                "Model %s rejected thinkingConfig, retrying without it.", self.model
            )

        plain_payload = self._payload(
            system_prompt, history, temperature, include_thinking=False
        )
        async for piece in self._stream_once(plain_payload):
            yield piece

    @staticmethod
    def _describe_error(status_code: int, body: str) -> str:
        detail = ""
        try:
            parsed = json.loads(body)
            detail = (parsed.get("error") or {}).get("message", "") or ""
        except json.JSONDecodeError:
            detail = body.strip()[:300]

        if status_code in (401, 403):
            hint = "The Gemini API key was rejected. Check GEMINI_API_KEY in backend/.env."
        elif status_code == 404:
            hint = (
                f"The model does not exist for this API version. Check GEMINI_MODEL "
                f"(currently '{settings.gemini_model}')."
            )
        elif status_code == 429:
            hint = "Gemini rate limit hit. Wait a moment and send again."
        elif status_code >= 500:
            hint = "Gemini is having a moment upstream. Try again shortly."
        else:
            hint = "Gemini rejected the request."
        return f"{hint} {detail}".strip()


# --------------------------------------------------------------------------- #
# Offline demo engine
# --------------------------------------------------------------------------- #

_DEMO_LINES: dict[str, tuple[str, ...]] = {
    "best_friend": (
        "Oh, you are back. I had already started writing your eulogy, "
        "figure of speech, of course. So what disaster are we fixing today?",
        "Let me guess: you have thought about this for three days and done "
        "absolutely nothing. Classic. Tell me the actual problem.",
        "You want my honest opinion or the version where I pretend you are "
        "a genius? Because I only have one setting and it is this one.",
    ),
    "girlfriend": (
        "There you are. I was starting to think your phone got eaten by the "
        "couch. Tell me about your day, the whole thing, I have time.",
        "You sound tired. Come here, put your head down and tell me what "
        "happened. I am not going anywhere.",
        "I have been thinking about you, which is inconvenient because I had "
        "plans. Anyway. Hi. How are you, honestly?",
    ),
    "teacher": (
        "Good, let's take this one step at a time. First tell me what you "
        "already understand, so I start in the right place.",
        "That is a fair question and a very common confusion. Let me give you "
        "one clear example before we touch the theory.",
        "Before I explain, try saying it back to me in your own words, even "
        "roughly. That tells me exactly where the gap is.",
    ),
    "mentor": (
        "Let's not start with the solution. What outcome do you actually want "
        "in ninety days? Be specific, vague goals are why people stall.",
        "I hear the symptom. What is the decision sitting underneath it? Name "
        "that and the rest gets much simpler.",
        "Here is my read, and you may not like it. Tell me the one thing you "
        "have been avoiding, and we will start there.",
    ),
    "custom": (
        "Right, I'm here. Say what's on your mind and I'll answer in the voice "
        "you asked for.",
        "Consider me briefed and ready. Go ahead, what are we talking about?",
        "I read your brief. I like it. Now tell me something real.",
    ),
}

_DEMO_NOTICE = (
    "Demo mode: no GEMINI_API_KEY configured, so this reply came from the "
    "offline engine."
)


class DemoEngine:
    """Deterministic-ish placeholder that still streams like the real thing."""

    def __init__(self, chunk_delay: float = 0.028) -> None:
        self.chunk_delay = chunk_delay

    async def stream_reply(
        self,
        *,
        system_prompt: str,
        history: Sequence[tuple[str, str]],
        temperature: float = 0.9,
        persona: str = "best_friend",
    ) -> AsyncIterator[str]:
        lines = _DEMO_LINES.get(persona, _DEMO_LINES["custom"])
        reply = random.choice(lines)

        for word in _split_for_stream(reply):
            await asyncio.sleep(self.chunk_delay)
            yield word


def _split_for_stream(text: str) -> Iterable[str]:
    """Yield whitespace preserving word chunks so the UI looks like a stream."""
    words = text.split(" ")
    for index, word in enumerate(words):
        yield word if index == 0 else " " + word


# --------------------------------------------------------------------------- #
# Engine selection
# --------------------------------------------------------------------------- #

_demo_engine = DemoEngine()


def get_engine():
    """Return the configured engine. Real Gemini wins when a key exists."""
    if settings.llm_configured:
        return GeminiClient(
            settings.gemini_api_key,
            settings.gemini_model,
            thinking_level=settings.gemini_thinking_level,
            max_output_tokens=settings.gemini_max_output_tokens,
        )
    return _demo_engine


def llm_status() -> dict:
    """Small description of the active engine, surfaced at /api/health."""
    if settings.llm_configured:
        return {
            "mode": "gemini",
            "configured": True,
            "model": settings.gemini_model,
            "thinkingLevel": settings.gemini_thinking_level or "default",
            "notice": None,
        }
    return {
        "mode": "demo",
        "configured": False,
        "model": "offline-demo-engine",
        "thinkingLevel": None,
        "notice": _DEMO_NOTICE,
    }


async def stream_reply(
    *,
    system_prompt: str,
    history: Sequence[tuple[str, str]],
    temperature: float,
    persona: str,
) -> AsyncIterator[str]:
    """Single entry point used by the websocket layer."""
    engine = get_engine()
    if isinstance(engine, DemoEngine):
        async for piece in engine.stream_reply(
            system_prompt=system_prompt,
            history=history,
            temperature=temperature,
            persona=persona,
        ):
            yield piece
        return

    async for piece in engine.stream_reply(
        system_prompt=system_prompt,
        history=history,
        temperature=temperature,
    ):
        yield piece
