"""AvatarAgent — single entry point for Live Avatar Channel SDK (Inbound mode).

Usage::

    class MyAgent(AgentListener):
        async def on_text_input(self, text: str, request_id: str) -> None:
            reply = await my_ai.chat(text)
            response_id = str(uuid.uuid4())
            await self.agent.send_response_start(request_id, response_id)
            await self.agent.send_response_chunk(request_id, response_id, 0, ts, reply)
            await self.agent.send_response_done(request_id, response_id)

    config = AvatarAgentConfig(api_key="sk-...", avatar_id="avatar-123")
    listener = MyAgent()
    agent = AvatarAgent(config, listener)
    listener.agent = agent
    await agent.start()
    # ... receive callbacks ...
    await agent.stop()
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from liveavatar_channel_sdk._ws_client import _AvatarWsClient, _AgentCallbacks
from liveavatar_channel_sdk.audio_frame import AudioFrame
from liveavatar_channel_sdk.message_builder import MessageBuilder
from liveavatar_channel_sdk.session_models import (
    ErrorCode,
    SessionStartError,
    SessionStartResult,
)
from liveavatar_channel_sdk.session_state import SessionState

logger = logging.getLogger(__name__)

_ERROR_CODE_MAP: dict[int, ErrorCode] = {
    40001: ErrorCode.NO_ORCHESTRATION_POD,
    40002: ErrorCode.NO_RENDERER_POD,
    40003: ErrorCode.SESSION_START_FAILED,
    40004: ErrorCode.PRINCIPAL_UNIDENTIFIED,
    40005: ErrorCode.CONCURRENCY_LIMIT_EXCEEDED,
    40006: ErrorCode.QUOTA_EXHAUSTED,
    40007: ErrorCode.SESSION_ACCESS_DENIED,
}


# ------------------------------------------------------------------
# AgentListener
# ------------------------------------------------------------------

class AgentListener:
    """Callback interface for receiving protocol events.

    All methods have default no-op implementations — override only
    the ones you need.  ``on_text_input`` is the core callback.
    """

    async def on_text_input(self, text: str, request_id: str) -> None:
        """User text input received (typing or platform ASR result)."""

    async def on_session_init(self, session_id: str, user_id: str) -> None:
        """Handshake complete (SDK already replied ``session.ready``)."""

    async def on_session_state(self, state: SessionState) -> None:
        """Session state changed (IDLE / LISTENING / SPEAKING / ...)."""

    async def on_session_closing(self, reason: str | None) -> None:
        """Platform is about to close the connection (e.g. timeout)."""

    async def on_idle_trigger(self, reason: str, idle_time_ms: int) -> None:
        """Platform detected prolonged user inactivity."""

    async def on_audio_frame(self, frame: AudioFrame) -> None:
        """Raw binary audio frame received (Developer ASR mode only)."""

    async def on_error(self, code: str, message: str) -> None:
        """Error received from platform or transport."""

    async def on_closed(self, code: int, reason: str) -> None:
        """WebSocket connection closed."""


# ------------------------------------------------------------------
# AvatarAgentConfig
# ------------------------------------------------------------------

@dataclass
class AvatarAgentConfig:
    """Configuration for AvatarAgent.

    Required:
        api_key:     Platform API Key (server-side only).
        avatar_id:   Unique avatar identifier.

    Optional:
        base_url:           Platform base URL.
        sandbox:            Enable sandbox mode (X-Env-Sandbox header).
        timeout:            HTTP request + handshake timeout in seconds.
        developer_tts:      Developer provides TTS output.
        developer_asr:      Developer runs ASR + VAD.
        voice_id:           Override avatar default voice.
        reconnect:          Enable auto-reconnect on disconnect.
        reconnect_base_delay:  Base delay for exponential backoff (s).
        reconnect_max_delay:  Max delay for exponential backoff (s).
    """

    api_key: str
    avatar_id: str
    base_url: str = "https://facemarket.ai/vih/dispatcher"
    sandbox: bool = False
    timeout: float = 30.0
    developer_tts: bool = False
    developer_asr: bool = False
    voice_id: str | None = None
    reconnect: bool = False
    reconnect_base_delay: float = 1.0
    reconnect_max_delay: float = 60.0


# ------------------------------------------------------------------
# AvatarAgent
# ------------------------------------------------------------------

class AvatarAgent:
    """Single entry point for the Live Avatar Channel SDK.

    Encapsulates REST session management, WebSocket transport, automatic
    handshake, and all protocol send methods.
    """

    def __init__(self, config: AvatarAgentConfig, listener: AgentListener) -> None:
        self._config = config
        self._listener = listener
        self._ws_client: _AvatarWsClient | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._session_id: str | None = None
        self._session_init_event = asyncio.Event()

    # -- lifecycle ---------------------------------------------------------

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def is_running(self) -> bool:
        return self._ws_client is not None and self._session_init_event.is_set()

    async def start(self) -> SessionStartResult:
        """Start a session: REST /session/start → WS connect → wait for
        session.init → auto-reply session.ready.

        Returns SessionStartResult.  Blocks until handshake completes
        (timeout controlled by config.timeout, default 30 s).
        """
        if self._http_client is not None:
            raise RuntimeError("Already started — call stop() first")

        self._session_init_event.clear()

        # 1. Create HTTP client
        headers = {"Authorization": f"Bearer {self._config.api_key}"}
        if self._config.sandbox:
            headers["X-Env-Sandbox"] = "true"
        self._http_client = httpx.AsyncClient(
            base_url=self._config.base_url,
            headers=headers,
            timeout=httpx.Timeout(self._config.timeout),
        )

        # 2. REST call
        result = await self._rest_start()

        if result.agent_ws_url is None:
            await self._http_client.aclose()
            self._http_client = None
            raise RuntimeError(
                "agentWsUrl not present in /session/start response — "
                "is Inbound mode enabled for this avatar?"
            )

        # 3. Connect WebSocket
        self._ws_client = _AvatarWsClient(
            url=result.agent_ws_url,
            callbacks=_ListenerBridge(self._listener),
            session_init_event=self._session_init_event,
        )
        await self._ws_client.connect(reconnect=self._config.reconnect)

        # 4. Wait for session.init handshake
        try:
            await asyncio.wait_for(
                self._session_init_event.wait(),
                timeout=self._config.timeout,
            )
        except asyncio.TimeoutError:
            await self._ws_client.disconnect()
            self._ws_client = None
            raise RuntimeError(
                f"Timed out waiting for session.init after {self._config.timeout}s"
            )

        self._session_id = result.session_id
        return result

    async def stop(self) -> None:
        """Idempotent stop: disconnect WS and call POST /session/stop."""
        if self._ws_client is not None:
            try:
                await self._ws_client.disconnect()
            except Exception:
                pass
            self._ws_client = None

        if self._session_id is not None and self._http_client is not None:
            try:
                resp = await self._http_client.post(
                    "/v1/session/stop",
                    json={"sessionId": self._session_id},
                )
                resp.raise_for_status()
            except Exception as exc:
                logger.warning("Error calling /session/stop: %s", exc)

        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

        self._session_id = None

    async def _rest_start(self) -> SessionStartResult:
        assert self._http_client is not None
        body: dict = {"avatarId": self._config.avatar_id}
        if self._config.voice_id is not None:
            body["voiceId"] = self._config.voice_id

        resp = await self._http_client.post("/v1/session/start", json=body)
        resp.raise_for_status()
        payload = resp.json()

        code = payload.get("code", -1)
        if code != 0:
            error_code = _ERROR_CODE_MAP.get(code, ErrorCode.SESSION_START_FAILED)
            raise SessionStartError(
                code=code,
                error_code=error_code,
                message=payload.get("message", "Unknown error"),
            )

        data = payload["data"]
        return SessionStartResult(
            session_id=data["sessionId"],
            sfu_url=data["sfuUrl"],
            user_token=data["userToken"],
            agent_token=data.get("agentToken"),
            agent_ws_url=data.get("agentWsUrl"),
        )

    def _require_ws(self) -> _AvatarWsClient:
        if self._ws_client is None:
            raise RuntimeError("Not connected — call start() first")
        return self._ws_client

    # -- send: Platform TTS ------------------------------------------------

    async def send_response_start(
        self,
        request_id: str,
        response_id: str,
        *,
        speed: float = 1.0,
        volume: float = 1.0,
        mood: str | None = None,
    ) -> None:
        await self._require_ws().send_json(
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
        await self._require_ws().send_json(
            MessageBuilder.response_chunk(request_id, response_id, seq, timestamp, text)
        )

    async def send_response_done(
        self, request_id: str, response_id: str
    ) -> None:
        await self._require_ws().send_json(
            MessageBuilder.response_done(request_id, response_id)
        )

    async def send_response_cancel(self, response_id: str) -> None:
        await self._require_ws().send_json(
            MessageBuilder.response_cancel(response_id)
        )

    # -- send: Developer TTS -----------------------------------------------

    async def send_response_audio_start(
        self, request_id: str, response_id: str
    ) -> None:
        await self._require_ws().send_json(
            MessageBuilder.response_audio_start(request_id, response_id)
        )

    async def send_audio_frame(self, frame: AudioFrame) -> None:
        await self._require_ws().send_binary(frame.pack())

    async def send_response_audio_finish(
        self, request_id: str, response_id: str
    ) -> None:
        await self._require_ws().send_json(
            MessageBuilder.response_audio_finish(request_id, response_id)
        )

    # -- send: idle prompt audio (Developer TTS mode) ----------------------

    async def send_prompt_audio_start(self) -> None:
        await self._require_ws().send_json(
            MessageBuilder.response_audio_prompt_start()
        )

    async def send_prompt_audio_finish(self) -> None:
        await self._require_ws().send_json(
            MessageBuilder.response_audio_prompt_finish()
        )

    # -- send: Developer ASR / Omni -----------------------------------------

    async def send_voice_start(self, request_id: str) -> None:
        await self._require_ws().send_json(
            MessageBuilder.input_voice_start(request_id)
        )

    async def send_asr_partial(
        self, request_id: str, text: str, seq: int
    ) -> None:
        await self._require_ws().send_json(
            MessageBuilder.input_asr_partial(request_id, text, seq)
        )

    async def send_voice_finish(self, request_id: str) -> None:
        await self._require_ws().send_json(
            MessageBuilder.input_voice_finish(request_id)
        )

    async def send_asr_final(self, request_id: str, text: str) -> None:
        await self._require_ws().send_json(
            MessageBuilder.input_asr_final(request_id, text)
        )

    # -- send: control -----------------------------------------------------

    async def send_interrupt(self, request_id: str | None = None) -> None:
        await self._require_ws().send_json(
            MessageBuilder.control_interrupt(request_id)
        )

    async def send_prompt(self, text: str) -> None:
        await self._require_ws().send_json(MessageBuilder.system_prompt(text))

    # -- send: error -------------------------------------------------------

    async def send_error(
        self,
        code: str,
        message: str,
        request_id: str | None = None,
    ) -> None:
        await self._require_ws().send_json(
            MessageBuilder.error(code, message, request_id)
        )


# ------------------------------------------------------------------
# Internal bridge — adapts AgentListener to _AgentCallbacks Protocol
# ------------------------------------------------------------------

class _ListenerBridge:
    """Forwards _AgentCallbacks to AgentListener, suppressing exceptions."""

    def __init__(self, listener: AgentListener) -> None:
        self._listener = listener

    async def on_session_init(self, session_id: str, user_id: str) -> None:
        try:
            await self._listener.on_session_init(session_id, user_id)
        except Exception as exc:
            logger.error("on_session_init error: %s", exc)

    async def on_session_state(self, state: SessionState) -> None:
        try:
            await self._listener.on_session_state(state)
        except Exception as exc:
            logger.error("on_session_state error: %s", exc)

    async def on_session_closing(self, reason: str | None) -> None:
        try:
            await self._listener.on_session_closing(reason)
        except Exception as exc:
            logger.error("on_session_closing error: %s", exc)

    async def on_text_input(self, text: str, request_id: str) -> None:
        try:
            await self._listener.on_text_input(text, request_id)
        except Exception as exc:
            logger.error("on_text_input error: %s", exc)

    async def on_idle_trigger(self, reason: str, idle_time_ms: int) -> None:
        try:
            await self._listener.on_idle_trigger(reason, idle_time_ms)
        except Exception as exc:
            logger.error("on_idle_trigger error: %s", exc)

    async def on_error(self, code: str, message: str) -> None:
        try:
            await self._listener.on_error(code, message)
        except Exception as exc:
            logger.error("on_error handler error: %s", exc)

    async def on_audio_frame(self, frame: AudioFrame) -> None:
        try:
            await self._listener.on_audio_frame(frame)
        except Exception as exc:
            logger.error("on_audio_frame error: %s", exc)

    async def on_closed(self, code: int, reason: str) -> None:
        try:
            await self._listener.on_closed(code, reason)
        except Exception as exc:
            logger.error("on_closed error: %s", exc)
