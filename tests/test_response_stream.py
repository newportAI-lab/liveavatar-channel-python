"""Tests for response stream lifecycle coordination."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from liveavatar_channel_sdk.avatar_agent import (
    AgentListener,
    AvatarAgent,
    AvatarAgentConfig,
)
from liveavatar_channel_sdk.event_type import EventType
from liveavatar_channel_sdk.example import live_avatar_service_simulator as simulator
from liveavatar_channel_sdk.example.live_avatar_service_simulator import EchoAgent
from liveavatar_channel_sdk.response_stream import ResponseStreamStateError
from liveavatar_channel_sdk.response_state import ResponseStateEvent

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_documentation_describes_response_stream_lifecycle_and_release_version():
    """Documentation must preserve the safe streaming migration contract."""
    english_protocol = (REPOSITORY_ROOT / "PROTOCOL.md").read_text()
    chinese_protocol = (REPOSITORY_ROOT / "PROTOCOL.zh.md").read_text()
    english_readme = (REPOSITORY_ROOT / "README.md").read_text()
    chinese_readme = (REPOSITORY_ROOT / "README.zh.md").read_text()
    package_metadata = (REPOSITORY_ROOT / "pyproject.toml").read_text()
    normalized_english_protocol = " ".join(english_protocol.split())
    normalized_chinese_protocol = " ".join(chinese_protocol.split())
    normalized_english_readme = " ".join(english_readme.split())
    normalized_chinese_readme = " ".join(chinese_readme.split())

    assert "MUST use the same `requestId` and `responseId`." in normalized_english_protocol
    assert "MUST be followed by `response.done`" in normalized_english_protocol
    assert "distinct request IDs may be processed concurrently" in normalized_english_protocol
    assert "必须使用相同的 `requestId` 和 `responseId`。" in normalized_chinese_protocol
    assert "必须紧接着发送相同标识符的 `response.done`" in normalized_chinese_protocol
    assert "不同的 request ID 可按应用策略并发处理" in normalized_chinese_protocol

    assert "exactly one active legacy response" in normalized_english_readme
    assert "Zero or multiple matches raise `ResponseStreamStateError`" in normalized_english_readme
    assert "恰好一个活动的旧响应" in normalized_chinese_readme
    assert "零个或多个匹配都会抛出 `ResponseStreamStateError`" in normalized_chinese_readme

    for readme in (english_readme, chinese_readme):
        quick_start = readme.split("### 2.", maxsplit=1)[0]
        assert "async with" in quick_start
        assert "response_stream" in quick_start
        assert '"resp-1"' not in quick_start
        assert "0.4.1" in readme
        assert "0.2.7" not in readme

    assert 'version = "0.4.1"' in package_metadata
    assert "0.2.7" not in package_metadata


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


class RecordingResponseStream:
    def __init__(self, request_id: str, release: asyncio.Event) -> None:
        self.request_id = request_id
        self.response_id = "response-" + request_id
        self._release = release
        self.chunk_sent = asyncio.Event()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        return None

    async def send_chunk(self, text: str) -> None:
        self.chunk_sent.set()
        await self._release.wait()


class RecordingResponseStreamAgent:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.streams = []
        self.stream_created = asyncio.Event()

    def response_stream(self, request_id: str, *, send_start: bool):
        stream = RecordingResponseStream(request_id, self.release)
        self.streams.append(stream)
        self.stream_created.set()
        return stream


class EchoResponseStream:
    def __init__(self) -> None:
        self.response_id = "stream-generated-id"
        self.chunks = []
        self.exited = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        self.exited = True

    async def send_chunk(self, text: str) -> None:
        self.chunks.append(text)


class EchoResponseStreamAgent:
    def __init__(self) -> None:
        self.response_stream_calls = []
        self.stream = EchoResponseStream()

    def response_stream(self, request_id: str, *, send_start: bool):
        self.response_stream_calls.append((request_id, send_start))
        return self.stream


@pytest.fixture
def agent() -> AvatarAgent:
    instance = AvatarAgent(
        AvatarAgentConfig(api_key="sk-test", avatar_id="avatar-1"),
        AgentListener(),
    )
    instance._session_id = "session-1"
    return instance


@pytest.mark.asyncio
async def test_simulator_rejects_duplicate_active_request_but_runs_other_requests():
    listener = EchoAgent()
    fake_agent = RecordingResponseStreamAgent()
    listener.agent = fake_agent

    async def controlled_echo(request_id: str, text: str) -> None:
        async with fake_agent.response_stream(request_id, send_start=True) as response:
            await response.send_chunk(text)

    listener._echo = controlled_echo

    await listener.on_text_input("first", "request-1")
    await fake_agent.stream_created.wait()
    await fake_agent.streams[0].chunk_sent.wait()
    fake_agent.stream_created.clear()

    await listener.on_text_input("duplicate", "request-1")
    assert [stream.request_id for stream in fake_agent.streams] == ["request-1"]

    await listener.on_text_input("second", "request-2")
    await fake_agent.stream_created.wait()
    await fake_agent.streams[1].chunk_sent.wait()
    assert [stream.request_id for stream in fake_agent.streams] == [
        "request-1",
        "request-2",
    ]

    tasks = list(listener._response_tasks.values())
    fake_agent.release.set()
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_simulator_stale_task_callback_keeps_replacement_registered():
    listener = EchoAgent()
    listener.agent = object()
    first_release = asyncio.Event()
    second_release = asyncio.Event()
    first_started = asyncio.Event()
    replacement = None

    async def controlled_echo(request_id: str, text: str) -> None:
        if text == "first":
            first_started.set()
            await first_release.wait()
        else:
            await second_release.wait()

    listener._echo = controlled_echo

    await listener.on_text_input("first", "request-1")
    await first_started.wait()
    first_task = listener._response_tasks["request-1"]

    async def replace_finished_task() -> None:
        nonlocal replacement
        await listener.on_text_input("second", "request-1")
        replacement = listener._response_tasks["request-1"]

    first_release.set()
    await asyncio.create_task(replace_finished_task())

    assert first_task.done()
    assert listener._response_tasks["request-1"] is replacement

    second_release.set()
    await replacement


@pytest.mark.asyncio
async def test_simulator_echo_uses_response_stream_context_for_chunks(monkeypatch):
    """Restoring manual IDs or terminal events to _echo breaks this fake stream."""
    listener = EchoAgent()
    fake_agent = EchoResponseStreamAgent()
    listener.agent = fake_agent
    sleep_delays = []

    async def record_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    monkeypatch.setattr(simulator.asyncio, "sleep", record_sleep)

    await listener._echo("request-1", "hello world")

    assert fake_agent.response_stream_calls == [("request-1", True)]
    assert fake_agent.stream.chunks == ["hello ", "world "]
    assert fake_agent.stream.exited
    assert sleep_delays == [0.05, 0.05]
    assert listener.response_done.is_set()


def test_response_stream_types_are_exported():
    from liveavatar_channel_sdk import ResponseStream, ResponseStreamStateError

    assert issubclass(ResponseStreamStateError, RuntimeError)
    assert ResponseStream.__module__ == "liveavatar_channel_sdk.response_stream"


def test_response_stream_factory_exposes_request_and_generated_response_ids(
    agent: AvatarAgent,
):
    from liveavatar_channel_sdk import ResponseStream

    response = agent.response_stream("req-1")

    assert isinstance(response, ResponseStream)
    assert response.request_id == "req-1"
    assert response.response_id


@pytest.mark.asyncio
async def test_response_stream_defaults_to_explicit_start_and_waits_for_platform_terminal(
    agent: AvatarAgent,
):
    ws = RecordingWs()
    agent._ws_client = ws
    response = agent.response_stream("req-1")

    async with response:
        await response.send_chunk("hello", timestamp=1000)

    assert [message["event"] for message in ws.messages] == [
        EventType.RESPONSE_START,
        EventType.RESPONSE_CHUNK,
        EventType.RESPONSE_DONE,
    ]
    waiter = asyncio.create_task(response.wait_finished())
    await asyncio.sleep(0)
    assert waiter.done() is False

    terminal = ResponseStateEvent(
        session_id="session-1",
        request_id="req-1",
        response_id=response.response_id,
        seq=1,
        timestamp=2000,
        state="FINISHED",
        reason="COMPLETED",
    )
    await agent._inbound_response_lifecycle.handle(terminal)
    assert await waiter == terminal


@pytest.mark.asyncio
async def test_response_stream_explicit_no_start_preserves_compatibility(agent: AvatarAgent):
    ws = RecordingWs()
    agent._ws_client = ws

    async with agent.response_stream("req-1", send_start=False) as response:
        await response.send_chunk("hello", timestamp=1000)

    assert [message["event"] for message in ws.messages] == [
        EventType.RESPONSE_CHUNK,
        EventType.RESPONSE_DONE,
    ]


@pytest.mark.asyncio
async def test_response_stream_reuses_id_sequences_chunks_and_auto_dones(
    agent: AvatarAgent,
):
    ws = RecordingWs()
    agent._ws_client = ws

    async with agent.response_stream("req-1", send_start=False) as response:
        response_id = response.response_id
        assert response.request_id == "req-1"
        await response.send_chunk("first", timestamp=1000)
        await response.send_chunk("second", timestamp=1001)

    assert [message["event"] for message in ws.messages] == [
        EventType.RESPONSE_CHUNK,
        EventType.RESPONSE_CHUNK,
        EventType.RESPONSE_DONE,
    ]
    assert {message["responseId"] for message in ws.messages} == {response_id}
    assert [message.get("seq") for message in ws.messages[:2]] == [0, 1]


@pytest.mark.asyncio
async def test_response_stream_send_start_uses_factory_configuration(agent: AvatarAgent):
    ws = RecordingWs()
    agent._ws_client = ws

    async with agent.response_stream(
        "req-1",
        speed=1.5,
        volume=0.75,
        mood="happy",
        metadata={"source": "test"},
        send_start=True,
    ) as response:
        await response.send_chunk("hello", timestamp=1000)

    assert ws.messages[0] == {
        "event": EventType.RESPONSE_START,
        "requestId": "req-1",
        "responseId": response.response_id,
        "data": {
            "audioConfig": {"speed": 1.5, "volume": 0.75, "mood": "happy"},
            "source": "test",
        },
    }


@pytest.mark.asyncio
async def test_response_stream_generates_epoch_millisecond_timestamp(
    agent: AvatarAgent,
    monkeypatch: pytest.MonkeyPatch,
):
    ws = RecordingWs()
    agent._ws_client = ws
    monkeypatch.setattr(
        "liveavatar_channel_sdk.response_stream.time.time_ns",
        lambda: 1_725_000_123_456_789_000,
    )

    async with agent.response_stream("req-1", send_start=False) as response:
        await response.send_chunk("hello")

    assert ws.messages[0]["timestamp"] == 1_725_000_123_456


@pytest.mark.asyncio
async def test_response_stream_explicit_done_is_not_repeated_on_exit(agent: AvatarAgent):
    ws = RecordingWs()
    agent._ws_client = ws

    async with agent.response_stream("req-1", send_start=False) as response:
        await response.send_chunk("hello", timestamp=1000)
        await response.done({"reason": "complete"})

    assert [message["event"] for message in ws.messages] == [
        EventType.RESPONSE_CHUNK,
        EventType.RESPONSE_DONE,
    ]
    assert ws.messages[-1]["data"] == {"reason": "complete"}


@pytest.mark.asyncio
async def test_response_stream_cancel_is_not_followed_by_done_on_exit(agent: AvatarAgent):
    ws = RecordingWs()
    agent._ws_client = ws

    async with agent.response_stream("req-1", send_start=False) as response:
        await response.cancel()

    assert [message["event"] for message in ws.messages] == [EventType.RESPONSE_CANCEL]
    assert ws.messages[0]["responseId"] == response.response_id


@pytest.mark.asyncio
async def test_response_stream_exception_cancels_and_preserves_original_exception(
    agent: AvatarAgent,
):
    ws = RecordingWs()
    agent._ws_client = ws
    original = ValueError("application failure")

    with pytest.raises(ValueError) as error:
        async with agent.response_stream("req-1", send_start=False):
            raise original

    assert error.value is original
    assert [message["event"] for message in ws.messages] == [EventType.RESPONSE_CANCEL]


@pytest.mark.asyncio
async def test_response_stream_cancel_failure_preserves_and_notes_original_exception(
    agent: AvatarAgent,
    caplog: pytest.LogCaptureFixture,
):
    ws = FailingWs(fail_on=1)
    agent._ws_client = ws
    original = ValueError("application failure")
    response = agent.response_stream("req-1", send_start=False)

    with pytest.raises(ValueError) as error:
        async with response:
            raise original

    assert error.value is original
    if hasattr(original, "add_note"):
        assert any(
            "failed to cancel response stream: selected send failure" in note
            for note in original.__notes__
        )
    else:
        assert "failed to cancel response stream: selected send failure" in caplog.text

    await response.cancel()
    assert ws.messages[-1]["event"] == EventType.RESPONSE_CANCEL


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["send_chunk", "done", "cancel"])
async def test_response_stream_rejects_use_before_entry(
    agent: AvatarAgent,
    operation: str,
):
    response = agent.response_stream("req-1")

    with pytest.raises(ResponseStreamStateError, match="has not been entered"):
        if operation == "send_chunk":
            await response.send_chunk("hello", timestamp=1000)
        else:
            await getattr(response, operation)()


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_operation", ["done", "cancel"])
@pytest.mark.parametrize("later_operation", ["send_chunk", "done", "cancel"])
async def test_response_stream_rejects_use_after_terminal_state(
    agent: AvatarAgent,
    terminal_operation: str,
    later_operation: str,
):
    ws = RecordingWs()
    agent._ws_client = ws
    response = agent.response_stream("req-1")
    await response.__aenter__()
    await getattr(response, terminal_operation)()

    with pytest.raises(ResponseStreamStateError, match="already terminal"):
        if later_operation == "send_chunk":
            await response.send_chunk("hello", timestamp=1000)
        else:
            await getattr(response, later_operation)()


@pytest.mark.asyncio
async def test_response_stream_reenter_is_rejected(agent: AvatarAgent):
    ws = RecordingWs()
    agent._ws_client = ws
    response = agent.response_stream("req-1")

    async with response:
        with pytest.raises(ResponseStreamStateError, match="entered twice"):
            await response.__aenter__()


@pytest.mark.asyncio
async def test_response_stream_owner_blocks_other_stream_and_legacy_operations(
    agent: AvatarAgent,
):
    ws = RecordingWs()
    agent._ws_client = ws

    async with agent.response_stream("req-1", send_start=False) as response:
        other = agent.response_stream("req-1", send_start=False)
        with pytest.raises(ResponseStreamStateError):
            await other.__aenter__()
        with pytest.raises(ResponseStreamStateError):
            await agent.send_response_start("req-1", "legacy-start")
        with pytest.raises(ResponseStreamStateError):
            await agent.send_response_chunk("req-1", "legacy-chunk", 0, 1000, "blocked")
        with pytest.raises(ResponseStreamStateError):
            await agent.send_response_done("req-1", "legacy-done")
        with pytest.raises(ResponseStreamStateError):
            await agent.send_response_cancel(response.response_id)

        assert ws.messages == []

    assert [message["event"] for message in ws.messages] == [EventType.RESPONSE_DONE]


@pytest.mark.asyncio
async def test_response_stream_cannot_claim_legacy_owned_request(agent: AvatarAgent):
    ws = RecordingWs()
    agent._ws_client = ws
    await agent.send_response_start("req-1", "legacy-response")
    response = agent.response_stream("req-1", send_start=False)

    with pytest.raises(ResponseStreamStateError):
        await response.__aenter__()

    await agent.send_response_done("req-1", "legacy-response")
    assert [message["event"] for message in ws.messages] == [
        EventType.RESPONSE_START,
        EventType.RESPONSE_DONE,
    ]


@pytest.mark.asyncio
async def test_concurrent_response_stream_enters_for_same_request_have_one_winner(
    agent: AvatarAgent,
):
    ws = RecordingWs()
    agent._ws_client = ws
    gate = asyncio.Event()
    first = agent.response_stream("req-1", send_start=False)
    second = agent.response_stream("req-1", send_start=False)

    async def enter(response):
        await gate.wait()
        return await response.__aenter__()

    tasks = [asyncio.create_task(enter(first)), asyncio.create_task(enter(second))]
    gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert sum(result in (first, second) for result in results) == 1
    assert sum(isinstance(result, ResponseStreamStateError) for result in results) == 1
    winner = next(result for result in results if result in (first, second))
    await winner.done()
    assert [message["event"] for message in ws.messages] == [EventType.RESPONSE_DONE]


@pytest.mark.asyncio
async def test_legacy_and_response_stream_for_different_requests_complete_independently(
    agent: AvatarAgent,
):
    ws = RecordingWs()
    agent._ws_client = ws
    await agent.send_response_chunk("legacy-request", "legacy-response", 0, 1000, "one")

    async with agent.response_stream("stream-request", send_start=False) as response:
        await response.send_chunk("two", timestamp=1001)
        await agent.send_response_done("legacy-request", "legacy-response")

    assert [(message.get("requestId"), message["event"]) for message in ws.messages] == [
        ("legacy-request", EventType.RESPONSE_CHUNK),
        ("stream-request", EventType.RESPONSE_CHUNK),
        ("legacy-request", EventType.RESPONSE_DONE),
        ("stream-request", EventType.RESPONSE_DONE),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_operation", ["done", "cancel"])
async def test_response_stream_failed_terminal_send_keeps_stream_open_for_retry(
    agent: AvatarAgent,
    terminal_operation: str,
):
    ws = FailingWs(fail_on=1)
    agent._ws_client = ws
    response = agent.response_stream("req-1", send_start=False)
    await response.__aenter__()

    with pytest.raises(OSError, match="selected send failure"):
        await getattr(response, terminal_operation)()

    await getattr(response, terminal_operation)()
    expected = (
        EventType.RESPONSE_DONE if terminal_operation == "done" else EventType.RESPONSE_CANCEL
    )
    assert ws.messages[-1]["event"] == expected


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
async def test_legacy_response_id_warning_points_to_caller(agent: AvatarAgent):
    """Changing warning stacklevel back to the SDK wrapper loses caller context."""
    ws = RecordingWs()
    agent._ws_client = ws
    await agent.send_response_chunk("req-1", "resp-1", 0, 1000, "first")

    with pytest.warns(DeprecationWarning, match="resp-2") as captured:
        await agent.send_response_chunk("req-1", "resp-2", 1, 1001, "second")

    assert Path(captured[0].filename).resolve() == Path(__file__).resolve()


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

    gate = asyncio.Event()

    async def send(response_id: str, timestamp: int, text: str):
        await gate.wait()
        return await agent.send_response_chunk("req-1", response_id, 0, timestamp, text)

    tasks = [
        asyncio.create_task(send("resp-1", 1000, "first")),
        asyncio.create_task(send("resp-2", 1001, "second")),
    ]
    gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

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
