"""Response stream lifecycle coordination."""

from __future__ import annotations

import asyncio
import logging
import time
import warnings
from dataclasses import dataclass
from typing import Awaitable, Callable

from liveavatar_channel_sdk.message_builder import MessageBuilder
from liveavatar_channel_sdk.response_lifecycle import (
    _PendingResponse,
    _ResponseLifecycleCoordinator,
)
from liveavatar_channel_sdk.response_state import ResponseStateEvent

logger = logging.getLogger(__name__)


class ResponseStreamStateError(RuntimeError):
    """Raised when a response operation violates the active stream lifecycle."""


class ResponseStream:
    """A request-scoped text response stream created by ``AvatarAgent``."""

    def __init__(
        self,
        lifecycle: _ResponseLifecycle,
        inbound_lifecycle: _ResponseLifecycleCoordinator,
        session_id: Callable[[], str | None],
        request_id: str,
        response_id: str,
        *,
        start_message: dict | None,
    ) -> None:
        self._lifecycle = lifecycle
        self._inbound_lifecycle = inbound_lifecycle
        self._session_id = session_id
        self._request_id = request_id
        self._response_id = response_id
        self._start_message = start_message
        self._entered = False
        self._terminal = False
        self._pending: _PendingResponse | None = None

    @property
    def request_id(self) -> str:
        return self._request_id

    @property
    def response_id(self) -> str:
        return self._response_id

    async def __aenter__(self) -> ResponseStream:
        if self._entered:
            raise ResponseStreamStateError("response stream cannot be entered twice")
        session_id = self._session_id()
        if session_id is None:
            raise RuntimeError("Not connected — call start() first")
        pending = await self._inbound_lifecycle.register(
            session_id, self._request_id, self._response_id
        )
        self._pending = pending
        try:
            await self._lifecycle.claim(
                self,
                self._request_id,
                self._response_id,
                self._start_message,
            )
        except BaseException:
            self._pending = None
            await self._inbound_lifecycle.rollback(pending)
            raise
        self._entered = True
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        if self._terminal:
            return False
        if exc is None:
            await self.done()
            return False
        try:
            await self.cancel()
        except BaseException as cancel_error:
            message = f"failed to cancel response stream: {cancel_error}"
            if hasattr(exc, "add_note"):
                exc.add_note(message)
            else:
                logger.warning(message)
        return False

    async def send_chunk(
        self,
        text: str,
        *,
        timestamp: int | None = None,
        metadata: dict | None = None,
    ) -> None:
        self._require_open("send chunk")
        if timestamp is None:
            timestamp = time.time_ns() // 1_000_000
        await self._lifecycle.stream_chunk(self, text, timestamp, metadata)

    async def done(self, metadata: dict | None = None) -> None:
        self._require_open("finish")
        await self._lifecycle.stream_done(self, metadata)
        self._terminal = True

    async def cancel(self) -> None:
        self._require_open("cancel")
        await self._lifecycle.stream_cancel(self)
        self._terminal = True

    async def wait_finished(self) -> ResponseStateEvent:
        if self._pending is None:
            raise ResponseStreamStateError(
                "cannot wait for completion: response stream has not been entered"
            )
        return await self._pending.wait_finished()

    def _require_open(self, operation: str) -> None:
        if not self._entered:
            raise ResponseStreamStateError(
                f"cannot {operation}: response stream has not been entered"
            )
        if self._terminal:
            raise ResponseStreamStateError(
                f"cannot {operation}: response stream is already terminal"
            )


@dataclass
class _ActiveResponse:
    request_id: str
    response_id: str
    next_seq: int = 0
    owner: object | None = None


class _ResponseLifecycle:
    def __init__(self, send_json: Callable[[dict], Awaitable[None]]) -> None:
        self._send_json = send_json
        self._lock = asyncio.Lock()
        self._active: dict[str, _ActiveResponse] = {}

    async def reset(self) -> None:
        async with self._lock:
            self._active.clear()

    async def claim(
        self,
        owner: object,
        request_id: str,
        response_id: str,
        start_message: dict | None,
    ) -> None:
        async with self._lock:
            current = self._active.get(request_id)
            if current is not None:
                raise self._state_error("enter", request_id, response_id, current)

            active = _ActiveResponse(request_id, response_id, owner=owner)
            self._active[request_id] = active
            try:
                if start_message is not None:
                    await self._send_json(start_message)
            except BaseException:
                self._active.pop(request_id, None)
                raise

    async def stream_chunk(
        self,
        owner: object,
        text: str,
        timestamp: int,
        metadata: dict | None,
    ) -> None:
        async with self._lock:
            active = self._require_owner_active("send chunk", owner)
            await self._send_json(
                MessageBuilder.response_chunk(
                    active.request_id,
                    active.response_id,
                    active.next_seq,
                    timestamp,
                    text,
                    metadata,
                )
            )
            active.next_seq += 1

    async def stream_done(self, owner: object, metadata: dict | None) -> None:
        async with self._lock:
            active = self._require_owner_active("finish", owner)
            await self._send_json(
                MessageBuilder.response_done(
                    active.request_id,
                    active.response_id,
                    metadata,
                )
            )
            self._active.pop(active.request_id, None)

    async def stream_cancel(self, owner: object) -> None:
        async with self._lock:
            active = self._require_owner_active("cancel", owner)
            await self._send_json(MessageBuilder.response_cancel(active.response_id))
            self._active.pop(active.request_id, None)

    async def legacy_start(
        self,
        request_id: str,
        response_id: str,
        speed: float,
        volume: float,
        mood: str | None,
        metadata: dict | None,
    ) -> None:
        async with self._lock:
            current = self._active.get(request_id)
            if current is not None:
                raise self._state_error("start", request_id, response_id, current)

            active = _ActiveResponse(request_id, response_id)
            self._active[request_id] = active
            try:
                await self._send_json(
                    MessageBuilder.response_start(
                        request_id,
                        response_id,
                        speed,
                        volume,
                        mood,
                        metadata,
                    )
                )
            except BaseException:
                self._active.pop(request_id, None)
                raise

    async def legacy_chunk(
        self,
        request_id: str,
        response_id: str,
        seq: int,
        timestamp: int,
        text: str,
        metadata: dict | None,
    ) -> None:
        async with self._lock:
            active = self._active.get(request_id)
            created = active is None
            if created:
                active = _ActiveResponse(request_id, response_id)
            elif active.owner is not None:
                raise self._state_error(
                    "chunk",
                    request_id,
                    response_id,
                    active,
                    "no active legacy response",
                )

            if seq != active.next_seq:
                raise self._state_error(
                    "chunk",
                    request_id,
                    response_id,
                    active,
                    f"expected seq {active.next_seq}, got {seq}",
                )

            if created:
                self._active[request_id] = active
            wire_response_id = self._wire_response_id("chunk", response_id, active)
            try:
                await self._send_json(
                    MessageBuilder.response_chunk(
                        request_id,
                        wire_response_id,
                        seq,
                        timestamp,
                        text,
                        metadata,
                    )
                )
            except BaseException:
                if created:
                    self._active.pop(request_id, None)
                raise
            active.next_seq += 1

    async def legacy_done(
        self,
        request_id: str,
        response_id: str,
        metadata: dict | None,
    ) -> None:
        async with self._lock:
            active = self._require_legacy_active("done", request_id, response_id)
            wire_response_id = self._wire_response_id("done", response_id, active)
            await self._send_json(
                MessageBuilder.response_done(request_id, wire_response_id, metadata)
            )
            self._active.pop(request_id, None)

    async def legacy_cancel(self, response_id: str) -> None:
        async with self._lock:
            matches = [
                (request_id, active)
                for request_id, active in self._active.items()
                if active.owner is None and active.response_id == response_id
            ]
            if len(matches) != 1:
                detail = "no exact active legacy response match"
                if len(matches) > 1:
                    detail = "multiple exact active legacy response matches"
                raise self._state_error(
                    "cancel",
                    response_id=response_id,
                    detail=detail,
                )

            request_id, _ = matches[0]
            await self._send_json(MessageBuilder.response_cancel(response_id))
            self._active.pop(request_id, None)

    def _require_legacy_active(
        self,
        operation: str,
        request_id: str,
        response_id: str | None = None,
    ) -> _ActiveResponse:
        active = self._active.get(request_id)
        if active is None or active.owner is not None:
            raise self._state_error(
                operation,
                request_id,
                response_id,
                active=active,
                detail="no active legacy response",
            )
        return active

    def _require_owner_active(
        self,
        operation: str,
        owner: object,
    ) -> _ActiveResponse:
        request_id = getattr(owner, "_request_id", None)
        response_id = getattr(owner, "_response_id", None)
        active = self._active.get(request_id)
        if active is None or active.owner is not owner:
            raise self._state_error(
                operation,
                request_id,
                response_id,
                active,
                "response stream does not own the active response",
            )
        return active

    @staticmethod
    def _state_error(
        operation: str,
        request_id: str | None = None,
        response_id: str | None = None,
        active: _ActiveResponse | None = None,
        detail: str | None = None,
    ) -> ResponseStreamStateError:
        parts = [f"cannot {operation}"]
        if detail is not None:
            parts.append(detail)
        if request_id is not None:
            parts.append(f"request_id={request_id!r}")
        if response_id is not None:
            parts.append(f"response_id={response_id!r}")
        if active is not None:
            parts.append(f"active request_id={active.request_id!r}")
            parts.append(f"active response_id={active.response_id!r}")
        return ResponseStreamStateError(": ".join(parts))

    @staticmethod
    def _wire_response_id(
        operation: str,
        supplied: str,
        active: _ActiveResponse,
    ) -> str:
        if supplied != active.response_id:
            warnings.warn(
                f"{operation} supplied response_id {supplied!r}; "
                f"using active response_id {active.response_id!r}",
                DeprecationWarning,
                stacklevel=4,
            )
        return active.response_id
