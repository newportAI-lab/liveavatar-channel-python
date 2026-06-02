from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("liveavatar-channel-sdk")
except PackageNotFoundError:
    __version__ = "0.0.0"

from liveavatar_channel_sdk.avatar_agent import AvatarAgent, AgentListener, AvatarAgentConfig
from liveavatar_channel_sdk.session_models import SessionStartResult, SessionStartError, ErrorCode
from liveavatar_channel_sdk.audio_frame import AudioFrame
from liveavatar_channel_sdk.audio_frame_builder import AudioFrameBuilder
from liveavatar_channel_sdk.image_frame import ImageFrame
from liveavatar_channel_sdk.image_frame_builder import ImageFrameBuilder
from liveavatar_channel_sdk.session_state import SessionState
from liveavatar_channel_sdk.event_type import EventType
from liveavatar_channel_sdk.exponential_backoff_strategy import ExponentialBackoffStrategy

__all__ = [
    "AvatarAgent",
    "AgentListener",
    "AvatarAgentConfig",
    "SessionStartResult",
    "SessionStartError",
    "ErrorCode",
    "AudioFrame",
    "AudioFrameBuilder",
    "ImageFrame",
    "ImageFrameBuilder",
    "SessionState",
    "EventType",
    "ExponentialBackoffStrategy",
]
