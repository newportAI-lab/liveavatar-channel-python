"""Streaming system prompt API."""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from liveavatar_channel_sdk.message_builder import MessageBuilder
from liveavatar_channel_sdk.response_lifecycle import (
    _PendingResponse,
    _ResponseLifecycleCoordinator,
)
from liveavatar_channel_sdk.response_state import ResponseStateEvent


class PromptStreamStateError(RuntimeError):
    """Raised when an operation violates the prompt stream lifecycle."""


class PromptStream:
    """A response-correlated streaming ``system.prompt`` producer."""

    def __init__(
        self,
        lifecycle: _ResponseLifecycleCoordinator,
        send_json: Callable[[dict], Awaitable[None]],
        session_id: Callable[[], str | None],
        request_id: str,
        response_id: str,
    ) -> None:
        self._lifecycle = lifecycle
        self._send_json = send_json
        self._session_id = session_id
        self._request_id = request_id
        self._response_id = response_id
        self._lock = asyncio.Lock()
        self._entered = False
        self._closed = False
        self._next_seq = 1
        self._pending: _PendingResponse | None = None

    @property
    def request_id(self) -> str:
        return self._request_id

    @property
    def response_id(self) -> str:
        return self._response_id

    @property
    def is_finished(self) -> bool:
        return self._pending is not None and self._pending.is_finished

    async def __aenter__(self) -> PromptStream:
        async with self._lock:
            if self._entered:
                raise PromptStreamStateError("prompt stream cannot be entered twice")
            session_id = self._session_id()
            if session_id is None:
                raise RuntimeError("Not connected — call start() first")
            pending = await self._lifecycle.register(
                session_id, self._request_id, self._response_id
            )
            try:
                await self._send_json(
                    MessageBuilder.system_prompt_start(self._request_id, self._response_id)
                )
            except BaseException:
                await self._lifecycle.rollback(pending)
                raise
            self._pending = pending
            self._entered = True
            return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        if exc is None:
            await self.done()
        else:
            async with self._lock:
                self._closed = True
        return False

    async def send(self, text: str, *, timestamp: int | None = None) -> None:
        async with self._lock:
            self._require_open("send")
            actual_timestamp = time.time_ns() // 1_000_000 if timestamp is None else timestamp
            await self._send_json(
                MessageBuilder.system_prompt_chunk(
                    self._request_id,
                    self._response_id,
                    self._next_seq,
                    actual_timestamp,
                    text,
                )
            )
            self._next_seq += 1

    async def done(self) -> None:
        async with self._lock:
            self._require_open("finish")
            await self._send_json(
                MessageBuilder.system_prompt_done(self._request_id, self._response_id)
            )
            self._closed = True

    async def wait_finished(self) -> ResponseStateEvent:
        if self._pending is None:
            raise PromptStreamStateError(
                "cannot wait for completion: prompt stream has not been entered"
            )
        return await self._pending.wait_finished()

    def _require_open(self, operation: str) -> None:
        if not self._entered:
            raise PromptStreamStateError(
                f"cannot {operation}: prompt stream has not been entered"
            )
        if self._closed:
            raise PromptStreamStateError(f"cannot {operation}: prompt stream is closed")
