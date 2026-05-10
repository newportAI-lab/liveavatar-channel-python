"""Typed models for the Session REST API (POST /v1/session/start, /v1/session/stop)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ErrorCode(Enum):
    """Platform error codes as defined in the Live Avatar Integration Guide."""

    NO_ORCHESTRATION_POD = "NO_ORCHESTRATION_POD"  # 40001 — retryable
    NO_RENDERER_POD = "NO_RENDERER_POD"  # 40002 — retryable
    SESSION_START_FAILED = "SESSION_START_FAILED"  # 40003 — retryable
    PRINCIPAL_UNIDENTIFIED = "PRINCIPAL_UNIDENTIFIED"  # 40004 — check API key
    CONCURRENCY_LIMIT_EXCEEDED = "CONCURRENCY_LIMIT_EXCEEDED"  # 40005 — plan limit
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"  # 40006 — usage limit
    SESSION_ACCESS_DENIED = "SESSION_ACCESS_DENIED"  # 40007 — wrong account


class SessionStartError(Exception):
    """Raised when the platform returns ``code != 0`` from /session/start."""

    def __init__(self, code: int, error_code: ErrorCode, message: str) -> None:
        self.code = code
        self.error_code = error_code
        self.message = message
        super().__init__(f"[{code}] {error_code.name}: {message}")


@dataclass
class SessionStartResult:
    """Successful response from POST /v1/session/start."""

    session_id: str
    sfu_url: str
    user_token: str
    agent_token: Optional[str] = None  # Platform RTC mode only
    agent_ws_url: Optional[str] = None  # WS Inbound mode only
