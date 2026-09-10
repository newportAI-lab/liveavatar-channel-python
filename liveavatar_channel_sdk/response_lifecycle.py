"""Internal response lifecycle correlation and deduplication."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from liveavatar_channel_sdk.response_state import ResponseStateEvent

_TERMINAL_STATES = {"REJECTED", "FINISHED"}


@dataclass
class _PendingResponse:
    session_id: str
    request_id: str
    response_id: str
    _future: asyncio.Future[ResponseStateEvent]
    latest: ResponseStateEvent | None = None
    terminal: ResponseStateEvent | None = None

    @property
    def is_finished(self) -> bool:
        return self.terminal is not None

    async def wait_finished(self) -> ResponseStateEvent:
        return await asyncio.shield(self._future)


class _ResponseLifecycleCoordinator:
    """Tracks online event order and locally-created response identities."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last_seq: dict[str, int] = {}
        self._pending: dict[tuple[str, str], _PendingResponse] = {}

    async def register(
        self, session_id: str, request_id: str, response_id: str
    ) -> _PendingResponse:
        key = (session_id, response_id)
        async with self._lock:
            if key in self._pending:
                raise ValueError(
                    f"response {response_id!r} is already registered for session {session_id!r}"
                )
            pending = _PendingResponse(
                session_id=session_id,
                request_id=request_id,
                response_id=response_id,
                _future=asyncio.get_running_loop().create_future(),
            )
            self._pending[key] = pending
            return pending

    async def rollback(self, pending: _PendingResponse) -> None:
        async with self._lock:
            key = (pending.session_id, pending.response_id)
            if self._pending.get(key) is pending:
                self._pending.pop(key)
        if not pending._future.done():
            pending._future.cancel()

    async def handle(self, event: ResponseStateEvent) -> bool:
        completed: asyncio.Future[ResponseStateEvent] | None = None
        async with self._lock:
            last_seq = self._last_seq.get(event.session_id)
            if last_seq is not None and event.seq <= last_seq:
                return False
            self._last_seq[event.session_id] = event.seq

            pending = self._pending.get((event.session_id, event.response_id))
            if pending is not None and pending.request_id == event.request_id:
                if pending.terminal is None:
                    pending.latest = event
                    if event.state in _TERMINAL_STATES:
                        pending.terminal = event
                        completed = pending._future

        if completed is not None and not completed.done():
            completed.set_result(event)
        return True

    async def reset(self) -> None:
        async with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
            self._last_seq.clear()
        for response in pending:
            if not response._future.done():
                response._future.cancel()
