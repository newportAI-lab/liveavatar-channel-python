from enum import Enum


class SessionState(str, Enum):
    """Session state constants tracking the avatar's active state during a dialogue."""

    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    STAGING = "STAGING"
    SPEAKING = "SPEAKING"
    PROMPT_THINKING = "PROMPT_THINKING"
    PROMPT_STAGING = "PROMPT_STAGING"
    PROMPT_SPEAKING = "PROMPT_SPEAKING"
