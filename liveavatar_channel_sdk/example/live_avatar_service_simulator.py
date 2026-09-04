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
        self._response_tasks: dict[str, asyncio.Task] = {}

    async def on_text_input(self, text: str, request_id: str) -> None:
        logger.info("<-- input.text  request_id=%s  text=%r", request_id, text)
        assert self.agent is not None
        task = self._response_tasks.get(request_id)
        if task is not None and not task.done():
            logger.warning("Ignoring duplicate active request: request_id=%s", request_id)
            return
        task = asyncio.create_task(self._echo(request_id, text))
        self._response_tasks[request_id] = task

        def remove_completed_task(completed: asyncio.Task, rid: str = request_id) -> None:
            if self._response_tasks.get(rid) is completed:
                self._response_tasks.pop(rid)

        task.add_done_callback(
            remove_completed_task
        )

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
        words = text.split()
        if not words:
            words = [text]

        assert self.agent is not None
        async with self.agent.response_stream(request_id, send_start=True) as response:
            logger.info("--> response.start  response_id=%s", response.response_id)
            for word in words:
                await response.send_chunk(word + " ")
                logger.info("--> response.chunk  response_id=%s", response.response_id)
                await asyncio.sleep(0.05)

        logger.info("--> response.done  response_id=%s", response.response_id)
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
