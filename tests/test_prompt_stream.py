from __future__ import annotations

import asyncio

import pytest

from liveavatar_channel_sdk import PromptStream, PromptStreamStateError
from liveavatar_channel_sdk.avatar_agent import AgentListener, AvatarAgent, AvatarAgentConfig
from liveavatar_channel_sdk.event_type import EventType
from liveavatar_channel_sdk.response_state import ResponseStateEvent


class RecordingWs:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)


class FailingWs(RecordingWs):
    async def send_json(self, message: dict) -> None:
        raise OSError("start failed")


def make_agent(ws=None) -> AvatarAgent:
    agent = AvatarAgent(AvatarAgentConfig("key", "avatar"), AgentListener())
    agent._session_id = "session-1"
    agent._ws_client = ws or RecordingWs()
    return agent


def terminal(response_id="prompt-1", request_id="request-1", seq=1):
    return ResponseStateEvent(
        session_id="session-1",
        request_id=request_id,
        response_id=response_id,
        seq=seq,
        timestamp=1788960000000,
        state="FINISHED",
        reason="COMPLETED",
    )


@pytest.mark.asyncio
async def test_prompt_stream_sends_stable_identity_chunks_and_done_without_accepted():
    ws = RecordingWs()
    agent = make_agent(ws)

    stream = agent.prompt_stream("request-1", response_id="prompt-1")
    assert isinstance(stream, PromptStream)
    assert stream.request_id == "request-1"
    assert stream.response_id == "prompt-1"

    async with stream:
        await stream.send("first", timestamp=100)
        await stream.send("second", timestamp=200)

    assert ws.messages == [
        {
            "event": EventType.SYSTEM_PROMPT_START,
            "requestId": "request-1",
            "responseId": "prompt-1",
        },
        {
            "event": EventType.SYSTEM_PROMPT_CHUNK,
            "requestId": "request-1",
            "responseId": "prompt-1",
            "seq": 1,
            "timestamp": 100,
            "data": {"text": "first"},
        },
        {
            "event": EventType.SYSTEM_PROMPT_CHUNK,
            "requestId": "request-1",
            "responseId": "prompt-1",
            "seq": 2,
            "timestamp": 200,
            "data": {"text": "second"},
        },
        {
            "event": EventType.SYSTEM_PROMPT_DONE,
            "requestId": "request-1",
            "responseId": "prompt-1",
        },
    ]


def test_prompt_stream_generates_response_id_and_rejects_blank_identity():
    agent = make_agent()

    assert agent.prompt_stream("request-1").response_id
    with pytest.raises(ValueError, match="request_id"):
        agent.prompt_stream(" ")
    with pytest.raises(ValueError, match="response_id"):
        agent.prompt_stream("request-1", response_id="")


@pytest.mark.asyncio
async def test_prompt_done_does_not_complete_waiter():
    agent = make_agent()
    stream = agent.prompt_stream("request-1", response_id="prompt-1")

    async with stream:
        await stream.send("hello")

    waiter = asyncio.create_task(stream.wait_finished())
    await asyncio.sleep(0)
    assert waiter.done() is False

    event = terminal()
    await agent._inbound_response_lifecycle.handle(event)
    assert await waiter == event


@pytest.mark.asyncio
async def test_prompt_stream_is_registered_before_start_send():
    agent = make_agent()

    class ImmediateLifecycleWs(RecordingWs):
        async def send_json(self, message):
            await super().send_json(message)
            if message["event"] == EventType.SYSTEM_PROMPT_START:
                await agent._inbound_response_lifecycle.handle(terminal())

    ws = ImmediateLifecycleWs()
    agent._ws_client = ws
    stream = agent.prompt_stream("request-1", response_id="prompt-1")

    async with stream:
        assert await stream.wait_finished() == terminal()


@pytest.mark.asyncio
async def test_concurrent_prompt_sends_get_unique_monotonic_sequences():
    ws = RecordingWs()
    agent = make_agent(ws)
    stream = agent.prompt_stream("request-1", response_id="prompt-1")

    async with stream:
        await asyncio.gather(*(stream.send(str(index), timestamp=index) for index in range(20)))

    chunks = [
        message for message in ws.messages if message["event"] == EventType.SYSTEM_PROMPT_CHUNK
    ]
    assert [message["seq"] for message in chunks] == list(range(1, 21))


@pytest.mark.asyncio
async def test_prompt_stream_rejects_invalid_local_state():
    agent = make_agent()
    stream = agent.prompt_stream("request-1", response_id="prompt-1")

    with pytest.raises(PromptStreamStateError, match="not been entered"):
        await stream.send("early")
    async with stream:
        pass
    with pytest.raises(PromptStreamStateError, match="closed"):
        await stream.send("late")
    with pytest.raises(PromptStreamStateError, match="closed"):
        await stream.done()
    with pytest.raises(PromptStreamStateError, match="entered twice"):
        async with stream:
            pass


@pytest.mark.asyncio
async def test_explicit_prompt_done_is_not_repeated_by_context_exit():
    ws = RecordingWs()
    agent = make_agent(ws)

    async with agent.prompt_stream("request-1", response_id="prompt-1") as stream:
        await stream.done()

    assert [message["event"] for message in ws.messages] == [
        EventType.SYSTEM_PROMPT_START,
        EventType.SYSTEM_PROMPT_DONE,
    ]


@pytest.mark.asyncio
async def test_prompt_start_failure_rolls_back_registration():
    agent = make_agent(FailingWs())
    failed = agent.prompt_stream("request-1", response_id="prompt-1")

    with pytest.raises(OSError, match="start failed"):
        await failed.__aenter__()

    agent._ws_client = RecordingWs()
    replacement = agent.prompt_stream("request-1", response_id="prompt-1")
    async with replacement:
        pass


@pytest.mark.asyncio
async def test_cancelling_waiter_does_not_cancel_shared_terminal_result():
    agent = make_agent()
    stream = agent.prompt_stream("request-1", response_id="prompt-1")
    await stream.__aenter__()

    waiter = asyncio.create_task(stream.wait_finished())
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    event = terminal()
    await agent._inbound_response_lifecycle.handle(event)
    assert await stream.wait_finished() == event


@pytest.mark.asyncio
async def test_exceptional_context_exit_does_not_send_done_or_terminal():
    ws = RecordingWs()
    agent = make_agent(ws)
    stream = agent.prompt_stream("request-1", response_id="prompt-1")

    with pytest.raises(RuntimeError, match="business failure"):
        async with stream:
            raise RuntimeError("business failure")

    assert [message["event"] for message in ws.messages] == [EventType.SYSTEM_PROMPT_START]
    assert stream.is_finished is False
