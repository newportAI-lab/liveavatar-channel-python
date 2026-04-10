from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BaseMessage:
    """Base message with event type."""

    type: str


@dataclass
class SessionInitMessage:
    """Session initialization message sent by avatar service."""

    type: str  # "session.init"
    session_id: str
    user_id: str


@dataclass
class SessionReadyMessage:
    """Session ready acknowledgment sent by developer."""

    type: str  # "session.ready"
    session_id: str


@dataclass
class SessionStateMessage:
    """Session state update sent by avatar service."""

    type: str  # "session.state"
    state: str  # SessionState value
    seq: int
    timestamp: int


@dataclass
class SessionClosingMessage:
    """Session closing notification sent by avatar service."""

    type: str  # "session.closing"
    reason: Optional[str] = None


@dataclass
class InputTextMessage:
    """User text input message sent by avatar service."""

    type: str  # "input.text"
    request_id: str
    text: str


@dataclass
class AsrMessage:
    """Automatic speech recognition result message."""

    type: str  # "input.asr.partial" or "input.asr.final"
    request_id: str
    text: str
    final: bool = False
    seq: Optional[int] = None


@dataclass
class ResponseChunkMessage:
    """Streaming response text chunk sent by developer."""

    type: str  # "response.chunk"
    request_id: str
    response_id: str
    seq: int
    timestamp: int
    text: str


@dataclass
class ResponseDoneMessage:
    """Response completion message sent by developer."""

    type: str  # "response.done"
    request_id: str
    response_id: str


@dataclass
class ResponseCancelMessage:
    """Response cancellation message sent by developer."""

    type: str  # "response.cancel"
    response_id: str


@dataclass
class ControlInterruptMessage:
    """Interrupt control message sent by developer."""

    type: str  # "control.interrupt"
    request_id: Optional[str] = None


@dataclass
class IdleTriggerMessage:
    """Idle trigger notification sent by avatar service."""

    type: str  # "system.idle_trigger"
    reason: str
    idle_time_ms: int


@dataclass
class SystemPromptMessage:
    """System prompt message sent by developer for idle wakeup."""

    type: str  # "system.prompt"
    text: str


@dataclass
class ErrorMessage:
    """Error message sent by either party."""

    type: str  # "error"
    code: str
    message: str
    request_id: Optional[str] = None
