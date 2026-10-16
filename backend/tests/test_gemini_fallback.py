"""Unit tests for Gemini primary -> fallback model routing (no network).

These exercise the real :class:`app.gemini.GeminiClient` with its HTTP layer
stubbed out, so the retry decision logic is tested in isolation from the
offline fake the end-to-end suite swaps in.
"""

from __future__ import annotations

import asyncio

import pytest

from app.gemini import GeminiClient, LLMError


def _collect(agen) -> list[str]:
    async def run() -> list[str]:
        return [piece async for piece in agen]

    return asyncio.run(run())


def test_models_skips_an_identical_or_empty_fallback():
    assert GeminiClient("k", "same", fallback_model="same")._models() == ["same"]
    assert GeminiClient("k", "same", fallback_model="")._models() == ["same"]
    assert GeminiClient("k", "same", fallback_model=" other ")._models() == [
        "same",
        "other",
    ]


def test_falls_back_when_the_primary_model_is_unavailable(monkeypatch):
    client = GeminiClient("k", "primary", fallback_model="backup")
    calls: list[str] = []

    async def fake_stream_once(model, payload):
        calls.append(model)
        if model == "primary":
            raise LLMError("model not found", status_code=404)
        for piece in ("from ", "backup"):
            yield piece

    monkeypatch.setattr(client, "_stream_once", fake_stream_once)
    pieces = _collect(
        client.stream_reply(system_prompt="sys", history=[("user", "hi")])
    )
    assert calls == ["primary", "backup"]
    assert "".join(pieces) == "from backup"


def test_primary_success_never_touches_the_fallback(monkeypatch):
    client = GeminiClient("k", "primary", fallback_model="backup")
    calls: list[str] = []

    async def fake_stream_once(model, payload):
        calls.append(model)
        yield "hello"

    monkeypatch.setattr(client, "_stream_once", fake_stream_once)
    pieces = _collect(
        client.stream_reply(system_prompt="sys", history=[("user", "hi")])
    )
    assert calls == ["primary"]
    assert "".join(pieces) == "hello"


def test_a_rejected_key_is_not_retried_on_the_fallback(monkeypatch):
    client = GeminiClient("k", "primary", fallback_model="backup")
    calls: list[str] = []

    async def fake_stream_once(model, payload):
        calls.append(model)
        raise LLMError("key rejected", status_code=403)
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(client, "_stream_once", fake_stream_once)
    with pytest.raises(LLMError):
        _collect(client.stream_reply(system_prompt="sys", history=[("user", "hi")]))
    assert calls == ["primary"]


def test_a_declined_reply_is_not_retried_on_the_fallback(monkeypatch):
    # SAFETY/PROHIBITED_CONTENT failures carry no status code, so they must not
    # be replayed against another model.
    client = GeminiClient("k", "primary", fallback_model="backup")
    calls: list[str] = []

    async def fake_stream_once(model, payload):
        calls.append(model)
        raise LLMError("The model declined to answer that one")
        yield  # pragma: no cover

    monkeypatch.setattr(client, "_stream_once", fake_stream_once)
    with pytest.raises(LLMError):
        _collect(client.stream_reply(system_prompt="sys", history=[("user", "hi")]))
    assert calls == ["primary"]


def test_a_partial_reply_is_not_retried_on_the_fallback(monkeypatch):
    client = GeminiClient("k", "primary", fallback_model="backup")
    calls: list[str] = []
    pieces: list[str] = []

    async def fake_stream_once(model, payload):
        calls.append(model)
        yield "partial "
        raise LLMError("upstream died", status_code=503)

    monkeypatch.setattr(client, "_stream_once", fake_stream_once)

    async def run():
        async for piece in client.stream_reply(
            system_prompt="sys", history=[("user", "hi")]
        ):
            pieces.append(piece)

    with pytest.raises(LLMError):
        asyncio.run(run())
    assert calls == ["primary"]
    assert "".join(pieces) == "partial "


def test_missing_fallback_model_disables_the_fallback(monkeypatch):
    client = GeminiClient("k", "primary", fallback_model="")
    calls: list[str] = []

    async def fake_stream_once(model, payload):
        calls.append(model)
        raise LLMError("model not found", status_code=404)
        yield  # pragma: no cover

    monkeypatch.setattr(client, "_stream_once", fake_stream_once)
    with pytest.raises(LLMError):
        _collect(client.stream_reply(system_prompt="sys", history=[("user", "hi")]))
    assert calls == ["primary"]
