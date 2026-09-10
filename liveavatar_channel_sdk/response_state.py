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

    def __post_init__(self) -> None:
        for name in ("session_id", "request_id", "response_id", "state"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        for name in ("seq", "timestamp"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        if self.reason is not None and not isinstance(self.reason, str):
            raise ValueError("reason must be a string or None")
