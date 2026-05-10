"""Tests for SessionClient using pytest-httpx."""

from __future__ import annotations

import json

import httpx
import pytest

from liveavatar_channel_sdk.session_client import SessionClient
from liveavatar_channel_sdk.session_models import ErrorCode, SessionStartError, SessionStartResult


@pytest.fixture
def client() -> SessionClient:
    return SessionClient(api_key="sk-test", base_url="https://test.example.com")


@pytest.mark.asyncio
async def test_start_success(client: SessionClient, httpx_mock):
    httpx_mock.add_response(
        url="https://test.example.com/v1/session/start",
        method="POST",
        json={
            "code": 0,
            "message": "success",
            "data": {
                "sessionId": "sess-123",
                "sfuUrl": "wss://sfu.example.com",
                "userToken": "user-token-123",
                "agentWsUrl": "wss://agent.example.com/ws?token=abc",
            },
        },
    )

    result = await client.start(avatar_id="avatar-1")

    assert isinstance(result, SessionStartResult)
    assert result.session_id == "sess-123"
    assert result.sfu_url == "wss://sfu.example.com"
    assert result.user_token == "user-token-123"
    assert result.agent_ws_url == "wss://agent.example.com/ws?token=abc"
    assert result.agent_token is None


@pytest.mark.asyncio
async def test_start_with_voice_id(client: SessionClient, httpx_mock):
    body_capture = {}

    def capture_body(request):
        body_capture.update(json.loads(request.content))
        return httpx.Response(200, json={
            "code": 0, "message": "success",
            "data": {"sessionId": "s", "sfuUrl": "u", "userToken": "t"},
        })

    httpx_mock.add_callback(capture_body, url="https://test.example.com/v1/session/start", method="POST")

    await client.start(avatar_id="avatar-1", voice_id="voice-42")
    assert body_capture["voiceId"] == "voice-42"


@pytest.mark.asyncio
async def test_start_reconnect_with_session_id(client: SessionClient, httpx_mock):
    body_capture = {}

    def capture_body(request):
        body_capture.update(json.loads(request.content))
        return httpx.Response(200, json={
            "code": 0, "message": "success",
            "data": {"sessionId": "sess-old", "sfuUrl": "u2", "userToken": "t2"},
        })

    httpx_mock.add_callback(capture_body, url="https://test.example.com/v1/session/start", method="POST")

    await client.start(avatar_id="avatar-1", session_id="sess-old")
    assert body_capture["sessionId"] == "sess-old"


@pytest.mark.asyncio
async def test_start_with_platform_error(client: SessionClient, httpx_mock):
    httpx_mock.add_response(
        url="https://test.example.com/v1/session/start",
        method="POST",
        json={"code": 40005, "message": "Max concurrent sessions reached"},
    )

    with pytest.raises(SessionStartError) as exc_info:
        await client.start(avatar_id="avatar-1")

    assert exc_info.value.error_code == ErrorCode.CONCURRENCY_LIMIT_EXCEEDED
    assert exc_info.value.code == 40005


@pytest.mark.asyncio
async def test_start_unknown_error_code_maps_to_default(client: SessionClient, httpx_mock):
    httpx_mock.add_response(
        url="https://test.example.com/v1/session/start",
        method="POST",
        json={"code": 40999, "message": "Something went wrong"},
    )

    with pytest.raises(SessionStartError) as exc_info:
        await client.start(avatar_id="avatar-1")

    assert exc_info.value.error_code == ErrorCode.SESSION_START_FAILED


@pytest.mark.asyncio
async def test_stop_success(client: SessionClient, httpx_mock):
    httpx_mock.add_response(
        url="https://test.example.com/v1/session/stop",
        method="POST",
        json={"code": 0, "message": "success"},
    )

    await client.stop(session_id="sess-123")
    # No exception means success


@pytest.mark.asyncio
async def test_sandbox_header(client: SessionClient, httpx_mock):
    sandbox_client = SessionClient(
        api_key="sk-test",
        base_url="https://test.example.com",
        sandbox=True,
    )

    headers_capture = {}

    def capture_headers(request):
        headers_capture.update(dict(request.headers))
        return httpx.Response(200, json={
            "code": 0, "message": "success",
            "data": {"sessionId": "s", "sfuUrl": "u", "userToken": "t"},
        })

    httpx_mock.add_callback(capture_headers, url="https://test.example.com/v1/session/start", method="POST")

    await sandbox_client.start(avatar_id="avatar-1")
    assert headers_capture["x-env-sandbox"] == "true"


@pytest.mark.asyncio
async def test_start_with_platform_rtc_agent_token(client: SessionClient, httpx_mock):
    httpx_mock.add_response(
        url="https://test.example.com/v1/session/start",
        method="POST",
        json={
            "code": 0, "message": "success",
            "data": {
                "sessionId": "sess-1",
                "sfuUrl": "wss://sfu.example.com",
                "userToken": "ut",
                "agentToken": "at",
            },
        },
    )

    result = await client.start(avatar_id="avatar-1")
    assert result.agent_token == "at"
    assert result.agent_ws_url is None


@pytest.mark.asyncio
async def test_close(client: SessionClient):
    await client.close()
    assert client._client.is_closed
