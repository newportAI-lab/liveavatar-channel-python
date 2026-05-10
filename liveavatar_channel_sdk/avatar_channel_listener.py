"""
Abstract base class defining all protocol event callbacks for the Live Avatar Channel.

Implement this interface by subclassing and overriding the methods you need to handle.
For a convenient no-op adapter, use AvatarChannelListenerAdapter.
"""

from abc import ABC, abstractmethod
from typing import Optional

from liveavatar_channel_sdk.audio_frame import AudioFrame
from liveavatar_channel_sdk.image_frame import ImageFrame
from liveavatar_channel_sdk.session_state import SessionState


class AvatarChannelListener(ABC):
    """Abstract base class for all Live Avatar Channel protocol event callbacks."""

    @abstractmethod
    async def on_session_init(self, session_id: str, user_id: str) -> None:
        """
        Avatar service opened a session.

        Args:
            session_id: Unique session identifier.
            user_id: User associated with the session.
        """

    @abstractmethod
    async def on_session_ready(self) -> None:
        """Developer's session.ready acknowledgement was received."""

    @abstractmethod
    async def on_session_state(self, state: SessionState, seq: int, timestamp: int) -> None:
        """
        Session state sync from avatar service.

        Args:
            state: Current session state.
            seq: Sequence number.
            timestamp: Event timestamp in milliseconds.
        """

    @abstractmethod
    async def on_session_closing(self, reason: Optional[str]) -> None:
        """
        Avatar service is closing the session (e.g., timeout).

        Args:
            reason: Optional reason string.
        """

    @abstractmethod
    async def on_session_stop(self) -> None:
        """Remote party requested session stop."""

    @abstractmethod
    async def on_scene_ready(self) -> None:
        """
        Frontend scene is ready for conversation (LiveKit DataChannel only).

        Sent by the JS SDK over the LiveKit DataChannel once the visual
        scene has finished initialising. Handled by the Live Avatar Service
        in production; provided here so reference implementations of that
        role can react to it. No payload.
        """

    @abstractmethod
    async def on_input_text(self, request_id: str, text: str) -> None:
        """
        User provided text input.

        Args:
            request_id: Unique request identifier.
            text: User input text.
        """

    @abstractmethod
    async def on_asr_partial(self, request_id: str, text: str, seq: int) -> None:
        """
        Streaming ASR result (not yet final).

        Args:
            request_id: Unique request identifier.
            text: Partial ASR text.
            seq: Sequence number.
        """

    @abstractmethod
    async def on_asr_final(self, request_id: str, text: str) -> None:
        """
        Final ASR result.

        Args:
            request_id: Unique request identifier.
            text: Final ASR text.
        """

    @abstractmethod
    async def on_voice_start(self, request_id: str) -> None:
        """
        Voice activity detected (user started speaking).

        Args:
            request_id: Unique request identifier.
        """

    @abstractmethod
    async def on_voice_finish(self, request_id: str) -> None:
        """
        Voice activity ended (user stopped speaking).

        Args:
            request_id: Unique request identifier.
        """

    @abstractmethod
    async def on_response_start(
        self, request_id: str, response_id: str, audio_config: Optional[dict]
    ) -> None:
        """
        Response generation started.

        Args:
            request_id: Request identifier.
            response_id: Unique response identifier.
            audio_config: Optional audio configuration (speed, volume, mood, etc.).
        """

    @abstractmethod
    async def on_chunk_received(
        self, request_id: str, response_id: str, seq: int, text: str
    ) -> None:
        """
        Response text chunk received (in sequence order).

        Args:
            request_id: Request identifier.
            response_id: Response identifier.
            seq: Sequence number within response.
            text: Text chunk.
        """

    @abstractmethod
    async def on_response_done(self, request_id: str, response_id: str) -> None:
        """
        Response generation complete.

        Args:
            request_id: Request identifier.
            response_id: Response identifier.
        """

    @abstractmethod
    async def on_response_audio_start(self, request_id: str, response_id: str) -> None:
        """
        TTS audio output started.

        Args:
            request_id: Request identifier.
            response_id: Response identifier.
        """

    @abstractmethod
    async def on_response_audio_finish(self, request_id: str, response_id: str) -> None:
        """
        TTS audio output finished.

        Args:
            request_id: Request identifier.
            response_id: Response identifier.
        """

    @abstractmethod
    async def on_response_audio_prompt_start(self) -> None:
        """Idle-prompt audio starting."""

    @abstractmethod
    async def on_response_audio_prompt_finish(self) -> None:
        """Idle-prompt audio finished."""

    @abstractmethod
    async def on_response_cancel(self, response_id: str) -> None:
        """
        Response stream cancelled.

        Args:
            response_id: Response identifier.
        """

    @abstractmethod
    async def on_idle_trigger(self, reason: str, idle_time_ms: int) -> None:
        """
        Avatar has been idle for a period.

        Args:
            reason: Reason for idle trigger.
            idle_time_ms: Idle time in milliseconds.
        """

    @abstractmethod
    async def on_system_prompt(self, text: str) -> None:
        """
        System pushed idle-wakeup text for TTS playback.

        Args:
            text: Prompt text.
        """

    @abstractmethod
    async def on_control_interrupt(self, request_id: Optional[str]) -> None:
        """
        Interrupt received (optionally targeting a specific request).

        Args:
            request_id: Optional request to interrupt; if None, interrupt all.
        """

    @abstractmethod
    async def on_error(self, request_id: Optional[str], code: str, message: str) -> None:
        """
        Error received from the avatar service.

        Args:
            request_id: Optional request identifier associated with error.
            code: Error code.
            message: Error message.
        """

    @abstractmethod
    async def on_audio_frame(self, frame: AudioFrame) -> None:
        """
        Binary audio frame received (WebSocket only).

        Args:
            frame: Deserialized audio frame.
        """

    @abstractmethod
    async def on_image_frame(self, frame: ImageFrame) -> None:
        """
        Binary image frame received (WebSocket only, multimodal).

        Args:
            frame: Deserialized image frame.
        """
