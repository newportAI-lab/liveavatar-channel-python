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

        task.add_done_callback(remove_completed_task)

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

# Call examples. Nothing below runs.
#
# config = AvatarAgentConfig(
#     api_key=API_KEY,
#     avatar_id=AVATAR_ID,
#     base_url=PLATFORM_URL,
#     sandbox=False,
#     timeout=30.0,
#     developer_tts=False,
#     developer_asr=True,
#     voice_id=None,
#     voice_config={"volume": 80, "speed": 1.0},
#     reconnect=False,
#     external_audio_config={"sampleRate": 48000, "channels": 2},
# )
# sampleRate 0 follows the session voice format. Otherwise use 16000, 24000,
# 44100, or 48000. channels 0 follows voice. Otherwise use 1 or 2.
# agent = AvatarAgent(config, listener)
# result = await agent.start()
# agent.session_id
# agent.is_running
#
# response = agent.response_stream(request_id)
# await response.start(audio_config)
# await response.send_chunk("Hello")
# await response.done()
# await response.cancel()
# Deprecated. Prefer response_stream:
# await agent.send_response_start(request_id, response_id)
# await agent.send_response_chunk(request_id, response_id, seq, timestamp, "Hello")
# await agent.send_response_done(request_id, response_id)
# await agent.send_response_cancel(response_id)
#
# await agent.send_response_audio_start(request_id, response_id)
# await agent.send_audio_frame(frame)  # 9-byte voice frame. This drives lip sync.
# await agent.send_response_audio_finish(request_id, response_id)
# await agent.send_prompt_audio_start()
# await agent.send_prompt_audio_finish()
#
# await agent.send_voice_start(request_id)
# await agent.send_asr_partial(request_id, "partial", seq)
# await agent.send_voice_finish(request_id)
# await agent.send_asr_final(request_id, "final text")
#
# await agent.send_prompt("Are you still there?")
# prompt = agent.prompt_stream(request_id)
# await prompt.send_chunk("Hello")
# await prompt.done()
#
# pcm = b"\x00" * 38400  # 200 ms, 48000 Hz, stereo, 16-bit
# The PCM rate and channel count must match external_audio_config when it is set.
# If it is omitted, match the session TTS audio format.
# One binary frame, including its header, must not exceed 65536 bytes.
# Send the next packet before the previous audio finishes playing.
# The first packet may be longer than later packets, but not over that limit.
# await agent.send_external_audio(pcm)
# await agent.send_external_audio(pcm, timestamp_us=0)
# Platform TTS song. This is the voice turn, not accompaniment.
# song_pcm is 24000 Hz, mono, 16-bit. The SDK does not resample.
# song = AudioFrame(channel=0, key=1, seq=0, timestamp=0, sample_rate=1,
#                   samples=len(song_pcm) // 2, codec=0, payload=song_pcm)
# async def song_frames():
#     yield song
# await agent.send_external_playback(request_id, response_id, song_frames())
# Sends response.audio.start and response.audio.finish with data.purpose=external.
#
# send_interrupt adds the string parameter interrupt_scope.
# await agent.send_interrupt()  # same as VOICE_ONLY: stop voice only
# await agent.send_interrupt(interrupt_scope="VOICE_ONLY")
# await agent.send_interrupt(interrupt_scope="BGM_ONLY")  # clear queued external audio only
# await agent.send_interrupt(interrupt_scope="VOICE_AND_ACCOMPANIMENT")  # stop both
# The value is sent as data.interruptScope on control.interrupt.
#
# await agent.send_error("APP_ERROR", "something failed", request_id)
# await agent.send_custom_event(request_id, "scene.switchVideo", {
#     "onceVideos": ["fist_bump"],  # resourceId or alias
#     "loopVideos": ["01KTJNMD7NZJF4KMGCCFSTJN4X"],
#     "mode": "HARD",  # HARD immediate, GRACEFUL wait (default)
# })
# await agent.stop()
#
# Listener methods you can override: on_text_input, on_session_init,
# on_session_state, on_resource_transition, on_session_closing, on_idle_trigger,
# on_scene_ready, on_audio_frame, on_error, on_closed, on_response_state.
