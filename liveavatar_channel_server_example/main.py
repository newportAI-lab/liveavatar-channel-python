"""
Reference FastAPI/ASGI server for the Live Avatar Channel SDK.

Exposes a single WebSocket endpoint:
    ws://localhost:8080/avatar/ws

The avatar service connects to this endpoint (outbound mode).
For each connection the server:
  1. Waits for session.init
  2. Responds with session.ready
  3. Echoes input.text back as a streaming response (response.chunk + response.done)
  4. Handles control.interrupt and error events

Run with:
    uvicorn liveavatar_channel_server_example.main:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from liveavatar_channel_sdk.avatar_channel_listener_adapter import AvatarChannelListenerAdapter
from liveavatar_channel_sdk.audio_frame import AudioFrame
from liveavatar_channel_sdk.image_frame import ImageFrame
from liveavatar_channel_sdk.message_builder import MessageBuilder
from liveavatar_channel_sdk.session_manager import SessionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Live Avatar Channel Reference Server")
session_manager = SessionManager()


# ---------------------------------------------------------------------------
# Listener implementation
# ---------------------------------------------------------------------------

class EchoListener(AvatarChannelListenerAdapter):
    """
    Minimal listener that echoes text input back as a streaming response.

    One instance is created per WebSocket connection.
    """

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws
        self._session_id: Optional[str] = None

    async def _send(self, msg: dict) -> None:
        await self._ws.send_text(json.dumps(msg))

    async def on_session_init(self, session_id: str, user_id: str) -> None:
        self._session_id = session_id
        logger.info("[%s] session.init  user=%s", session_id, user_id)
        await session_manager.add_session(session_id, self._ws)
        await self._send(MessageBuilder.session_ready())

    async def on_session_closing(self, reason: Optional[str]) -> None:
        logger.info("[%s] session.closing  reason=%s", self._session_id, reason)

    async def on_input_text(self, request_id: str, text: str) -> None:
        logger.info("[%s] input.text  request_id=%s  text=%r", self._session_id, request_id, text)
        asyncio.ensure_future(self._echo_response(request_id, text))

    async def on_control_interrupt(self, request_id: Optional[str]) -> None:
        logger.info("[%s] control.interrupt  request_id=%s", self._session_id, request_id)

    async def on_error(self, request_id: Optional[str], code: str, message: str) -> None:
        logger.error("[%s] error  code=%s  message=%s", self._session_id, code, message)

    async def on_audio_frame(self, frame: AudioFrame) -> None:
        logger.debug("[%s] audio frame  seq=%d  ts=%d", self._session_id, frame.seq, frame.timestamp)

    async def on_image_frame(self, frame: ImageFrame) -> None:
        logger.debug("[%s] image frame  id=%d  %dx%d", self._session_id, frame.image_id, frame.width, frame.height)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _echo_response(self, request_id: str, text: str) -> None:
        """Stream the echoed text back one word per chunk."""
        response_id = str(uuid.uuid4())
        words = text.split()
        if not words:
            words = [text]

        await self._send(MessageBuilder.response_start(request_id, response_id))

        import time
        for seq, word in enumerate(words):
            ts = int(time.monotonic() * 1000) & 0xFFFFF
            await self._send(MessageBuilder.response_chunk(request_id, response_id, seq, ts, word + " "))
            await asyncio.sleep(0.05)  # simulate TTS pacing

        await self._send(MessageBuilder.response_done(request_id, response_id))


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/avatar/ws")
async def avatar_ws(ws: WebSocket) -> None:
    await ws.accept()
    logger.info("New WebSocket connection from %s", ws.client)

    listener = EchoListener(ws)
    session_id: Optional[str] = None

    try:
        async for raw in ws.iter_text():
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Non-JSON message received")
                continue

            event_type = msg.get("event")
            data = msg.get("data", {})

            # Dispatch to listener
            if event_type == "session.init":
                session_id = data.get("sessionId", "")
                await listener.on_session_init(
                    session_id=session_id,
                    user_id=data.get("userId", ""),
                )
            elif event_type == "input.text":
                await listener.on_input_text(
                    request_id=msg.get("requestId", ""),
                    text=data.get("text", ""),
                )
            elif event_type == "session.closing":
                await listener.on_session_closing(reason=data.get("reason"))
            elif event_type == "control.interrupt":
                await listener.on_control_interrupt(request_id=msg.get("requestId"))
            elif event_type == "error":
                await listener.on_error(
                    request_id=msg.get("requestId"),
                    code=data.get("code", ""),
                    message=data.get("message", ""),
                )
            else:
                logger.debug("Unhandled event type: %s", event_type)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    finally:
        if session_id:
            await session_manager.remove_session(session_id)
