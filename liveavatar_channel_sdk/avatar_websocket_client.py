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
from liveavatar_channel_sdk.event_type import EventType
from liveavatar_channel_sdk.exponential_backoff_strategy import ExponentialBackoffStrategy
from liveavatar_channel_sdk.image_frame import ImageFrame
from liveavatar_channel_sdk.message_builder import MessageBuilder
from liveavatar_channel_sdk.session_state import SessionState
from liveavatar_channel_sdk.streaming_response_handler import StreamingResponseHandler

logger = logging.getLogger(__name__)

_AUDIO_TYPE_BITS = 0b01
_IMAGE_TYPE_BITS = 0b10


def _frame_type(data: bytes) -> int:
    """Return the 2-bit type field from the MSB of the first byte."""
    return (data[0] >> 6) & 0x3


class AvatarWebSocketClient:
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
            # Schedule the reconnect loop as a background task.
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
    # Public API — send helpers (developer → avatar)
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

    # Convenience wrappers for common outgoing messages:

    async def send_session_ready(self) -> None:
        await self.send_json(MessageBuilder.session_ready())

    async def send_scene_ready(self) -> None:
        """scene.ready — LiveKit DataChannel only; sent by the JS SDK to signal
        the frontend scene is ready for conversation."""
        await self.send_json(MessageBuilder.scene_ready())

    # Scenario 2B (Developer ASR / Omni): the developer runs ASR+VAD
    # internally and sends the input.voice.* / input.asr.* events back to
    # the platform. Protocol shape is identical to Scenario 2A, direction
    # is reversed.

    async def send_input_voice_start(self, request_id: str) -> None:
        await self.send_json(MessageBuilder.input_voice_start(request_id))

    async def send_input_voice_finish(self, request_id: str) -> None:
        await self.send_json(MessageBuilder.input_voice_finish(request_id))

    async def send_input_asr_partial(self, request_id: str, text: str, seq: int) -> None:
        await self.send_json(MessageBuilder.input_asr_partial(request_id, text, seq))

    async def send_input_asr_final(self, request_id: str, text: str) -> None:
        await self.send_json(MessageBuilder.input_asr_final(request_id, text))

    async def send_response_start(
        self,
        request_id: str,
        response_id: str,
        speed: float = 1.0,
        volume: float = 1.0,
        mood: Optional[str] = None,
    ) -> None:
        await self.send_json(
            MessageBuilder.response_start(request_id, response_id, speed, volume, mood)
        )

    async def send_response_chunk(
        self,
        request_id: str,
        response_id: str,
        seq: int,
        timestamp: int,
        text: str,
    ) -> None:
        await self.send_json(
            MessageBuilder.response_chunk(request_id, response_id, seq, timestamp, text)
        )

    async def send_response_done(self, request_id: str, response_id: str) -> None:
        await self.send_json(MessageBuilder.response_done(request_id, response_id))

    async def send_response_cancel(self, response_id: str) -> None:
        await self.send_json(MessageBuilder.response_cancel(response_id))

    async def send_control_interrupt(self, request_id: Optional[str] = None) -> None:
        await self.send_json(MessageBuilder.control_interrupt(request_id))

    async def send_system_prompt(self, text: str) -> None:
        await self.send_json(MessageBuilder.system_prompt(text))

    async def send_error(self, code: str, message: str, request_id: Optional[str] = None) -> None:
        await self.send_json(MessageBuilder.error(code, message, request_id))

    async def send_audio_frame(self, frame: AudioFrame) -> None:
        await self.send_binary(frame.pack())

    async def send_image_frame(self, frame: ImageFrame) -> None:
        await self.send_binary(frame.pack())

    # ------------------------------------------------------------------
    # Internal — connection helpers
    # ------------------------------------------------------------------

    async def _connect_once(self) -> None:
        self._ws = await websockets.connect(self._url)
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
                    await self._dispatch_text(message)
                elif isinstance(message, bytes):
                    await self._dispatch_binary(message)
        except ConnectionClosed as exc:
            logger.info("Connection closed: %s", exc)
        except Exception as exc:
            logger.error("Receive loop error: %s", exc)

    # ------------------------------------------------------------------
    # Internal — dispatch text messages
    # ------------------------------------------------------------------

    async def _dispatch_text(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Received non-JSON text message: %.120s", raw)
            return

        event_type = msg.get("event")
        data = msg.get("data", {})
        listener = self._listener

        try:
            if event_type == EventType.SESSION_INIT:
                await listener.on_session_init(
                    session_id=data["sessionId"],
                    user_id=data["userId"],
                )

            elif event_type == EventType.SESSION_READY:
                await listener.on_session_ready()

            elif event_type == EventType.SESSION_STATE:
                state = SessionState(data["state"])
                await listener.on_session_state(
                    state=state,
                    seq=msg["seq"],
                    timestamp=msg["timestamp"],
                )

            elif event_type == EventType.SESSION_CLOSING:
                await listener.on_session_closing(reason=data.get("reason"))

            elif event_type == EventType.SCENE_READY:
                await listener.on_scene_ready()

            elif event_type == EventType.INPUT_TEXT:
                await listener.on_input_text(
                    request_id=msg["requestId"],
                    text=data["text"],
                )

            elif event_type == EventType.INPUT_ASR_PARTIAL:
                await listener.on_asr_partial(
                    request_id=msg["requestId"],
                    text=data["text"],
                    seq=msg["seq"],
                )

            elif event_type == EventType.INPUT_ASR_FINAL:
                await listener.on_asr_final(
                    request_id=msg["requestId"],
                    text=data["text"],
                )

            elif event_type == EventType.INPUT_VOICE_START:
                await listener.on_voice_start(request_id=msg["requestId"])

            elif event_type == EventType.INPUT_VOICE_FINISH:
                await listener.on_voice_finish(request_id=msg["requestId"])

            elif event_type == EventType.RESPONSE_START:
                await listener.on_response_start(
                    request_id=msg["requestId"],
                    response_id=msg["responseId"],
                    audio_config=data.get("audioConfig"),
                )

            elif event_type == EventType.RESPONSE_CHUNK:
                await self._streaming.handle_chunk(
                    request_id=msg["requestId"],
                    response_id=msg["responseId"],
                    seq=msg["seq"],
                    text=data["text"],
                )

            elif event_type == EventType.RESPONSE_DONE:
                await self._streaming.handle_done(
                    request_id=msg["requestId"],
                    response_id=msg["responseId"],
                )

            elif event_type == EventType.RESPONSE_AUDIO_START:
                await listener.on_response_audio_start(
                    request_id=msg["requestId"],
                    response_id=msg["responseId"],
                )

            elif event_type == EventType.RESPONSE_AUDIO_FINISH:
                await listener.on_response_audio_finish(
                    request_id=msg["requestId"],
                    response_id=msg["responseId"],
                )

            elif event_type == EventType.RESPONSE_AUDIO_PROMPT_START:
                await listener.on_response_audio_prompt_start()

            elif event_type == EventType.RESPONSE_AUDIO_PROMPT_FINISH:
                await listener.on_response_audio_prompt_finish()

            elif event_type == EventType.RESPONSE_CANCEL:
                self._streaming.clear(msg.get("responseId"))
                await listener.on_response_cancel(response_id=msg["responseId"])

            elif event_type == EventType.CONTROL_INTERRUPT:
                await listener.on_control_interrupt(request_id=msg.get("requestId"))

            elif event_type == EventType.SYSTEM_IDLE_TRIGGER:
                await listener.on_idle_trigger(
                    reason=data["reason"],
                    idle_time_ms=data["idleTimeMs"],
                )

            elif event_type == EventType.SYSTEM_PROMPT:
                await listener.on_system_prompt(text=data["text"])

            elif event_type == EventType.ERROR:
                await listener.on_error(
                    request_id=msg.get("requestId"),
                    code=data["code"],
                    message=data["message"],
                )

            else:
                logger.warning("Unknown event type: %s", event_type)

        except Exception as exc:
            logger.error("Error dispatching %s: %s", event_type, exc)

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
