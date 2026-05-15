"""
Live Avatar Inbound Mode Agent Example.

Demonstrates the new AvatarAgent + AgentListener API::

    # Terminal 1 (reference server)
    uvicorn liveavatar_channel_server_example.main:app --host 0.0.0.0 --port 8080

    # Terminal 2 (this simulator)
    python -m liveavatar_channel_sdk.example.live_avatar_service_simulator

Configuration via environment variables::

    PLATFORM_URL   Platform base URL (default: http://localhost:8080)
    API_KEY        API Key (default: sk-local-test-key)
    AVATAR_ID      Avatar ID (default: default-avatar)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid

from liveavatar_channel_sdk.avatar_agent import AvatarAgent, AgentListener, AvatarAgentConfig
from liveavatar_channel_sdk.audio_frame import AudioFrame
from liveavatar_channel_sdk.session_state import SessionState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PLATFORM_URL = os.environ.get("PLATFORM_URL", "http://localhost:8080")
API_KEY = os.environ.get("API_KEY", "sk-local-test-key")
AVATAR_ID = os.environ.get("AVATAR_ID", "default-avatar")


class EchoAgent(AgentListener):
    """Echo back user input word-by-word."""

    def __init__(self) -> None:
        self.agent: AvatarAgent | None = None
        self.response_done = asyncio.Event()

    async def on_text_input(self, text: str, request_id: str) -> None:
        logger.info("<-- input.text  request_id=%s  text=%r", request_id, text)
        assert self.agent is not None
        asyncio.ensure_future(self._echo(request_id, text))

    async def on_session_init(self, session_id: str, user_id: str) -> None:
        logger.info("<-- session.init  session_id=%s  user_id=%s", session_id, user_id)

    async def on_session_state(self, state: SessionState) -> None:
        logger.info("<-- session.state  state=%s", state.value)

    async def on_session_closing(self, reason: str | None) -> None:
        logger.info("<-- session.closing  reason=%s", reason)

    async def on_idle_trigger(self, reason: str, idle_time_ms: int) -> None:
        logger.info("<-- system.idleTrigger  reason=%s  idle_time_ms=%d", reason, idle_time_ms)

    async def on_error(self, code: str, message: str) -> None:
        logger.error("<-- error  code=%s  message=%s", code, message)

    async def on_audio_frame(self, frame: AudioFrame) -> None:
        logger.debug("<-- audio frame  seq=%d  len=%d", frame.seq, len(frame.payload))

    async def on_closed(self, code: int, reason: str) -> None:
        logger.info("<-- closed  code=%d  reason=%s", code, reason)

    async def _echo(self, request_id: str, text: str) -> None:
        response_id = str(uuid.uuid4())
        words = text.split()
        if not words:
            words = [text]

        await self.agent.send_response_start(request_id, response_id)
        logger.info("--> response.start  response_id=%s", response_id)

        for seq, word in enumerate(words):
            ts = int(time.monotonic() * 1000) & 0xFFFFF
            await self.agent.send_response_chunk(request_id, response_id, seq, ts, word + " ")
            logger.info("--> response.chunk  response_id=%s  seq=%d", response_id, seq)
            await asyncio.sleep(0.05)

        await self.agent.send_response_done(request_id, response_id)
        logger.info("--> response.done  response_id=%s", response_id)
        self.response_done.set()


async def main() -> None:
    listener = EchoAgent()
    config = AvatarAgentConfig(
        api_key=API_KEY,
        avatar_id=AVATAR_ID,
        base_url=PLATFORM_URL,
        timeout=15.0,
    )
    agent = AvatarAgent(config, listener)
    listener.agent = agent

    result = await agent.start()
    logger.info(
        "Session started: session_id=%s  user_token=%s  sfu_url=%s",
        result.session_id,
        result.user_token,
        result.sfu_url,
    )

    try:
        await asyncio.wait_for(listener.response_done.wait(), timeout=15.0)
    except asyncio.TimeoutError:
        logger.warning("Timed out waiting for response.done")

    await agent.stop()
    logger.info("Agent stopped. session_id=%s", agent.session_id)


if __name__ == "__main__":
    asyncio.run(main())
