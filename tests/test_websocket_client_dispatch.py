"""Dispatch tests for AvatarWebSocketClient._dispatch_text.

These tests exercise the text-frame dispatch table without opening a real
WebSocket — we instantiate the client, point it at a recording listener,
and feed JSON strings directly into the private _dispatch_text hook.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional, Tuple

import pytest

from liveavatar_channel_sdk.avatar_channel_listener_adapter import (
    AvatarChannelListenerAdapter,
)
from liveavatar_channel_sdk.avatar_websocket_client import AvatarWebSocketClient
from liveavatar_channel_sdk.event_type import EventType
from liveavatar_channel_sdk.message_builder import MessageBuilder


class RecordingListener(AvatarChannelListenerAdapter):
    """Listener that records every callback invocation for assertion."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, Tuple[Any, ...]]] = []

    async def on_session_init(self, session_id: str, user_id: str) -> None:
        self.calls.append(("on_session_init", (session_id, user_id)))

    async def on_session_closing(self, reason: Optional[str]) -> None:
        self.calls.append(("on_session_closing", (reason,)))

    async def on_scene_ready(self) -> None:
        self.calls.append(("on_scene_ready", ()))

    async def on_input_text(self, request_id: str, text: str) -> None:
        self.calls.append(("on_input_text", (request_id, text)))

    async def on_asr_partial(self, request_id: str, text: str, seq: int) -> None:
        self.calls.append(("on_asr_partial", (request_id, text, seq)))

    async def on_asr_final(self, request_id: str, text: str) -> None:
        self.calls.append(("on_asr_final", (request_id, text)))

    async def on_voice_start(self, request_id: str) -> None:
        self.calls.append(("on_voice_start", (request_id,)))

    async def on_voice_finish(self, request_id: str) -> None:
        self.calls.append(("on_voice_finish", (request_id,)))


def _make_client() -> Tuple[AvatarWebSocketClient, RecordingListener]:
    listener = RecordingListener()
    client = AvatarWebSocketClient("ws://dummy", listener)
    return client, listener


@pytest.mark.asyncio
async def test_dispatch_scene_ready_invokes_on_scene_ready():
    client, listener = _make_client()

    await client._dispatch_text(json.dumps(MessageBuilder.scene_ready()))

    assert listener.calls == [("on_scene_ready", ())]


@pytest.mark.asyncio
async def test_dispatch_session_closing_passes_reason():
    client, listener = _make_client()

    raw = json.dumps({"event": EventType.SESSION_CLOSING, "data": {"reason": "timeout"}})
    await client._dispatch_text(raw)

    assert listener.calls == [("on_session_closing", ("timeout",))]


@pytest.mark.asyncio
async def test_dispatch_session_closing_missing_reason():
    client, listener = _make_client()

    raw = json.dumps({"event": EventType.SESSION_CLOSING, "data": {}})
    await client._dispatch_text(raw)

    assert listener.calls == [("on_session_closing", (None,))]


@pytest.mark.asyncio
async def test_dispatch_unknown_event_does_not_raise():
    client, listener = _make_client()

    await client._dispatch_text(json.dumps({"event": "bogus.event"}))

    # No callback recorded and no exception propagated.
    assert listener.calls == []


# ----------------------------------------------------------------------
# Scenario 2B: developer sends input.voice.* / input.asr.* back to the
# platform. We assert both directions round-trip through the dispatcher.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_input_voice_start():
    client, listener = _make_client()

    await client._dispatch_text(json.dumps(MessageBuilder.input_voice_start("req-9")))

    assert listener.calls == [("on_voice_start", ("req-9",))]


@pytest.mark.asyncio
async def test_dispatch_input_voice_finish():
    client, listener = _make_client()

    await client._dispatch_text(json.dumps(MessageBuilder.input_voice_finish("req-9")))

    assert listener.calls == [("on_voice_finish", ("req-9",))]


@pytest.mark.asyncio
async def test_dispatch_input_asr_partial():
    client, listener = _make_client()

    await client._dispatch_text(json.dumps(MessageBuilder.input_asr_partial("req-9", "he", 3)))

    assert listener.calls == [("on_asr_partial", ("req-9", "he", 3))]


@pytest.mark.asyncio
async def test_dispatch_input_asr_final():
    client, listener = _make_client()

    await client._dispatch_text(json.dumps(MessageBuilder.input_asr_final("req-9", "hello")))

    assert listener.calls == [("on_asr_final", ("req-9", "hello"))]
