"""
No-op adapter implementing AvatarChannelListener with all methods as pass.

Subclass and override only the methods you need to handle.
"""

from typing import Optional

from liveavatar_channel_sdk.audio_frame import AudioFrame
from liveavatar_channel_sdk.avatar_channel_listener import AvatarChannelListener
from liveavatar_channel_sdk.image_frame import ImageFrame
from liveavatar_channel_sdk.session_state import SessionState


class AvatarChannelListenerAdapter(AvatarChannelListener):
    """No-op adapter. Subclass and override only the methods you need."""

    async def on_session_init(self, session_id: str, user_id: str) -> None:
        pass

    async def on_session_ready(self) -> None:
        pass

    async def on_session_state(self, state: SessionState, seq: int, timestamp: int) -> None:
        pass

    async def on_session_closing(self, reason: Optional[str]) -> None:
        pass

    async def on_session_stop(self) -> None:
        pass

    async def on_scene_ready(self) -> None:
        pass

    async def on_input_text(self, request_id: str, text: str) -> None:
        pass

    async def on_asr_partial(self, request_id: str, text: str, seq: int) -> None:
        pass

    async def on_asr_final(self, request_id: str, text: str) -> None:
        pass

    async def on_voice_start(self, request_id: str) -> None:
        pass

    async def on_voice_finish(self, request_id: str) -> None:
        pass

    async def on_response_start(
        self, request_id: str, response_id: str, audio_config: Optional[dict]
    ) -> None:
        pass

    async def on_chunk_received(
        self, request_id: str, response_id: str, seq: int, text: str
    ) -> None:
        pass

    async def on_response_done(self, request_id: str, response_id: str) -> None:
        pass

    async def on_response_audio_start(self, request_id: str, response_id: str) -> None:
        pass

    async def on_response_audio_finish(self, request_id: str, response_id: str) -> None:
        pass

    async def on_response_audio_prompt_start(self) -> None:
        pass

    async def on_response_audio_prompt_finish(self) -> None:
        pass

    async def on_response_cancel(self, response_id: str) -> None:
        pass

    async def on_idle_trigger(self, reason: str, idle_time_ms: int) -> None:
        pass

    async def on_system_prompt(self, text: str) -> None:
        pass

    async def on_control_interrupt(self, request_id: Optional[str]) -> None:
        pass

    async def on_error(self, request_id: Optional[str], code: str, message: str) -> None:
        pass

    async def on_audio_frame(self, frame: AudioFrame) -> None:
        pass

    async def on_image_frame(self, frame: ImageFrame) -> None:
        pass
