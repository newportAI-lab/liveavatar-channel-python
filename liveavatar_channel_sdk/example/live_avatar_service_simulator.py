"""
Live Avatar Service Simulator — simulates the avatar service for local testing.

Connects to the reference server at ws://localhost:8080/avatar/ws and sends a
scripted sequence of events to exercise the protocol:

  1. session.init       (open session)
  2. input.text         (send user text input)
  3. Receive + print streaming response chunks
  4. system.idle_trigger (simulate idle)
  5. session.closing    (close gracefully)

Run with:
    python -m liveavatar_channel_sdk.example.live_avatar_service_simulator
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

from liveavatar_channel_sdk.avatar_channel_listener_adapter import AvatarChannelListenerAdapter
from liveavatar_channel_sdk.avatar_websocket_client import AvatarWebSocketClient
from liveavatar_channel_sdk.message_builder import MessageBuilder
from liveavatar_channel_sdk.session_state import SessionState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SERVER_URL = "ws://localhost:8080/avatar/ws"


class SimulatorListener(AvatarChannelListenerAdapter):
    """Prints incoming protocol events and collects response text."""

    def __init__(self) -> None:
        self.response_text: dict[str, list[str]] = {}  # response_id -> chunks
        self.done_event = asyncio.Event()

    async def on_session_ready(self) -> None:
        logger.info("← session.ready")

    async def on_session_state(self, state: SessionState, seq: int, timestamp: int) -> None:
        logger.info("← session.state  state=%s  seq=%d  ts=%d", state, seq, timestamp)

    async def on_response_start(
        self, request_id: str, response_id: str, audio_config: Optional[dict]
    ) -> None:
        logger.info("← response.start  response_id=%s", response_id)
        self.response_text[response_id] = []

    async def on_chunk_received(
        self, request_id: str, response_id: str, seq: int, text: str
    ) -> None:
        logger.info("← response.chunk [%d] %r", seq, text)
        self.response_text.setdefault(response_id, []).append(text)

    async def on_response_done(self, request_id: str, response_id: str) -> None:
        full = "".join(self.response_text.get(response_id, []))
        logger.info("← response.done   full_text=%r", full)
        self.done_event.set()

    async def on_idle_trigger(self, reason: str, idle_time_ms: int) -> None:
        logger.info("← system.idleTrigger  reason=%s  idle_time_ms=%d", reason, idle_time_ms)

    async def on_error(self, request_id: Optional[str], code: str, message: str) -> None:
        logger.error("← error  code=%s  message=%s", code, message)


async def main() -> None:
    listener = SimulatorListener()
    client = AvatarWebSocketClient(SERVER_URL, listener)

    logger.info("Connecting to %s …", SERVER_URL)
    await client.connect()

    session_id = str(uuid.uuid4())
    user_id = "test-user-001"

    # 1. session.init
    logger.info("→ session.init  session_id=%s", session_id)
    await client.send_json(MessageBuilder.session_init(session_id, user_id))

    # Small pause to let the server respond with session.ready
    await asyncio.sleep(0.2)

    # 2. input.text
    request_id = str(uuid.uuid4())
    text = "Hello, this is a test message for the echo server"
    logger.info("→ input.text  %r", text)
    await client.send_json(MessageBuilder.input_text(request_id, text))

    # 3. Wait for response.done
    try:
        await asyncio.wait_for(listener.done_event.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning("Timed out waiting for response.done")

    # 4. system.idle_trigger
    logger.info("→ system.idle_trigger")
    await client.send_json(MessageBuilder.system_idle_trigger("no_input", 5000))
    await asyncio.sleep(0.1)

    # 5. Graceful close
    logger.info("→ session.closing (disconnect)")
    await client.disconnect()
    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
