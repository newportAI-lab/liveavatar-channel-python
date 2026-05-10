"""
Live Avatar Channel Reference Server — Outbound Mode example.

This server demonstrates the **Outbound** WebSocket integration pattern:

  Developer registers a ``wsEndpoint`` (e.g. ``wss://my-host/avatar/ws``) in the
  Live Avatar console. After calling the platform's ``POST /session/start`` API,
  the **platform connects to this server** as a WebSocket client and initiates
  the protocol handshake with ``session.init``.

The server also includes a mock ``POST /avatar/session/start`` endpoint and a
platform-simulator WS endpoint so the Inbound client example can test against
it locally — no real platform required.

Endpoints
---------
``GET  /avatar/ws``                      Outbound mode developer WS endpoint
``POST /avatar/session/start``           Mock platform REST API (for local testing)
``GET  /avatar/platform-ws/{session_id}`` Platform simulator WS (for Inbound local testing)

Run with::

    uvicorn liveavatar_channel_server_example.main:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
import uuid
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from starlette.requests import Request

from liveavatar_channel_sdk.audio_frame import AudioFrame
from liveavatar_channel_sdk.avatar_channel_listener_adapter import AvatarChannelListenerAdapter
from liveavatar_channel_sdk.dispatch import dispatch_text_event
from liveavatar_channel_sdk.event_type import EventType
from liveavatar_channel_sdk.image_frame import ImageFrame
from liveavatar_channel_sdk.message_builder import MessageBuilder
from liveavatar_channel_sdk.session_manager import SessionManager
from liveavatar_channel_sdk.session_state import SessionState
from liveavatar_channel_sdk.websocket_adapter import WebSocketAdapter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("liveavatar.example")

app = FastAPI(title="Live Avatar Channel Reference Server (Outbound Mode)")
session_manager = SessionManager()

# ---------------------------------------------------------------------------
# Pydantic models for the mock REST endpoint
# ---------------------------------------------------------------------------


class SessionStartRequest(BaseModel):
    avatarId: str


class SessionStartData(BaseModel):
    sessionId: str
    sfuUrl: str
    userToken: str
    agentToken: str
    agentWsUrl: str


class SessionStartResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: SessionStartData


# ---------------------------------------------------------------------------
# Outbound mode — developer-side listener
# ---------------------------------------------------------------------------


class OutboundDeveloperListener(AvatarChannelListenerAdapter):
    """
    Handles protocol events received **from** the platform in Outbound mode.

    Direction convention in logs:
      ``<--``  Platform → Developer (received)
      ``-->``  Developer → Platform (sent via *send* helpers on the WS)
    """

    def __init__(self, adapter: WebSocketAdapter) -> None:
        self._adapter = adapter
        self._session_id: Optional[str] = None
        # Track active response streams so we can cancel them on interrupt.
        self._active_tasks: dict[str, asyncio.Task] = {}

    # ---- session events ---------------------------------------------------

    async def on_session_init(self, session_id: str, user_id: str) -> None:
        self._session_id = session_id
        logger.info("[%s] <-- session.init  user_id=%s", session_id, user_id)
        await session_manager.add_session(session_id, self._adapter._ws)
        await self._adapter.send_session_ready()
        logger.info("[%s] --> session.ready", session_id)

    async def on_session_ready(self) -> None:
        logger.info("[%s] <-- session.ready", self._session_id)

    async def on_session_state(self, state: SessionState, seq: int, timestamp: int) -> None:
        logger.info(
            "[%s] <-- session.state  state=%s  seq=%d  ts=%d",
            self._session_id,
            state.value,
            seq,
            timestamp,
        )

    async def on_session_closing(self, reason: Optional[str]) -> None:
        logger.info("[%s] <-- session.closing  reason=%s", self._session_id, reason)

    # ---- scene events -----------------------------------------------------

    async def on_scene_ready(self) -> None:
        logger.info("[%s] <-- scene.ready (LiveKit DataChannel)", self._session_id)

    # ---- input events — text ----------------------------------------------

    async def on_input_text(self, request_id: str, text: str) -> None:
        logger.info("[%s] <-- input.text  request_id=%s  text=%r", self._session_id, request_id, text)
        task = asyncio.ensure_future(self._echo_response(request_id, text))
        self._active_tasks[request_id] = task

    # ---- input events — ASR / voice (Platform ASR mode: received from platform) --

    async def on_asr_partial(self, request_id: str, text: str, seq: int) -> None:
        logger.info("[%s] <-- input.asr.partial  request_id=%s  seq=%d  text=%r", self._session_id, request_id, seq, text)

    async def on_asr_final(self, request_id: str, text: str) -> None:
        logger.info("[%s] <-- input.asr.final  request_id=%s  text=%r", self._session_id, request_id, text)

    async def on_voice_start(self, request_id: str) -> None:
        logger.info("[%s] <-- input.voice.start  request_id=%s", self._session_id, request_id)

    async def on_voice_finish(self, request_id: str) -> None:
        logger.info("[%s] <-- input.voice.finish  request_id=%s", self._session_id, request_id)

    # ---- response events (Platform TTS: received from platform) -----------

    async def on_response_start(self, request_id: str, response_id: str, audio_config: Optional[dict]) -> None:
        logger.info("[%s] <-- response.start  response_id=%s  audio_config=%s", self._session_id, response_id, audio_config)

    async def on_chunk_received(self, request_id: str, response_id: str, seq: int, text: str) -> None:
        logger.info("[%s] <-- response.chunk  response_id=%s  seq=%d  text=%r", self._session_id, response_id, seq, text)

    async def on_response_done(self, request_id: str, response_id: str) -> None:
        logger.info("[%s] <-- response.done  response_id=%s", self._session_id, response_id)

    async def on_response_audio_start(self, request_id: str, response_id: str) -> None:
        logger.info("[%s] <-- response.audio.start  response_id=%s", self._session_id, response_id)

    async def on_response_audio_finish(self, request_id: str, response_id: str) -> None:
        logger.info("[%s] <-- response.audio.finish  response_id=%s", self._session_id, response_id)

    async def on_response_audio_prompt_start(self) -> None:
        logger.info("[%s] <-- response.audio.promptStart", self._session_id)

    async def on_response_audio_prompt_finish(self) -> None:
        logger.info("[%s] <-- response.audio.promptFinish", self._session_id)

    async def on_response_cancel(self, response_id: str) -> None:
        logger.info("[%s] <-- response.cancel  response_id=%s", self._session_id, response_id)

    # ---- control / system -------------------------------------------------

    async def on_control_interrupt(self, request_id: Optional[str]) -> None:
        logger.info("[%s] <-- control.interrupt  request_id=%s", self._session_id, request_id)
        if request_id and request_id in self._active_tasks:
            self._active_tasks[request_id].cancel()

    async def on_idle_trigger(self, reason: str, idle_time_ms: int) -> None:
        logger.info("[%s] <-- system.idleTrigger  reason=%s  idle_time_ms=%d", self._session_id, reason, idle_time_ms)

    async def on_system_prompt(self, text: str) -> None:
        logger.info("[%s] <-- system.prompt  text=%r", self._session_id, text)

    async def on_error(self, request_id: Optional[str], code: str, message: str) -> None:
        logger.error("[%s] <-- error  request_id=%s  code=%s  message=%s", self._session_id, request_id, code, message)

    # ---- binary frames ----------------------------------------------------

    async def on_audio_frame(self, frame: AudioFrame) -> None:
        logger.debug(
            "[%s] <-- audio frame  seq=%d  ts=%d  codec=%s  len=%d",
            self._session_id,
            frame.seq,
            frame.timestamp,
            frame.codec_name,
            len(frame.payload),
        )

    async def on_image_frame(self, frame: ImageFrame) -> None:
        logger.debug(
            "[%s] <-- image frame  id=%d  %dx%d  fmt=%d  len=%d",
            self._session_id,
            frame.image_id,
            frame.width,
            frame.height,
            frame.format,
            len(frame.payload),
        )

    # ---- internal helpers --------------------------------------------------

    async def _echo_response(self, request_id: str, text: str) -> None:
        """Stream echoed text back as response chunks (one word per chunk)."""
        response_id = str(uuid.uuid4())
        words = text.split()
        if not words:
            words = [text]

        await self._adapter.send_response_start(request_id, response_id)
        logger.info("[%s] --> response.start  response_id=%s", self._session_id, response_id)

        for seq, word in enumerate(words):
            ts = int(time.monotonic() * 1000) & 0xFFFFF
            await self._adapter.send_response_chunk(request_id, response_id, seq, ts, word + " ")
            logger.info("[%s] --> response.chunk  response_id=%s  seq=%d", self._session_id, response_id, seq)
            await asyncio.sleep(0.05)

        await self._adapter.send_response_done(request_id, response_id)
        logger.info("[%s] --> response.done  response_id=%s", self._session_id, response_id)
        self._active_tasks.pop(request_id, None)


# ---------------------------------------------------------------------------
# Mock platform REST endpoint — simulates POST /session/start
# ---------------------------------------------------------------------------


@app.post("/avatar/session/start", response_model=SessionStartResponse)
async def session_start(body: SessionStartRequest, request: Request) -> SessionStartResponse:
    """
    Simulate the platform's ``POST /v1/session/start`` for local testing.

    Returns a mock response whose ``agentWsUrl`` points back to this server's
    platform-simulator WS endpoint.
    """
    auth = request.headers.get("Authorization", "Bearer <none>")
    session_id = "sess_" + secrets.token_hex(6)
    host = request.headers.get("host", "localhost:8080")
    scheme = "wss" if request.url.scheme == "https" else "ws"

    logger.info(
        "REST ← POST /session/start  avatarId=%s  auth=%s…  → sessionId=%s",
        body.avatarId,
        auth[:30],
        session_id,
    )

    return SessionStartResponse(
        data=SessionStartData(
            sessionId=session_id,
            sfuUrl="wss://sfu.example.com/livekit",
            userToken="mock-user-token-" + secrets.token_hex(4),
            agentToken="mock-agent-token-" + secrets.token_hex(4),
            agentWsUrl=f"{scheme}://{host}/avatar/platform-ws/{session_id}",
        )
    )


# ---------------------------------------------------------------------------
# Outbound mode WS endpoint — platform connects here
# ---------------------------------------------------------------------------


@app.websocket("/avatar/ws")
async def avatar_outbound_ws(ws: WebSocket) -> None:
    """
    **Outbound mode** developer WS endpoint.

    The platform connects to this endpoint after the developer calls
    ``POST /session/start`` and the platform resolves the registered
    ``wsEndpoint``.
    """
    await ws.accept()
    logger.info("Outbound WS connection from %s", ws.client)

    adapter = WebSocketAdapter(ws)
    listener = OutboundDeveloperListener(adapter)

    try:
        async for raw in ws.iter_text():
            await dispatch_text_event(raw, listener)
    except WebSocketDisconnect:
        logger.info("Outbound WS disconnected")
    finally:
        if listener._session_id:
            await session_manager.remove_session(listener._session_id)


# ---------------------------------------------------------------------------
# Platform simulator WS endpoint — used by the Inbound client for local testing
# ---------------------------------------------------------------------------


@app.websocket("/avatar/platform-ws/{session_id}")
async def avatar_platform_simulator_ws(ws: WebSocket, session_id: str) -> None:
    """
    Platform simulator WS endpoint for local Inbound-mode testing.

    This endpoint acts as the platform: it sends ``session.init``, waits for
    ``session.ready``, sends a test ``input.text``, and logs the developer's
    response.
    """
    await ws.accept()
    logger.info("[%s] Platform simulator: developer connected", session_id)

    user_id = "test-user-" + secrets.token_hex(4)

    try:
        # 1. Send session.init
        await ws.send_text(json.dumps(MessageBuilder.session_init(session_id, user_id)))
        logger.info("[%s] --> session.init  user_id=%s", session_id, user_id)

        # 2. Wait for session.ready
        raw = await asyncio.wait_for(ws.receive_text(), timeout=10.0)
        msg = json.loads(raw)
        if msg.get("event") == EventType.SESSION_READY:
            logger.info("[%s] <-- session.ready", session_id)
        else:
            logger.warning("[%s] Expected session.ready, got %s", session_id, msg.get("event"))

        # 3. Send session.state
        state_msg = MessageBuilder.session_state(
            SessionState.LISTENING.value,
            seq=1,
            timestamp=int(time.time() * 1000),
        )
        await ws.send_text(json.dumps(state_msg))
        logger.info("[%s] --> session.state  state=LISTENING", session_id)

        # 4. Send input.text
        request_id = str(uuid.uuid4())
        test_text = "Hello! Tell me about yourself in a few words."
        await ws.send_text(json.dumps(MessageBuilder.input_text(request_id, test_text)))
        logger.info("[%s] --> input.text  request_id=%s  text=%r", session_id, request_id, test_text)

        # 5. Receive and log response events
        response_text: list[str] = []
        while True:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=15.0)
            msg = json.loads(raw)
            event = msg.get("event")
            data = msg.get("data", {})

            if event == EventType.RESPONSE_START:
                logger.info(
                    "[%s] <-- response.start  response_id=%s",
                    session_id,
                    msg.get("responseId"),
                )
            elif event == EventType.RESPONSE_CHUNK:
                chunk = data.get("text", "")
                response_text.append(chunk)
                logger.info(
                    "[%s] <-- response.chunk  seq=%d  text=%r",
                    session_id,
                    msg.get("seq"),
                    chunk,
                )
            elif event == EventType.RESPONSE_DONE:
                logger.info(
                    "[%s] <-- response.done  full_text=%r",
                    session_id,
                    "".join(response_text),
                )
                break
            elif event == EventType.ERROR:
                logger.error(
                    "[%s] <-- error  code=%s  message=%s",
                    session_id,
                    data.get("code"),
                    data.get("message"),
                )
                break
            else:
                logger.debug("[%s] <-- %s (unexpected in this flow)", session_id, event)

    except asyncio.TimeoutError:
        logger.warning("[%s] Platform simulator: timeout waiting for message", session_id)
    except WebSocketDisconnect:
        logger.info("[%s] Platform simulator: developer disconnected", session_id)
    except Exception as exc:
        logger.error("[%s] Platform simulator error: %s", session_id, exc)


