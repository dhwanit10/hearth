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
        fallback_model: str = "",
        thinking_level: str = "",
        max_output_tokens: int = 1024,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.fallback_model = (fallback_model or "").strip()
        self.thinking_level = (thinking_level or "").lower()
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout

    def _models(self) -> list[str]:
        """The primary model, then the fallback if one is configured."""
        models = [self.model]
        if self.fallback_model and self.fallback_model != self.model:
            models.append(self.fallback_model)
        return models

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
        model: str,
        payload: dict,
    ) -> AsyncIterator[str]:
        url = GEMINI_ENDPOINT.format(model=model)
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
                        self._describe_error(response.status_code, body, model),
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

    async def _stream_model(
        self,
        model: str,
        *,
        system_prompt: str,
        history: Sequence[tuple[str, str]],
        temperature: float,
    ) -> AsyncIterator[str]:
        """Stream from a single model. Retries once without thinkingConfig on 400."""
        wants_thinking = self.thinking_level in VALID_THINKING_LEVELS
        payload = self._payload(
            system_prompt, history, temperature, include_thinking=wants_thinking
        )
        produced = False
        try:
            async for piece in self._stream_once(model, payload):
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
                "Model %s rejected thinkingConfig, retrying without it.", model
            )

        plain_payload = self._payload(
            system_prompt, history, temperature, include_thinking=False
        )
        async for piece in self._stream_once(model, plain_payload):
            yield piece

    @staticmethod
    def _is_fallback_worthy(exc: LLMError) -> bool:
        """Whether another model could plausibly do better.

        Model-specific and transient provider failures (unknown model, bad
        request, rate limit, upstream 5xx) are worth retrying on the fallback.
        A rejected key, or a reply the model declined to produce, is not.
        """
        code = exc.status_code
        return code is not None and (code in (400, 404, 429) or code >= 500)

    async def stream_reply(
        self,
        *,
        system_prompt: str,
        history: Sequence[tuple[str, str]],
        temperature: float = 0.9,
    ) -> AsyncIterator[str]:
        """Yield reply chunks, falling back to the secondary model on failure.

        The primary model is tried first; if it fails before emitting anything and
        the error looks model-specific or transient, the fallback model is tried
        once. Content that streams before a failure is never discarded.
        """
        models = self._models()
        for index, model in enumerate(models):
            produced = False
            try:
                async for piece in self._stream_model(
                    model,
                    system_prompt=system_prompt,
                    history=history,
                    temperature=temperature,
                ):
                    produced = True
                    yield piece
                return
            except LLMError as exc:
                is_last = index == len(models) - 1
                if produced or is_last or not self._is_fallback_worthy(exc):
                    raise
                logger.warning(
                    "Model %s failed (%s); falling back to %s.",
                    model,
                    exc.message,
                    models[index + 1],
                )

    @staticmethod
    def _describe_error(status_code: int, body: str, model: str) -> str:
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
                f"The model '{model}' does not exist for this API version. Check "
                f"GEMINI_MODEL / GEMINI_FALLBACK_MODEL."
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


def get_engine(api_key: str | None = None):
    """Return the engine for one request.

    A user-supplied (BYOK) key wins; otherwise the platform ``GEMINI_API_KEY``
    is used; with neither, replies come from the offline demo engine.
    """
    key = (api_key or "").strip() or settings.gemini_api_key
    if key:
        return GeminiClient(
            key,
            settings.gemini_model,
            fallback_model=settings.gemini_fallback_model,
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
            "platformKey": True,
            "model": settings.gemini_model,
            "fallbackModel": settings.gemini_fallback_model or None,
            "thinkingLevel": settings.gemini_thinking_level or "default",
            "notice": None,
        }
    return {
        "mode": "demo",
        "configured": False,
        "platformKey": False,
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
    api_key: str | None = None,
) -> AsyncIterator[str]:
    """Single entry point used by the websocket layer.

    ``api_key`` is the user's own Gemini key when they have supplied one; it
    takes precedence over the platform key.
    """
    engine = get_engine(api_key)
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
