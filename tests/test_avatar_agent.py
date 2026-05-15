"""Tests for AvatarAgent send methods and lifecycle."""

from __future__ import annotations

import json
from typing import List

import httpx
import pytest

from liveavatar_channel_sdk.audio_frame import AudioFrame
from liveavatar_channel_sdk.avatar_agent import AvatarAgent, AgentListener, AvatarAgentConfig
from liveavatar_channel_sdk.event_type import EventType
from liveavatar_channel_sdk.session_models import SessionStartError, ErrorCode


class FakeWs:
    """Simulates _AvatarWsClient for unit testing send methods."""

    def __init__(self) -> None:
        self.json_messages: List[dict] = []
        self.binary_messages: List[bytes] = []

    async def send_json(self, message: dict) -> None:
        self.json_messages.append(message)

    async def send_binary(self, data: bytes) -> None:
        self.binary_messages.append(data)


@pytest.fixture
def agent() -> AvatarAgent:
    config = AvatarAgentConfig(api_key="sk-test", avatar_id="avatar-1")
    listener = AgentListener()
    return AvatarAgent(config, listener)


def _inject_ws(a: AvatarAgent, ws: FakeWs) -> FakeWs:
    a._ws_client = ws
    return ws


# -- Platform TTS -----------------------------------------------------------


@pytest.mark.asyncio
async def test_send_response_start(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_response_start("req-1", "resp-1", speed=1.5, volume=0.8, mood="happy")
    msg = ws.json_messages[0]
    assert msg["event"] == EventType.RESPONSE_START
    assert msg["requestId"] == "req-1"
    assert msg["responseId"] == "resp-1"
    assert msg["data"]["audioConfig"]["speed"] == 1.5
    assert msg["data"]["audioConfig"]["volume"] == 0.8
    assert msg["data"]["audioConfig"]["mood"] == "happy"


@pytest.mark.asyncio
async def test_send_response_start_defaults(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_response_start("req-1", "resp-1")
    msg = ws.json_messages[0]
    assert msg["data"]["audioConfig"]["speed"] == 1.0
    assert msg["data"]["audioConfig"]["volume"] == 1.0
    assert "mood" not in msg["data"]["audioConfig"]


@pytest.mark.asyncio
async def test_send_response_chunk(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_response_chunk("req-1", "resp-1", seq=3, timestamp=1000, text="hi")
    msg = ws.json_messages[0]
    assert msg["event"] == EventType.RESPONSE_CHUNK
    assert msg["seq"] == 3
    assert msg["data"]["text"] == "hi"


@pytest.mark.asyncio
async def test_send_response_done(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_response_done("req-1", "resp-1")
    assert ws.json_messages[0]["event"] == EventType.RESPONSE_DONE


@pytest.mark.asyncio
async def test_send_response_cancel(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_response_cancel("resp-1")
    assert ws.json_messages[0]["event"] == EventType.RESPONSE_CANCEL


# -- Developer TTS ----------------------------------------------------------


@pytest.mark.asyncio
async def test_send_response_audio_start(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_response_audio_start("req-1", "resp-1")
    msg = ws.json_messages[0]
    assert msg["event"] == EventType.RESPONSE_AUDIO_START
    assert msg["requestId"] == "req-1"
    assert msg["responseId"] == "resp-1"


@pytest.mark.asyncio
async def test_send_response_audio_finish(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_response_audio_finish("req-1", "resp-1")
    msg = ws.json_messages[0]
    assert msg["event"] == EventType.RESPONSE_AUDIO_FINISH


@pytest.mark.asyncio
async def test_send_audio_frame(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    frame = AudioFrame(payload=b"\x00" * 100)
    await agent.send_audio_frame(frame)
    assert len(ws.binary_messages) == 1


# -- Prompt audio -----------------------------------------------------------


@pytest.mark.asyncio
async def test_send_prompt_audio_start(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_prompt_audio_start()
    assert ws.json_messages[0]["event"] == EventType.RESPONSE_AUDIO_PROMPT_START


@pytest.mark.asyncio
async def test_send_prompt_audio_finish(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_prompt_audio_finish()
    assert ws.json_messages[0]["event"] == EventType.RESPONSE_AUDIO_PROMPT_FINISH


# -- Developer ASR ----------------------------------------------------------


@pytest.mark.asyncio
async def test_send_voice_start(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_voice_start("req-1")
    assert ws.json_messages[0]["event"] == EventType.INPUT_VOICE_START
    assert ws.json_messages[0]["requestId"] == "req-1"


@pytest.mark.asyncio
async def test_send_voice_finish(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_voice_finish("req-1")
    assert ws.json_messages[0]["event"] == EventType.INPUT_VOICE_FINISH


@pytest.mark.asyncio
async def test_send_asr_partial(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_asr_partial("req-1", "hel", 1)
    msg = ws.json_messages[0]
    assert msg["event"] == EventType.INPUT_ASR_PARTIAL
    assert msg["data"]["text"] == "hel"


@pytest.mark.asyncio
async def test_send_asr_final(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_asr_final("req-1", "hello")
    assert ws.json_messages[0]["event"] == EventType.INPUT_ASR_FINAL


# -- Control ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_interrupt_without_request_id(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_interrupt()
    assert ws.json_messages[0]["event"] == EventType.CONTROL_INTERRUPT
    assert "requestId" not in ws.json_messages[0]


@pytest.mark.asyncio
async def test_send_interrupt_with_request_id(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_interrupt(request_id="req-1")
    assert ws.json_messages[0]["requestId"] == "req-1"


# -- System -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_prompt(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_prompt("Are you still there?")
    msg = ws.json_messages[0]
    assert msg["event"] == EventType.SYSTEM_PROMPT
    assert msg["data"]["text"] == "Are you still there?"


# -- Error ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_error(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_error("ASR_FAIL", "audio decode error", request_id="req-1")
    msg = ws.json_messages[0]
    assert msg["event"] == EventType.ERROR
    assert msg["data"]["code"] == "ASR_FAIL"
    assert msg["data"]["message"] == "audio decode error"


@pytest.mark.asyncio
async def test_send_error_without_request_id(agent: AvatarAgent):
    ws = _inject_ws(agent, FakeWs())
    await agent.send_error("ERR", "msg")
    msg = ws.json_messages[0]
    assert "requestId" not in msg


# -- Listener defaults are no-ops ------------------------------------------


@pytest.mark.asyncio
async def test_agent_listener_defaults_are_noops():
    listener = AgentListener()
    await listener.on_text_input("hello", "req-1")
    await listener.on_session_init("sess-1", "user-1")
    await listener.on_session_state(None)
    await listener.on_session_closing("timeout")
    await listener.on_idle_trigger("user_idle", 120000)
    await listener.on_audio_frame(AudioFrame())
    await listener.on_error("ERR", "msg")
    await listener.on_closed(1000, "normal")


# -- Lifecycle: send before connect raises ----------------------------------


@pytest.mark.asyncio
async def test_send_before_start_raises():
    config = AvatarAgentConfig(api_key="sk-test", avatar_id="avatar-1")
    listener = AgentListener()
    agent = AvatarAgent(config, listener)
    with pytest.raises(RuntimeError, match="Not connected"):
        await agent.send_response_done("req-1", "resp-1")


# -- REST integration tests (pytest-httpx) ----------------------------------


@pytest.fixture
def agent_with_config() -> AvatarAgent:
    config = AvatarAgentConfig(
        api_key="sk-test",
        avatar_id="avatar-1",
        base_url="https://test.example.com",
    )
    listener = AgentListener()
    return AvatarAgent(config, listener)


@pytest.mark.asyncio
async def test_rest_start_success(agent_with_config: AvatarAgent, httpx_mock):
    httpx_mock.add_response(
        url="https://test.example.com/v1/session/start",
        method="POST",
        json={
            "code": 0,
            "message": "success",
            "data": {
                "sessionId": "sess-123",
                "sfuUrl": "wss://sfu.example.com",
                "userToken": "ut",
                "agentWsUrl": "wss://agent.example.com/ws",
            },
        },
    )

    agent_with_config._http_client = httpx.AsyncClient(
        base_url="https://test.example.com",
        headers={"Authorization": "Bearer sk-test"},
    )
    try:
        result = await agent_with_config._rest_start()
        assert result.session_id == "sess-123"
        assert result.agent_ws_url == "wss://agent.example.com/ws"
    finally:
        await agent_with_config._http_client.aclose()


@pytest.mark.asyncio
async def test_rest_start_error(agent_with_config: AvatarAgent, httpx_mock):
    httpx_mock.add_response(
        url="https://test.example.com/v1/session/start",
        method="POST",
        json={"code": 40005, "message": "Max concurrent sessions"},
    )

    agent_with_config._http_client = httpx.AsyncClient(
        base_url="https://test.example.com",
        headers={"Authorization": "Bearer sk-test"},
    )
    try:
        with pytest.raises(SessionStartError) as exc_info:
            await agent_with_config._rest_start()
        assert exc_info.value.error_code == ErrorCode.CONCURRENCY_LIMIT_EXCEEDED
    finally:
        await agent_with_config._http_client.aclose()


@pytest.mark.asyncio
async def test_rest_start_unknown_error(agent_with_config: AvatarAgent, httpx_mock):
    httpx_mock.add_response(
        url="https://test.example.com/v1/session/start",
        method="POST",
        json={"code": 40999, "message": "???"},
    )

    agent_with_config._http_client = httpx.AsyncClient(
        base_url="https://test.example.com",
        headers={"Authorization": "Bearer sk-test"},
    )
    try:
        with pytest.raises(SessionStartError) as exc_info:
            await agent_with_config._rest_start()
        assert exc_info.value.error_code == ErrorCode.SESSION_START_FAILED
    finally:
        await agent_with_config._http_client.aclose()


@pytest.mark.asyncio
async def test_rest_start_with_voice_id(agent_with_config: AvatarAgent, httpx_mock):
    agent_with_config._config.voice_id = "voice-42"
    body_capture = {}

    def capture_body(request):
        body_capture.update(json.loads(request.content))
        return httpx.Response(200, json={
            "code": 0, "message": "success",
            "data": {"sessionId": "s", "sfuUrl": "u", "userToken": "t"},
        })

    httpx_mock.add_callback(
        capture_body,
        url="https://test.example.com/v1/session/start",
        method="POST",
    )

    agent_with_config._http_client = httpx.AsyncClient(
        base_url="https://test.example.com",
        headers={"Authorization": "Bearer sk-test"},
    )
    try:
        await agent_with_config._rest_start()
        assert body_capture["voiceId"] == "voice-42"
    finally:
        await agent_with_config._http_client.aclose()


@pytest.mark.asyncio
async def test_rest_start_sandbox_header(httpx_mock):
    config = AvatarAgentConfig(
        api_key="sk-test",
        avatar_id="avatar-1",
        base_url="https://test.example.com",
        sandbox=True,
    )
    listener = AgentListener()
    agent = AvatarAgent(config, listener)

    headers_capture = {}

    def capture_headers(request):
        headers_capture.update(dict(request.headers))
        return httpx.Response(200, json={
            "code": 0, "message": "success",
            "data": {"sessionId": "s", "sfuUrl": "u", "userToken": "t"},
        })

    httpx_mock.add_callback(
        capture_headers,
        url="https://test.example.com/v1/session/start",
        method="POST",
    )

    agent._http_client = httpx.AsyncClient(
        base_url="https://test.example.com",
        headers={"Authorization": "Bearer sk-test", "X-Env-Sandbox": "true"},
    )
    try:
        await agent._rest_start()
        assert headers_capture["x-env-sandbox"] == "true"
    finally:
        await agent._http_client.aclose()
