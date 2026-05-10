"""
Live Avatar Inbound Mode Client Example.

This script demonstrates the **Inbound** WebSocket integration pattern:

  1. Call ``POST /session/start`` (REST API) with an API Key to initiate a session.
  2. Extract ``agentWsUrl`` from the response — this is the platform's WebSocket
     endpoint for this session (embeds a one-time token).
  3. Connect to ``agentWsUrl`` as a WebSocket client.
  4. The **platform** sends ``session.init`` — reply with ``session.ready``.
  5. Receive ``input.text`` / ``input.asr.*`` / ``session.state`` / etc.
     from the platform.
  6. Send ``response.chunk`` / ``response.done`` (or binary audio frames)
     back to the platform.

From the developer's perspective the event directions are::

    <--  Platform → Developer  (received via listener callbacks)
    -->  Developer → Platform  (sent via client.send_* helpers)

For local testing, run the reference server first, then this script::

    # Terminal 1
    uvicorn liveavatar_channel_server_example.main:app --host 0.0.0.0 --port 8080

    # Terminal 2
    python -m liveavatar_channel_sdk.example.live_avatar_service_simulator

Configuration via environment variables::

    PLATFORM_URL   Base URL of the platform (default: http://localhost:8080)
    API_KEY        API Key for Authorization header (default: sk-local-test-key)
    AVATAR_ID      Avatar ID to start a session for (default: default-avatar)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Optional
from liveavatar_channel_sdk.audio_frame import AudioFrame
from liveavatar_channel_sdk.avatar_channel_listener_adapter import AvatarChannelListenerAdapter
from liveavatar_channel_sdk.avatar_websocket_client import AvatarWebSocketClient
from liveavatar_channel_sdk.image_frame import ImageFrame
from liveavatar_channel_sdk.session_client import SessionClient
from liveavatar_channel_sdk.session_state import SessionState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PLATFORM_URL = os.environ.get("PLATFORM_URL", "http://localhost:8080")
API_KEY = os.environ.get("API_KEY", "sk-local-test-key")
AVATAR_ID = os.environ.get("AVATAR_ID", "default-avatar")


# ---------------------------------------------------------------------------
# Inbound mode — developer-side listener
# ---------------------------------------------------------------------------


class InboundDeveloperListener(AvatarChannelListenerAdapter):
    """
    Handles protocol events received **from** the platform in Inbound mode.

    Direction convention in logs:
      ``<--``  Platform → Developer (received)
      ``-->``  Developer → Platform (sent via ``client.send_*`` helpers)
    """

    def __init__(self, client: AvatarWebSocketClient) -> None:
        self._client = client
        self.session_id: Optional[str] = None
        self.user_id: Optional[str] = None
        self.session_init_received = asyncio.Event()
        self.response_done = asyncio.Event()
        self._response_text: dict[str, list[str]] = {}

    # ---- session events ---------------------------------------------------

    async def on_session_init(self, session_id: str, user_id: str) -> None:
        self.session_id = session_id
        self.user_id = user_id
        logger.info("<-- session.init  session_id=%s  user_id=%s", session_id, user_id)
        self.session_init_received.set()

    async def on_session_ready(self) -> None:
        logger.info("<-- session.ready")

    async def on_session_state(self, state: SessionState, seq: int, timestamp: int) -> None:
        logger.info("<-- session.state  state=%s  seq=%d  ts=%d", state.value, seq, timestamp)

    async def on_session_closing(self, reason: Optional[str]) -> None:
        logger.info("<-- session.closing  reason=%s", reason)

    # ---- scene events -----------------------------------------------------

    async def on_scene_ready(self) -> None:
        logger.info("<-- scene.ready (LiveKit DataChannel)")

    # ---- input events — text ----------------------------------------------

    async def on_input_text(self, request_id: str, text: str) -> None:
        logger.info("<-- input.text  request_id=%s  text=%r", request_id, text)
        # Kick off a streaming response (echo the input back word-by-word).
        asyncio.ensure_future(self._stream_echo_response(request_id, text))

    # ---- input events — ASR / voice (Platform ASR: received from platform) -

    async def on_asr_partial(self, request_id: str, text: str, seq: int) -> None:
        logger.info("<-- input.asr.partial  request_id=%s  seq=%d  text=%r", request_id, seq, text)

    async def on_asr_final(self, request_id: str, text: str) -> None:
        logger.info("<-- input.asr.final  request_id=%s  text=%r", request_id, text)

    async def on_voice_start(self, request_id: str) -> None:
        logger.info("<-- input.voice.start  request_id=%s", request_id)

    async def on_voice_finish(self, request_id: str) -> None:
        logger.info("<-- input.voice.finish  request_id=%s", request_id)

    # ---- response events (Platform TTS) -----------------------------------

    async def on_response_start(self, request_id: str, response_id: str, audio_config: Optional[dict]) -> None:
        logger.info("<-- response.start  response_id=%s", response_id)

    async def on_chunk_received(self, request_id: str, response_id: str, seq: int, text: str) -> None:
        logger.info("<-- response.chunk  response_id=%s  seq=%d  text=%r", response_id, seq, text)

    async def on_response_done(self, request_id: str, response_id: str) -> None:
        logger.info("<-- response.done  response_id=%s", response_id)

    async def on_response_audio_start(self, request_id: str, response_id: str) -> None:
        logger.info("<-- response.audio.start  response_id=%s", response_id)

    async def on_response_audio_finish(self, request_id: str, response_id: str) -> None:
        logger.info("<-- response.audio.finish  response_id=%s", response_id)

    async def on_response_audio_prompt_start(self) -> None:
        logger.info("<-- response.audio.promptStart")

    async def on_response_audio_prompt_finish(self) -> None:
        logger.info("<-- response.audio.promptFinish")

    async def on_response_cancel(self, response_id: str) -> None:
        logger.info("<-- response.cancel  response_id=%s", response_id)

    # ---- control / system -------------------------------------------------

    async def on_control_interrupt(self, request_id: Optional[str]) -> None:
        logger.info("<-- control.interrupt  request_id=%s", request_id)

    async def on_idle_trigger(self, reason: str, idle_time_ms: int) -> None:
        logger.info("<-- system.idleTrigger  reason=%s  idle_time_ms=%d", reason, idle_time_ms)

    async def on_system_prompt(self, text: str) -> None:
        logger.info("<-- system.prompt  text=%r", text)

    async def on_error(self, request_id: Optional[str], code: str, message: str) -> None:
        logger.error("<-- error  request_id=%s  code=%s  message=%s", request_id, code, message)

    # ---- binary frames ----------------------------------------------------

    async def on_audio_frame(self, frame: AudioFrame) -> None:
        logger.debug(
            "<-- audio frame  seq=%d  ts=%d  codec=%s  len=%d",
            frame.seq,
            frame.timestamp,
            frame.codec_name,
            len(frame.payload),
        )

    async def on_image_frame(self, frame: ImageFrame) -> None:
        logger.debug(
            "<-- image frame  id=%d  %dx%d  fmt=%d  len=%d",
            frame.image_id,
            frame.width,
            frame.height,
            frame.format,
            len(frame.payload),
        )

    # ---- internal helpers --------------------------------------------------

    async def _stream_echo_response(self, request_id: str, text: str) -> None:
        """Send a word-by-word echo response back to the platform."""
        response_id = str(uuid.uuid4())
        words = text.split()
        if not words:
            words = [text]

        await self._client.send_response_start(request_id, response_id)
        logger.info("--> response.start  response_id=%s", response_id)

        for seq, word in enumerate(words):
            ts = int(time.monotonic() * 1000) & 0xFFFFF
            await self._client.send_response_chunk(request_id, response_id, seq, ts, word + " ")
            logger.info("--> response.chunk  response_id=%s  seq=%d", response_id, seq)
            await asyncio.sleep(0.05)

        await self._client.send_response_done(request_id, response_id)
        logger.info("--> response.done  response_id=%s", response_id)
        self.response_done.set()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    # 1. Call REST API to start a session using SessionClient
    session_client = SessionClient(
        api_key=API_KEY,
        base_url=PLATFORM_URL,
    )
    result = await session_client.start(avatar_id=AVATAR_ID)
    agent_ws_url = result.agent_ws_url
    session_id = result.session_id
    await session_client.close()

    if agent_ws_url is None:
        raise RuntimeError(
            "agentWsUrl not present in /session/start response — "
            "is Inbound mode enabled for this avatar?"
        )

    logger.info("REST ← sessionId=%s  agentWsUrl=%s", session_id, agent_ws_url)

    # 2. Build the listener and client.  The listener needs a client reference
    #    for its send helpers, so we create it via __new__ and inject after.
    listener = InboundDeveloperListener.__new__(InboundDeveloperListener)
    client = AvatarWebSocketClient(agent_ws_url, listener)
    listener.__init__(client)

    logger.info("Connecting to agentWsUrl: %s", agent_ws_url)
    await client.connect()

    # 3. Wait for session.init from the platform
    try:
        await asyncio.wait_for(listener.session_init_received.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.error("Timed out waiting for session.init — is the platform reachable?")
        await client.disconnect()
        return

    # 4. Acknowledge the session
    await client.send_session_ready()
    logger.info("--> session.ready")

    # 5. Wait for the response echo to complete (triggered by input.text from platform)
    try:
        await asyncio.wait_for(listener.response_done.wait(), timeout=15.0)
    except asyncio.TimeoutError:
        logger.warning("Timed out waiting for response.done")

    # 6. Clean disconnect
    await client.disconnect()
    logger.info("Inbound client example complete. session_id=%s", session_id)


if __name__ == "__main__":
    asyncio.run(main())
