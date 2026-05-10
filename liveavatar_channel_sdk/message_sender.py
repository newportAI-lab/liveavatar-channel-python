"""ABC mixin providing send_*() convenience methods for the Live Avatar protocol.

Concrete transports inherit this and implement :meth:`send_json` and
:meth:`send_binary`, then get all protocol senders for free.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from liveavatar_channel_sdk.audio_frame import AudioFrame
from liveavatar_channel_sdk.image_frame import ImageFrame
from liveavatar_channel_sdk.message_builder import MessageBuilder


class MessageSender(ABC):
    """Mixin providing typed send helpers on top of raw send_json/send_binary."""

    @abstractmethod
    async def send_json(self, message: dict) -> None:
        """Send a JSON text message over the transport."""

    @abstractmethod
    async def send_binary(self, data: bytes) -> None:
        """Send a binary message over the transport."""

    # -- session ----------------------------------------------------------

    async def send_session_ready(self) -> None:
        await self.send_json(MessageBuilder.session_ready())

    async def send_session_closing(self, reason: Optional[str] = None) -> None:
        await self.send_json(MessageBuilder.session_closing(reason))

    async def send_session_stop(self) -> None:
        await self.send_json(MessageBuilder.session_stop())

    # -- scene ------------------------------------------------------------

    async def send_scene_ready(self) -> None:
        await self.send_json(MessageBuilder.scene_ready())

    # -- input (Scenario 2B: Developer ASR / Omni) ------------------------

    async def send_input_voice_start(self, request_id: str) -> None:
        await self.send_json(MessageBuilder.input_voice_start(request_id))

    async def send_input_voice_finish(self, request_id: str) -> None:
        await self.send_json(MessageBuilder.input_voice_finish(request_id))

    async def send_input_asr_partial(
        self, request_id: str, text: str, seq: int
    ) -> None:
        await self.send_json(
            MessageBuilder.input_asr_partial(request_id, text, seq)
        )

    async def send_input_asr_final(self, request_id: str, text: str) -> None:
        await self.send_json(MessageBuilder.input_asr_final(request_id, text))

    # -- response ---------------------------------------------------------

    async def send_response_start(
        self,
        request_id: str,
        response_id: str,
        speed: float = 1.0,
        volume: float = 1.0,
        mood: Optional[str] = None,
    ) -> None:
        await self.send_json(
            MessageBuilder.response_start(
                request_id, response_id, speed, volume, mood
            )
        )

    async def send_response_chunk(
        self,
        request_id: str,
        response_id: str,
        seq: int,
        timestamp: int,
        text: str,
    ) -> None:
        await self.send_json(
            MessageBuilder.response_chunk(
                request_id, response_id, seq, timestamp, text
            )
        )

    async def send_response_done(
        self, request_id: str, response_id: str
    ) -> None:
        await self.send_json(
            MessageBuilder.response_done(request_id, response_id)
        )

    async def send_response_cancel(self, response_id: str) -> None:
        await self.send_json(MessageBuilder.response_cancel(response_id))

    # -- control ----------------------------------------------------------

    async def send_control_interrupt(
        self, request_id: Optional[str] = None
    ) -> None:
        await self.send_json(MessageBuilder.control_interrupt(request_id))

    # -- system -----------------------------------------------------------

    async def send_system_prompt(self, text: str) -> None:
        await self.send_json(MessageBuilder.system_prompt(text))

    # -- error ------------------------------------------------------------

    async def send_error(
        self,
        code: str,
        message: str,
        request_id: Optional[str] = None,
    ) -> None:
        await self.send_json(MessageBuilder.error(code, message, request_id))

    # -- binary frames ----------------------------------------------------

    async def send_audio_frame(self, frame: AudioFrame) -> None:
        await self.send_binary(frame.pack())

    async def send_image_frame(self, frame: ImageFrame) -> None:
        await self.send_binary(frame.pack())
