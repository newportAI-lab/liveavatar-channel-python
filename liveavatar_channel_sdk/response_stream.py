"""Response stream lifecycle coordination."""

from __future__ import annotations

import asyncio
import warnings
from dataclasses import dataclass
from typing import Awaitable, Callable

from liveavatar_channel_sdk.message_builder import MessageBuilder


class ResponseStreamStateError(RuntimeError):
    """Raised when a response operation violates the active stream lifecycle."""


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
                stacklevel=3,
            )
        return active.response_id
