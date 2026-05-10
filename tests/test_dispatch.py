"""Tests for the shared dispatch_text_event() function."""

from __future__ import annotations

import json
from typing import Any, List, Optional, Tuple

import pytest

from liveavatar_channel_sdk.avatar_channel_listener_adapter import AvatarChannelListenerAdapter
from liveavatar_channel_sdk.dispatch import dispatch_text_event
from liveavatar_channel_sdk.event_type import EventType
from liveavatar_channel_sdk.message_builder import MessageBuilder


class RecordingListener(AvatarChannelListenerAdapter):
    def __init__(self) -> None:
        self.calls: List[Tuple[str, Tuple[Any, ...]]] = []

    async def on_session_init(self, session_id: str, user_id: str) -> None:
        self.calls.append(("on_session_init", (session_id, user_id)))

    async def on_session_closing(self, reason: Optional[str]) -> None:
        self.calls.append(("on_session_closing", (reason,)))

    async def on_session_stop(self) -> None:
        self.calls.append(("on_session_stop", ()))

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

    async def on_chunk_received(self, request_id: str, response_id: str, seq: int, text: str) -> None:
        self.calls.append(("on_chunk_received", (request_id, response_id, seq, text)))

    async def on_response_done(self, request_id: str, response_id: str) -> None:
        self.calls.append(("on_response_done", (request_id, response_id)))

    async def on_error(self, request_id: Optional[str], code: str, message: str) -> None:
        self.calls.append(("on_error", (request_id, code, message)))


@pytest.mark.asyncio
async def test_dispatch_scene_ready():
    listener = RecordingListener()
    await dispatch_text_event(json.dumps(MessageBuilder.scene_ready()), listener)
    assert listener.calls == [("on_scene_ready", ())]


@pytest.mark.asyncio
async def test_dispatch_session_closing_passes_reason():
    listener = RecordingListener()
    raw = json.dumps({"event": EventType.SESSION_CLOSING, "data": {"reason": "timeout"}})
    await dispatch_text_event(raw, listener)
    assert listener.calls == [("on_session_closing", ("timeout",))]


@pytest.mark.asyncio
async def test_dispatch_session_closing_missing_reason():
    listener = RecordingListener()
    raw = json.dumps({"event": EventType.SESSION_CLOSING, "data": {}})
    await dispatch_text_event(raw, listener)
    assert listener.calls == [("on_session_closing", (None,))]


@pytest.mark.asyncio
async def test_dispatch_session_stop():
    listener = RecordingListener()
    await dispatch_text_event(json.dumps(MessageBuilder.session_stop()), listener)
    assert listener.calls == [("on_session_stop", ())]


@pytest.mark.asyncio
async def test_dispatch_unknown_event_does_not_raise():
    listener = RecordingListener()
    await dispatch_text_event(json.dumps({"event": "bogus.event"}), listener)
    assert listener.calls == []


@pytest.mark.asyncio
async def test_dispatch_input_voice_start():
    listener = RecordingListener()
    await dispatch_text_event(json.dumps(MessageBuilder.input_voice_start("req-9")), listener)
    assert listener.calls == [("on_voice_start", ("req-9",))]


@pytest.mark.asyncio
async def test_dispatch_input_voice_finish():
    listener = RecordingListener()
    await dispatch_text_event(json.dumps(MessageBuilder.input_voice_finish("req-9")), listener)
    assert listener.calls == [("on_voice_finish", ("req-9",))]


@pytest.mark.asyncio
async def test_dispatch_input_asr_partial():
    listener = RecordingListener()
    await dispatch_text_event(json.dumps(MessageBuilder.input_asr_partial("req-9", "he", 3)), listener)
    assert listener.calls == [("on_asr_partial", ("req-9", "he", 3))]


@pytest.mark.asyncio
async def test_dispatch_input_asr_final():
    listener = RecordingListener()
    await dispatch_text_event(json.dumps(MessageBuilder.input_asr_final("req-9", "hello")), listener)
    assert listener.calls == [("on_asr_final", ("req-9", "hello"))]


@pytest.mark.asyncio
async def test_dispatch_input_text():
    listener = RecordingListener()
    await dispatch_text_event(json.dumps(MessageBuilder.input_text("req-1", "hello")), listener)
    assert listener.calls == [("on_input_text", ("req-1", "hello"))]


@pytest.mark.asyncio
async def test_dispatch_response_chunk_direct_to_listener():
    """Without streaming handler, chunks go directly to the listener."""
    listener = RecordingListener()
    raw = json.dumps(MessageBuilder.response_chunk("req-1", "resp-1", seq=0, timestamp=100, text="hi"))
    await dispatch_text_event(raw, listener)
    assert listener.calls == [("on_chunk_received", ("req-1", "resp-1", 0, "hi"))]


@pytest.mark.asyncio
async def test_dispatch_response_done_direct_to_listener():
    listener = RecordingListener()
    raw = json.dumps(MessageBuilder.response_done("req-1", "resp-1"))
    await dispatch_text_event(raw, listener)
    assert listener.calls == [("on_response_done", ("req-1", "resp-1"))]
