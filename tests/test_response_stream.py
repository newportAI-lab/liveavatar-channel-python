"""Tests for response stream lifecycle coordination."""

from __future__ import annotations

import asyncio

import pytest

from liveavatar_channel_sdk.avatar_agent import (
    AgentListener,
    AvatarAgent,
    AvatarAgentConfig,
)
from liveavatar_channel_sdk.event_type import EventType
from liveavatar_channel_sdk.response_stream import ResponseStreamStateError


class RecordingWs:
    def __init__(self) -> None:
        self.messages = []

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)


class FailingWs(RecordingWs):
    def __init__(self, fail_on: int) -> None:
        super().__init__()
        self.fail_on = fail_on
        self.send_count = 0

    async def send_json(self, message: dict) -> None:
        self.send_count += 1
        if self.send_count == self.fail_on:
            raise OSError("selected send failure")
        await super().send_json(message)


@pytest.fixture
def agent() -> AvatarAgent:
    return AvatarAgent(
        AvatarAgentConfig(api_key="sk-test", avatar_id="avatar-1"),
        AgentListener(),
    )


@pytest.mark.asyncio
async def test_legacy_chunks_and_done_reuse_first_response_id(agent: AvatarAgent):
    ws = RecordingWs()
    agent._ws_client = ws

    await agent.send_response_chunk("req-1", "resp-a", 0, 1000, "first")
    with pytest.warns(DeprecationWarning, match="resp-b"):
        await agent.send_response_chunk("req-1", "resp-b", 1, 1001, "second")
    with pytest.warns(DeprecationWarning, match="resp-c"):
        await agent.send_response_done("req-1", "resp-c")

    assert [message["responseId"] for message in ws.messages] == [
        "resp-a",
        "resp-a",
        "resp-a",
    ]
    assert [message["event"] for message in ws.messages] == [
        EventType.RESPONSE_CHUNK,
        EventType.RESPONSE_CHUNK,
        EventType.RESPONSE_DONE,
    ]


@pytest.mark.asyncio
async def test_legacy_start_chunks_and_done_keep_one_response_id(agent: AvatarAgent):
    ws = RecordingWs()
    agent._ws_client = ws

    await agent.send_response_start("req-1", "resp-1")
    await agent.send_response_chunk("req-1", "resp-1", 0, 1000, "first")
    await agent.send_response_chunk("req-1", "resp-1", 1, 1001, "second")
    await agent.send_response_done("req-1", "resp-1")

    assert [message["responseId"] for message in ws.messages] == ["resp-1"] * 4
    assert [message["event"] for message in ws.messages] == [
        EventType.RESPONSE_START,
        EventType.RESPONSE_CHUNK,
        EventType.RESPONSE_CHUNK,
        EventType.RESPONSE_DONE,
    ]


@pytest.mark.asyncio
async def test_legacy_chunks_without_start_do_not_synthesize_start(agent: AvatarAgent):
    ws = RecordingWs()
    agent._ws_client = ws

    await agent.send_response_chunk("req-1", "resp-1", 0, 1000, "first")
    await agent.send_response_done("req-1", "resp-1")

    assert [message["event"] for message in ws.messages] == [
        EventType.RESPONSE_CHUNK,
        EventType.RESPONSE_DONE,
    ]


@pytest.mark.asyncio
async def test_request_mismatch_with_nonzero_first_sequence_is_rejected(agent: AvatarAgent):
    ws = RecordingWs()
    agent._ws_client = ws
    await agent.send_response_chunk("req-1", "resp-1", 0, 1000, "first")

    with pytest.raises(ResponseStreamStateError, match="request"):
        await agent.send_response_chunk("req-2", "resp-2", 1, 1001, "wrong turn")

    assert len(ws.messages) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("seq", [0, -1, 2], ids=["duplicate", "decreasing", "skipped"])
async def test_sequence_mismatch_is_rejected(agent: AvatarAgent, seq: int):
    ws = RecordingWs()
    agent._ws_client = ws
    await agent.send_response_chunk("req-1", "resp-1", 0, 1000, "first")

    with pytest.raises(ResponseStreamStateError, match="expected seq 1"):
        await agent.send_response_chunk("req-1", "resp-1", seq, 1001, "invalid")

    assert len(ws.messages) == 1


@pytest.mark.asyncio
async def test_duplicate_start_for_one_request_is_rejected(agent: AvatarAgent):
    ws = RecordingWs()
    agent._ws_client = ws
    await agent.send_response_start("req-1", "resp-1")

    with pytest.raises(ResponseStreamStateError, match="start"):
        await agent.send_response_start("req-1", "resp-2")

    assert len(ws.messages) == 1


@pytest.mark.asyncio
async def test_different_requests_may_be_active_simultaneously(agent: AvatarAgent):
    ws = RecordingWs()
    agent._ws_client = ws

    await agent.send_response_chunk("req-1", "resp-1", 0, 1000, "one")
    await agent.send_response_chunk("req-2", "resp-2", 0, 1001, "two")
    await agent.send_response_done("req-2", "resp-2")
    await agent.send_response_done("req-1", "resp-1")

    assert [(message.get("requestId"), message["event"]) for message in ws.messages] == [
        ("req-1", EventType.RESPONSE_CHUNK),
        ("req-2", EventType.RESPONSE_CHUNK),
        ("req-2", EventType.RESPONSE_DONE),
        ("req-1", EventType.RESPONSE_DONE),
    ]


@pytest.mark.asyncio
async def test_done_without_active_request_is_rejected_without_affecting_other_request(
    agent: AvatarAgent,
):
    ws = RecordingWs()
    agent._ws_client = ws
    await agent.send_response_chunk("req-1", "resp-1", 0, 1000, "first")

    with pytest.raises(ResponseStreamStateError, match="done") as error:
        await agent.send_response_done("req-2", "resp-1")

    assert "request_id='req-2'" in str(error.value)
    assert "response_id='resp-1'" in str(error.value)
    await agent.send_response_done("req-1", "resp-1")
    assert [message["requestId"] for message in ws.messages] == ["req-1", "req-1"]


@pytest.mark.asyncio
async def test_cancel_without_active_response_id_is_rejected(agent: AvatarAgent):
    ws = RecordingWs()
    agent._ws_client = ws
    await agent.send_response_chunk("req-1", "resp-1", 0, 1000, "first")

    with pytest.raises(ResponseStreamStateError, match="cancel"):
        await agent.send_response_cancel("resp-missing")

    assert len(ws.messages) == 1


@pytest.mark.asyncio
async def test_cancel_with_ambiguous_exact_response_id_is_rejected(agent: AvatarAgent):
    ws = RecordingWs()
    agent._ws_client = ws
    await agent.send_response_chunk("req-1", "resp-shared", 0, 1000, "first")
    await agent.send_response_chunk("req-2", "resp-shared", 0, 1001, "second")

    with pytest.raises(ResponseStreamStateError, match="cancel"):
        await agent.send_response_cancel("resp-shared")

    assert len(ws.messages) == 2


@pytest.mark.asyncio
async def test_exact_cancel_clears_only_matching_request(agent: AvatarAgent):
    ws = RecordingWs()
    agent._ws_client = ws
    await agent.send_response_chunk("req-1", "resp-1", 0, 1000, "first")
    await agent.send_response_chunk("req-2", "resp-2", 0, 1001, "second")

    await agent.send_response_cancel("resp-1")
    await agent.send_response_start("req-1", "resp-3")
    await agent.send_response_done("req-2", "resp-2")

    assert [message["event"] for message in ws.messages[-3:]] == [
        EventType.RESPONSE_CANCEL,
        EventType.RESPONSE_START,
        EventType.RESPONSE_DONE,
    ]


@pytest.mark.asyncio
async def test_concurrent_duplicate_first_chunks_create_only_one_active_response(
    agent: AvatarAgent,
):
    ws = RecordingWs()
    agent._ws_client = ws

    results = await asyncio.gather(
        agent.send_response_chunk("req-1", "resp-1", 0, 1000, "first"),
        agent.send_response_chunk("req-1", "resp-2", 0, 1001, "second"),
        return_exceptions=True,
    )

    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, ResponseStreamStateError) for result in results) == 1
    assert len(ws.messages) == 1


@pytest.mark.asyncio
async def test_sequence_error_omits_chunk_text_and_metadata(agent: AvatarAgent):
    ws = RecordingWs()
    agent._ws_client = ws
    await agent.send_response_chunk("req-1", "resp-1", 0, 1000, "first")

    with pytest.raises(ResponseStreamStateError) as error:
        await agent.send_response_chunk(
            "req-1",
            "resp-1",
            2,
            1001,
            "secret chunk text",
            {"secret": "metadata value"},
        )

    assert "secret chunk text" not in str(error.value)
    assert "metadata value" not in str(error.value)


@pytest.mark.asyncio
async def test_start_send_failure_rolls_back_creation(agent: AvatarAgent):
    ws = FailingWs(fail_on=1)
    agent._ws_client = ws

    with pytest.raises(OSError, match="selected send failure"):
        await agent.send_response_start("req-1", "resp-1")

    await agent.send_response_start("req-1", "resp-2")
    assert ws.messages[0]["responseId"] == "resp-2"


@pytest.mark.asyncio
async def test_first_chunk_send_failure_rolls_back_creation(agent: AvatarAgent):
    ws = FailingWs(fail_on=1)
    agent._ws_client = ws

    with pytest.raises(OSError, match="selected send failure"):
        await agent.send_response_chunk("req-1", "resp-1", 0, 1000, "first")

    await agent.send_response_chunk("req-1", "resp-2", 0, 1001, "retry")
    assert ws.messages[0]["responseId"] == "resp-2"


@pytest.mark.asyncio
async def test_chunk_send_failure_does_not_advance_sequence(agent: AvatarAgent):
    ws = FailingWs(fail_on=2)
    agent._ws_client = ws
    await agent.send_response_chunk("req-1", "resp-1", 0, 1000, "first")

    with pytest.raises(OSError, match="selected send failure"):
        await agent.send_response_chunk("req-1", "resp-1", 1, 1001, "failed")

    await agent.send_response_chunk("req-1", "resp-1", 1, 1002, "retry")
    assert [message["seq"] for message in ws.messages] == [0, 1]


@pytest.mark.asyncio
async def test_done_send_failure_keeps_state_for_retry(agent: AvatarAgent):
    ws = FailingWs(fail_on=2)
    agent._ws_client = ws
    await agent.send_response_chunk("req-1", "resp-1", 0, 1000, "first")

    with pytest.raises(OSError, match="selected send failure"):
        await agent.send_response_done("req-1", "resp-1")

    await agent.send_response_done("req-1", "resp-1")
    assert ws.messages[-1]["event"] == EventType.RESPONSE_DONE


@pytest.mark.asyncio
async def test_cancel_send_failure_keeps_state_for_retry(agent: AvatarAgent):
    ws = FailingWs(fail_on=2)
    agent._ws_client = ws
    await agent.send_response_chunk("req-1", "resp-1", 0, 1000, "first")

    with pytest.raises(OSError, match="selected send failure"):
        await agent.send_response_cancel("resp-1")

    await agent.send_response_cancel("resp-1")
    assert ws.messages[-1]["event"] == EventType.RESPONSE_CANCEL
