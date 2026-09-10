"""Response-specific lifecycle events published by the platform."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResponseStateEvent:
    """A response lifecycle update.

    ``state`` and ``reason`` intentionally remain strings so newer protocol
    values can reach applications without requiring an SDK upgrade.
    """

    session_id: str
    request_id: str
    response_id: str
    seq: int
    timestamp: int
    state: str
    reason: str | None
