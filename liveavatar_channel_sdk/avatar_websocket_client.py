"""
AvatarWebSocketClient — manages WebSocket lifecycle for the Live Avatar Channel SDK.

Supports both connection modes:
  - Outbound: developer's server exposes a stable public endpoint; avatar service connects to it.
  - Inbound:  avatar service provides the WebSocket URL; developer connects as a client.

Usage (outbound/inbound are symmetric from the client's perspective — pass any ws:// URL):

    client = AvatarWebSocketClient(url, listener)
    await client.enable_auto_reconnect()   # optional
    await client.connect()
    await client.send_session_ready()
    await client.send_response_chunk(request_id, response_id, seq, ts, text)
    await client.disconnect()
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import websockets
from websockets.exceptions import ConnectionClosed

from liveavatar_channel_sdk.audio_frame import AudioFrame
from liveavatar_channel_sdk.avatar_channel_listener import AvatarChannelListener
from liveavatar_channel_sdk.dispatch import dispatch_text_event
from liveavatar_channel_sdk.exponential_backoff_strategy import ExponentialBackoffStrategy
from liveavatar_channel_sdk.image_frame import ImageFrame
from liveavatar_channel_sdk.message_sender import MessageSender
from liveavatar_channel_sdk.streaming_response_handler import StreamingResponseHandler

logger = logging.getLogger(__name__)

_AUDIO_TYPE_BITS = 0b01
_IMAGE_TYPE_BITS = 0b10


def _frame_type(data: bytes) -> int:
    """Return the 2-bit type field from the MSB of the first byte."""
    return (data[0] >> 6) & 0x3


class AvatarWebSocketClient(MessageSender):
    """
    Manages the WebSocket connection lifecycle and protocol event dispatch.

    Args:
        url: WebSocket endpoint URL (ws:// or wss://).
        listener: AvatarChannelListener implementation for protocol event callbacks.
    """

    def __init__(self, url: str, listener: AvatarChannelListener) -> None:
        self._url = url
        self._listener = listener
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._backoff: Optional[ExponentialBackoffStrategy] = None
        self._running = False
        self._streaming = StreamingResponseHandler(
            on_chunk_received=listener.on_chunk_received,
            on_response_done=listener.on_response_done,
        )

    # ------------------------------------------------------------------
    # Public API — lifecycle
    # ------------------------------------------------------------------

    async def enable_auto_reconnect(
        self,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ) -> None:
        """Enable automatic reconnection with exponential backoff (opt-in)."""
        self._backoff = ExponentialBackoffStrategy(base_delay, max_delay)

    async def connect(self) -> None:
        """
        Connect to the WebSocket server and start receiving messages.

        If auto-reconnect is enabled, keeps retrying on disconnection until
        :meth:`disconnect` is called.
        """
        self._running = True
        await self._connect_once()

        if self._backoff is not None:
            asyncio.ensure_future(self._reconnect_loop())

    async def disconnect(self) -> None:
        """Close the connection and stop the receive loop."""
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

    # ------------------------------------------------------------------
    # MessageSender abstract method implementations
    # ------------------------------------------------------------------

    async def send_json(self, message: dict) -> None:
        """Serialise *message* as JSON and send it over the WebSocket."""
        if self._ws is None:
            raise RuntimeError("Not connected")
        await self._ws.send(json.dumps(message))

    async def send_binary(self, data: bytes) -> None:
        """Send raw binary data (audio/image frames)."""
        if self._ws is None:
            raise RuntimeError("Not connected")
        await self._ws.send(data)

    # ------------------------------------------------------------------
    # Internal — connection helpers
    # ------------------------------------------------------------------

    async def _connect_once(self) -> None:
        self._ws = await websockets.connect(self._url, ping_interval=5)
        if self._backoff is not None:
            self._backoff.reset()
        self._recv_task = asyncio.ensure_future(self._recv_loop())
        logger.info("Connected to %s", self._url)

    async def _reconnect_loop(self) -> None:
        """Wait for the recv task to finish, then reconnect if still running."""
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
            logger.info("Reconnecting in %.1f s …", delay)
            await self._backoff.wait()

            if not self._running:
                break

            try:
                await self._connect_once()
            except Exception as exc:
                logger.warning("Reconnect failed: %s", exc)

    # ------------------------------------------------------------------
    # Internal — receive loop
    # ------------------------------------------------------------------

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            async for message in self._ws:
                if isinstance(message, str):
                    await dispatch_text_event(message, self._listener, self._streaming)
                elif isinstance(message, bytes):
                    await self._dispatch_binary(message)
        except ConnectionClosed as exc:
            logger.info("Connection closed: %s", exc)
        except Exception as exc:
            logger.error("Receive loop error: %s", exc)

    # ------------------------------------------------------------------
    # Internal — dispatch binary frames
    # ------------------------------------------------------------------

    async def _dispatch_binary(self, data: bytes) -> None:
        if len(data) < 1:
            return
        frame_type = _frame_type(data)
        try:
            if frame_type == _AUDIO_TYPE_BITS:
                frame = AudioFrame.unpack(data)
                await self._listener.on_audio_frame(frame)
            elif frame_type == _IMAGE_TYPE_BITS:
                frame = ImageFrame.unpack(data)
                await self._listener.on_image_frame(frame)
            else:
                logger.warning("Unknown binary frame type bits: 0b%02b", frame_type)
        except Exception as exc:
            logger.error("Error dispatching binary frame (type 0b%02b): %s", frame_type, exc)
