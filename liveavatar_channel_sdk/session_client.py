"""
SessionClient -- async REST client for the Live Avatar session management API.

Covers ``POST /v1/session/start`` and ``POST /v1/session/stop`` as defined
in the Live Avatar Integration Guide.

Usage::

    client = SessionClient(api_key="sk-...")
    result = await client.start(avatar_id="avatar-123")
    await client.stop(session_id=result.session_id)
    await client.close()
"""

from __future__ import annotations

from typing import Optional

import httpx

from liveavatar_channel_sdk.session_models import (
    ErrorCode,
    SessionStartError,
    SessionStartResult,
)

_ERROR_CODE_MAP: dict[int, ErrorCode] = {
    40001: ErrorCode.NO_ORCHESTRATION_POD,
    40002: ErrorCode.NO_RENDERER_POD,
    40003: ErrorCode.SESSION_START_FAILED,
    40004: ErrorCode.PRINCIPAL_UNIDENTIFIED,
    40005: ErrorCode.CONCURRENCY_LIMIT_EXCEEDED,
    40006: ErrorCode.QUOTA_EXHAUSTED,
    40007: ErrorCode.SESSION_ACCESS_DENIED,
}

_DEFAULT_BASE_URL = "https://facemarket.ai/vih/dispatcher"


class SessionClient:
    """Async client for the platform session management REST API.

    Args:
        api_key: Platform API Key (server-side only -- never expose to frontend).
        base_url: Platform base URL. Defaults to production; override for
            regional endpoints (e.g. ``https://facemarket.cn/vih/dispatcher``).
        sandbox: If ``True``, adds ``X-Env-Sandbox: true`` to every request.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        sandbox: bool = False,
        timeout: float = 30,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"}
        if sandbox:
            headers["X-Env-Sandbox"] = "true"
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(
        self,
        avatar_id: str,
        *,
        voice_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> SessionStartResult:
        """Initiate (or reconnect to) a session.

        Args:
            avatar_id: Unique avatar identifier (required).
            voice_id: Override the avatar's default voice for this session.
            session_id: Include to reconnect to an existing session; omit to
                create a new session.

        Returns:
            ``SessionStartResult`` with tokens and URLs.

        Raises:
            ``SessionStartError``: Platform returned ``code != 0``.
            ``httpx.HTTPError``: Network or HTTP protocol error.
        """
        body: dict = {"avatarId": avatar_id}
        if voice_id is not None:
            body["voiceId"] = voice_id
        if session_id is not None:
            body["sessionId"] = session_id

        resp = await self._client.post("/v1/session/start", json=body)
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

    async def stop(self, session_id: str) -> None:
        """End an active session.

        Args:
            session_id: The session to stop.

        Raises:
            ``httpx.HTTPError``: Network or HTTP protocol error.
        """
        resp = await self._client.post("/v1/session/stop", json={"sessionId": session_id})
        resp.raise_for_status()

    async def close(self) -> None:
        """Release the underlying HTTP client."""
        await self._client.aclose()
