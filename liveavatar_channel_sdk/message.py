from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BaseMessage:
    """Base message with event type."""

    event: str  # EventType string value


@dataclass
class SessionInitMessage:
    """Session initialization message sent by avatar service."""

    event: str  # EventType.SESSION_INIT
    session_id: str
    user_id: str


@dataclass
class SessionReadyMessage:
    """Session ready acknowledgment sent by developer."""

    event: str  # "session.ready"


@dataclass
class SessionStateMessage:
    """Session state update sent by avatar service."""

    event: str  # "session.state"
    state: str  # SessionState value
    seq: int
    timestamp: int


@dataclass
class SessionClosingMessage:
    """Session closing notification sent by avatar service."""

    event: str  # "session.closing"
    reason: Optional[str] = None


@dataclass
class SceneReadyMessage:
    """Scene ready notification sent by JS SDK over the LiveKit DataChannel.

    Signals that the frontend scene has finished setting up and the
    conversation can begin. Handled by the Live Avatar Service; has no
    payload beyond the event name.
    """

    event: str  # "scene.ready"


@dataclass
class InputTextMessage:
    """User text input message sent by avatar service."""

    event: str  # "input.text"
    request_id: str
    text: str


@dataclass
class AsrMessage:
    """Automatic speech recognition result message."""

    event: str  # "input.asr.partial" or "input.asr.final"
    request_id: str
    text: str
    final: bool = False
    seq: Optional[int] = None


@dataclass
class ResponseChunkMessage:
    """Streaming response text chunk sent by developer."""

    event: str  # "response.chunk"
    request_id: str
    response_id: str
    seq: int
    timestamp: int
    text: str


@dataclass
class ResponseDoneMessage:
    """Response completion message sent by developer."""

    event: str  # "response.done"
    request_id: str
    response_id: str


@dataclass
class ResponseCancelMessage:
    """Response cancellation message sent by developer."""

    event: str  # "response.cancel"
    response_id: str


@dataclass
class ControlInterruptMessage:
    """Interrupt control message sent by developer."""

    event: str  # "control.interrupt"
    request_id: Optional[str] = None


@dataclass
class IdleTriggerMessage:
    """Idle trigger notification sent by avatar service."""

    event: str  # EventType.SYSTEM_IDLE_TRIGGER
    reason: str
    idle_time_ms: int


@dataclass
class SystemPromptMessage:
    """System prompt message sent by developer for idle wakeup."""

    event: str  # "system.prompt"
    text: str


@dataclass
class ErrorMessage:
    """Error message sent by either party."""

    event: str  # "error"
    code: str
    message: str
    request_id: Optional[str] = None
