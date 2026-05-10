"""Tests for MessageSender mixin via a concrete stub."""

from __future__ import annotations

from typing import List

import pytest

from liveavatar_channel_sdk.audio_frame import AudioFrame
from liveavatar_channel_sdk.event_type import EventType
from liveavatar_channel_sdk.image_frame import ImageFrame
from liveavatar_channel_sdk.message_sender import MessageSender


class StubSender(MessageSender):
    """Concrete sender that records all sent messages."""

    def __init__(self) -> None:
        self.sent_json: List[dict] = []
        self.sent_binary: List[bytes] = []

    async def send_json(self, message: dict) -> None:
        self.sent_json.append(message)

    async def send_binary(self, data: bytes) -> None:
        self.sent_binary.append(data)


@pytest.fixture
def sender() -> StubSender:
    return StubSender()


@pytest.mark.asyncio
async def test_send_session_ready(sender: StubSender):
    await sender.send_session_ready()
    assert sender.sent_json[0]["event"] == EventType.SESSION_READY


@pytest.mark.asyncio
async def test_send_session_stop(sender: StubSender):
    await sender.send_session_stop()
    assert sender.sent_json[0]["event"] == EventType.SESSION_STOP


@pytest.mark.asyncio
async def test_send_session_closing_with_reason(sender: StubSender):
    await sender.send_session_closing("timeout")
    assert sender.sent_json[0]["event"] == EventType.SESSION_CLOSING
    assert sender.sent_json[0]["data"]["reason"] == "timeout"


@pytest.mark.asyncio
async def test_send_session_closing_without_reason(sender: StubSender):
    await sender.send_session_closing()
    assert sender.sent_json[0]["event"] == EventType.SESSION_CLOSING


@pytest.mark.asyncio
async def test_send_input_voice_start(sender: StubSender):
    await sender.send_input_voice_start("req-1")
    assert sender.sent_json[0]["event"] == EventType.INPUT_VOICE_START
    assert sender.sent_json[0]["requestId"] == "req-1"


@pytest.mark.asyncio
async def test_send_input_voice_finish(sender: StubSender):
    await sender.send_input_voice_finish("req-1")
    assert sender.sent_json[0]["event"] == EventType.INPUT_VOICE_FINISH


@pytest.mark.asyncio
async def test_send_input_asr_partial(sender: StubSender):
    await sender.send_input_asr_partial("req-1", "hel", 1)
    assert sender.sent_json[0]["event"] == EventType.INPUT_ASR_PARTIAL
    assert sender.sent_json[0]["data"]["text"] == "hel"


@pytest.mark.asyncio
async def test_send_input_asr_final(sender: StubSender):
    await sender.send_input_asr_final("req-1", "hello")
    assert sender.sent_json[0]["event"] == EventType.INPUT_ASR_FINAL


@pytest.mark.asyncio
async def test_send_response_start(sender: StubSender):
    await sender.send_response_start("req-1", "resp-1", speed=1.5, volume=0.8, mood="happy")
    assert sender.sent_json[0]["event"] == EventType.RESPONSE_START
    assert sender.sent_json[0]["requestId"] == "req-1"
    assert sender.sent_json[0]["responseId"] == "resp-1"


@pytest.mark.asyncio
async def test_send_response_chunk(sender: StubSender):
    await sender.send_response_chunk("req-1", "resp-1", seq=3, timestamp=1000, text="hi")
    assert sender.sent_json[0]["event"] == EventType.RESPONSE_CHUNK
    assert sender.sent_json[0]["seq"] == 3


@pytest.mark.asyncio
async def test_send_response_done(sender: StubSender):
    await sender.send_response_done("req-1", "resp-1")
    assert sender.sent_json[0]["event"] == EventType.RESPONSE_DONE


@pytest.mark.asyncio
async def test_send_response_cancel(sender: StubSender):
    await sender.send_response_cancel("resp-1")
    assert sender.sent_json[0]["event"] == EventType.RESPONSE_CANCEL


@pytest.mark.asyncio
async def test_send_control_interrupt_without_request_id(sender: StubSender):
    await sender.send_control_interrupt()
    assert sender.sent_json[0]["event"] == EventType.CONTROL_INTERRUPT


@pytest.mark.asyncio
async def test_send_control_interrupt_with_request_id(sender: StubSender):
    await sender.send_control_interrupt(request_id="req-1")
    assert sender.sent_json[0]["requestId"] == "req-1"


@pytest.mark.asyncio
async def test_send_system_prompt(sender: StubSender):
    await sender.send_system_prompt("hello")
    assert sender.sent_json[0]["event"] == EventType.SYSTEM_PROMPT
    assert sender.sent_json[0]["data"]["text"] == "hello"


@pytest.mark.asyncio
async def test_send_error(sender: StubSender):
    await sender.send_error("ERR", "msg", request_id="req-1")
    assert sender.sent_json[0]["event"] == EventType.ERROR
    assert sender.sent_json[0]["data"]["code"] == "ERR"


@pytest.mark.asyncio
async def test_send_audio_frame(sender: StubSender):
    frame = AudioFrame(payload=b"test-audio")
    await sender.send_audio_frame(frame)
    assert len(sender.sent_binary) == 1
    assert sender.sent_binary[0][-10:] == b"test-audio"


@pytest.mark.asyncio
async def test_send_image_frame(sender: StubSender):
    frame = ImageFrame(payload=b"test-img")
    await sender.send_image_frame(frame)
    assert len(sender.sent_binary) == 1
    assert sender.sent_binary[0][-8:] == b"test-img"
