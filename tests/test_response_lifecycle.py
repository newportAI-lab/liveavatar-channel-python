from __future__ import annotations

import asyncio

import pytest

from liveavatar_channel_sdk.response_lifecycle import _ResponseLifecycleCoordinator
from liveavatar_channel_sdk.response_state import ResponseStateEvent
from liveavatar_channel_sdk.avatar_agent import AgentListener, _ListenerBridge


def lifecycle_event(
    seq: int,
    *,
    state: str = "ACCEPTED",
    reason: str | None = None,
    session_id: str = "session-1",
    request_id: str = "request-1",
    response_id: str = "response-1",
) -> ResponseStateEvent:
    return ResponseStateEvent(
        session_id=session_id,
        request_id=request_id,
        response_id=response_id,
        seq=seq,
        timestamp=1788960000000 + seq,
        state=state,
        reason=reason,
    )


@pytest.mark.asyncio
async def test_matching_first_terminal_completes_pending_response_once():
    coordinator = _ResponseLifecycleCoordinator()
    pending = await coordinator.register("session-1", "request-1", "response-1")

    assert await coordinator.handle(lifecycle_event(1)) is True
    assert pending.is_finished is False

    first = lifecycle_event(2, state="FINISHED", reason="COMPLETED")
    later = lifecycle_event(3, state="FINISHED", reason="INTERNAL_ERROR")
    assert await coordinator.handle(first) is True
    assert await coordinator.handle(later) is True
    assert await pending.wait_finished() == first


@pytest.mark.asyncio
async def test_lifecycle_deduplicates_by_session_sequence_and_accepts_gaps():
    coordinator = _ResponseLifecycleCoordinator()

    assert await coordinator.handle(lifecycle_event(5, response_id="unknown")) is True
    assert await coordinator.handle(lifecycle_event(5, response_id="other")) is False
    assert await coordinator.handle(lifecycle_event(4, response_id="other")) is False
    assert await coordinator.handle(lifecycle_event(9, response_id="other")) is True


@pytest.mark.asyncio
async def test_identity_mismatch_does_not_complete_pending_but_remains_publishable():
    coordinator = _ResponseLifecycleCoordinator()
    pending = await coordinator.register("session-1", "request-1", "response-1")

    assert (
        await coordinator.handle(
            lifecycle_event(1, request_id="wrong", state="REJECTED", reason="INVALID_REQUEST")
        )
        is True
    )
    assert pending.is_finished is False


@pytest.mark.asyncio
async def test_reset_cancels_pending_wait_without_platform_terminal():
    coordinator = _ResponseLifecycleCoordinator()
    pending = await coordinator.register("session-1", "request-1", "response-1")

    await coordinator.reset()

    with pytest.raises(asyncio.CancelledError):
        await pending.wait_finished()


@pytest.mark.asyncio
async def test_duplicate_response_identity_is_rejected():
    coordinator = _ResponseLifecycleCoordinator()
    await coordinator.register("session-1", "request-1", "response-1")

    with pytest.raises(ValueError, match="already registered"):
        await coordinator.register("session-1", "request-1", "response-1")


@pytest.mark.asyncio
async def test_listener_bridge_publishes_each_session_sequence_once():
    class RecordingListener(AgentListener):
        def __init__(self):
            self.events = []

        async def on_response_state(self, event):
            self.events.append(event)

    listener = RecordingListener()
    bridge = _ListenerBridge(listener, _ResponseLifecycleCoordinator())
    event = lifecycle_event(4, state="FUTURE_STATE", reason="FUTURE_REASON")

    await bridge.on_response_state(event)
    await bridge.on_response_state(event)

    assert listener.events == [event]
