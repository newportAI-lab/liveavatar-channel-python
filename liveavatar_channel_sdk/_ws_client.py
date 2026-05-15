"""Internal WebSocket transport for AvatarAgent.

Handles connect, receive loop, text/binary event routing, auto-reconnect.
Not part of the public API — use AvatarAgent instead.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional, Protocol

import websockets
from websockets.exceptions import ConnectionClosed

from liveavatar_channel_sdk.audio_frame import AudioFrame
from liveavatar_channel_sdk.event_type import EventType
from liveavatar_channel_sdk.exponential_backoff_strategy import ExponentialBackoffStrategy
from liveavatar_channel_sdk.message_builder import MessageBuilder
from liveavatar_channel_sdk.session_state import SessionState

logger = logging.getLogger(__name__)

_AUDIO_TYPE_BITS = 0b01
_IMAGE_TYPE_BITS = 0b10


def _frame_type(data: bytes) -> int:
    return (data[0] >> 6) & 0x3


class _AgentCallbacks(Protocol):
    """Internal protocol matching the callbacks the WS client routes to."""

    async def on_session_init(self, session_id: str, user_id: str) -> None: ...
    async def on_session_state(self, state: SessionState) -> None: ...
    async def on_session_closing(self, reason: str | None) -> None: ...
    async def on_text_input(self, text: str, request_id: str) -> None: ...
    async def on_idle_trigger(self, reason: str, idle_time_ms: int) -> None: ...
    async def on_error(self, code: str, message: str) -> None: ...
    async def on_audio_frame(self, frame: AudioFrame) -> None: ...
    async def on_closed(self, code: int, reason: str) -> None: ...


class _AvatarWsClient:
    """Internal WebSocket client (Inbound mode).

    Args:
        url: WebSocket endpoint URL (ws:// or wss://).
        callbacks: Object implementing the _AgentCallbacks protocol.
        session_init_event: asyncio.Event set when session.init is received.
    """

    def __init__(
        self,
        url: str,
        callbacks: _AgentCallbacks,
        session_init_event: asyncio.Event,
    ) -> None:
        self._url = url
        self._callbacks = callbacks
        self._session_init_event = session_init_event
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._running = False
        self._backoff: Optional[ExponentialBackoffStrategy] = None

    async def send_json(self, message: dict) -> None:
        if self._ws is None:
            raise RuntimeError("Not connected")
        await self._ws.send(json.dumps(message))

    async def send_binary(self, data: bytes) -> None:
        if self._ws is None:
            raise RuntimeError("Not connected")
        await self._ws.send(data)

    # -- lifecycle ----------------------------------------------------------

    async def connect(self, *, reconnect: bool = False) -> None:
        self._running = True
        if reconnect:
            self._backoff = ExponentialBackoffStrategy()
        await self._connect_once()
        if self._backoff is not None:
            asyncio.ensure_future(self._reconnect_loop())

    async def disconnect(self) -> None:
        self._running = False
        if self._recv_task is not None and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    # -- internal connect ---------------------------------------------------

    async def _connect_once(self) -> None:
        self._ws = await websockets.connect(self._url, ping_interval=5)
        if self._backoff is not None:
            self._backoff.reset()
        self._recv_task = asyncio.ensure_future(self._recv_loop())
        logger.info("Connected to %s", self._url)

    async def _reconnect_loop(self) -> None:
        while self._running:
            if self._recv_task is not None:
                try:
                    await self._recv_task
                except (asyncio.CancelledError, Exception):
                    pass

            if not self._running:
                break

            assert self._backoff is not None
            delay = self._backoff.next_delay
            logger.info("Reconnecting in %.1f s ...", delay)
            await self._backoff.wait()

            if not self._running:
                break

            try:
                await self._connect_once()
            except Exception as exc:
                logger.warning("Reconnect failed: %s", exc)

    # -- receive loop -------------------------------------------------------

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            async for message in self._ws:
                if isinstance(message, str):
                    await self._handle_text(message)
                elif isinstance(message, bytes):
                    await self._handle_binary(message)
        except ConnectionClosed as exc:
            logger.info("Connection closed: %s", exc)
            await self._callbacks.on_closed(exc.code, exc.reason or "")
        except Exception as exc:
            logger.error("Receive loop error: %s", exc)

    # -- text dispatch (Inbound mode only) ----------------------------------

    async def _handle_text(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Received non-JSON text: %.120s", raw)
            return

        event_type = msg.get("event")
        data = msg.get("data", {})

        try:
            if event_type == EventType.SESSION_INIT:
                # Auto handshake
                await self.send_json(MessageBuilder.session_ready())
                await self._callbacks.on_session_init(
                    session_id=data["sessionId"],
                    user_id=data["userId"],
                )
                self._session_init_event.set()

            elif event_type == EventType.SESSION_STATE:
                await self._callbacks.on_session_state(
                    state=SessionState(data["state"])
                )

            elif event_type == EventType.SESSION_CLOSING:
                await self._callbacks.on_session_closing(
                    reason=data.get("reason")
                )

            elif event_type == EventType.INPUT_TEXT:
                await self._callbacks.on_text_input(
                    text=data["text"],
                    request_id=msg["requestId"],
                )

            elif event_type == EventType.SYSTEM_IDLE_TRIGGER:
                await self._callbacks.on_idle_trigger(
                    reason=data["reason"],
                    idle_time_ms=data["idleTimeMs"],
                )

            elif event_type == EventType.ERROR:
                await self._callbacks.on_error(
                    code=data["code"],
                    message=data["message"],
                )

            elif event_type == EventType.SCENE_READY:
                logger.debug("Received scene.ready (no-op in Agent mode)")

            else:
                logger.warning("Unhandled event in Agent mode: %s", event_type)

        except Exception as exc:
            logger.error("Error handling event %s: %s", event_type, exc)

    # -- binary dispatch ----------------------------------------------------

    async def _handle_binary(self, data: bytes) -> None:
        if len(data) < 1:
            return
        try:
            ft = _frame_type(data)
            if ft == _AUDIO_TYPE_BITS:
                frame = AudioFrame.unpack(data)
                await self._callbacks.on_audio_frame(frame)
            elif ft == _IMAGE_TYPE_BITS:
                logger.debug("Received image frame (ignored in Agent mode)")
            else:
                logger.warning("Unknown binary frame type: 0b%02b", ft)
        except Exception as exc:
            logger.error("Error dispatching binary frame: %s", exc)
