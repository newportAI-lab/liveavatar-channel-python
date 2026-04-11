"""Fluent factory for building JSON protocol messages.

The MessageBuilder class provides static methods that return dict objects
ready to be serialized as JSON. Each method sets the 'event' field to the
appropriate EventType string value and follows camelCase naming for JSON fields.
Payload data is nested under a 'data' key where the protocol requires it.
"""

from typing import Optional

from liveavatar_channel_sdk.event_type import EventType


class MessageBuilder:
    """Factory for constructing all protocol JSON messages."""

    @staticmethod
    def session_init(session_id: str, user_id: str) -> dict:
        """session.init: Open session with session_id and user_id."""
        return {
            "event": EventType.SESSION_INIT,
            "data": {
                "sessionId": session_id,
                "userId": user_id,
            },
        }

    @staticmethod
    def session_ready() -> dict:
        """session.ready: Acknowledge session established."""
        return {"event": EventType.SESSION_READY}

    @staticmethod
    def session_state(state: str, seq: int, timestamp: int) -> dict:
        """session.state: State sync with seq and timestamp."""
        return {
            "event": EventType.SESSION_STATE,
            "seq": seq,
            "timestamp": timestamp,
            "data": {"state": state},
        }

    @staticmethod
    def input_text(request_id: str, text: str) -> dict:
        """input.text: User typed text input."""
        return {
            "event": EventType.INPUT_TEXT,
            "requestId": request_id,
            "data": {"text": text},
        }

    @staticmethod
    def input_asr_partial(request_id: str, text: str, seq: int) -> dict:
        """input.asr.partial: Streaming ASR result (final: false)."""
        return {
            "event": EventType.INPUT_ASR_PARTIAL,
            "requestId": request_id,
            "seq": seq,
            "data": {"text": text, "final": False},
        }

    @staticmethod
    def input_asr_final(request_id: str, text: str) -> dict:
        """input.asr.final: Final ASR result."""
        return {
            "event": EventType.INPUT_ASR_FINAL,
            "requestId": request_id,
            "data": {"text": text},
        }

    @staticmethod
    def input_voice_start(request_id: str) -> dict:
        """input.voice.start: Voice activity start detected."""
        return {"event": EventType.INPUT_VOICE_START, "requestId": request_id}

    @staticmethod
    def input_voice_finish(request_id: str) -> dict:
        """input.voice.finish: Voice activity end detected."""
        return {"event": EventType.INPUT_VOICE_FINISH, "requestId": request_id}

    @staticmethod
    def response_start(
        request_id: str,
        response_id: str,
        speed: float = 1.0,
        volume: float = 1.0,
        mood: Optional[str] = None,
    ) -> dict:
        """response.start: Optional message to set TTS speed, volume, mood before chunks."""
        audio_config: dict = {"speed": speed, "volume": volume}
        if mood is not None:
            audio_config["mood"] = mood
        return {
            "event": EventType.RESPONSE_START,
            "requestId": request_id,
            "responseId": response_id,
            "data": {"audioConfig": audio_config},
        }

    @staticmethod
    def response_chunk(
        request_id: str, response_id: str, seq: int, timestamp: int, text: str
    ) -> dict:
        """response.chunk: Streaming text chunk with seq and timestamp."""
        return {
            "event": EventType.RESPONSE_CHUNK,
            "requestId": request_id,
            "responseId": response_id,
            "seq": seq,
            "timestamp": timestamp,
            "data": {"text": text},
        }

    @staticmethod
    def response_done(request_id: str, response_id: str) -> dict:
        """response.done: End of a streaming response."""
        return {
            "event": EventType.RESPONSE_DONE,
            "requestId": request_id,
            "responseId": response_id,
        }

    @staticmethod
    def response_audio_start(request_id: str, response_id: str) -> dict:
        """response.audio.start: Audio output starting."""
        return {
            "event": EventType.RESPONSE_AUDIO_START,
            "requestId": request_id,
            "responseId": response_id,
        }

    @staticmethod
    def response_audio_finish(request_id: str, response_id: str) -> dict:
        """response.audio.finish: Audio output finished."""
        return {
            "event": EventType.RESPONSE_AUDIO_FINISH,
            "requestId": request_id,
            "responseId": response_id,
        }

    @staticmethod
    def response_audio_prompt_start() -> dict:
        """response.audio.promptStart: Idle-prompt audio starting."""
        return {"event": EventType.RESPONSE_AUDIO_PROMPT_START}

    @staticmethod
    def response_audio_prompt_finish() -> dict:
        """response.audio.promptFinish: Idle-prompt audio finished."""
        return {"event": EventType.RESPONSE_AUDIO_PROMPT_FINISH}

    @staticmethod
    def response_cancel(response_id: str) -> dict:
        """response.cancel: Cancel an in-progress response stream."""
        return {
            "event": EventType.RESPONSE_CANCEL,
            "responseId": response_id,
        }

    @staticmethod
    def control_interrupt(request_id: Optional[str] = None) -> dict:
        """control.interrupt: Interrupt current playback; optional request_id for targeting."""
        msg = {"event": EventType.CONTROL_INTERRUPT}
        if request_id is not None:
            msg["requestId"] = request_id
        return msg

    @staticmethod
    def system_idle_trigger(reason: str, idle_time_ms: int) -> dict:
        """system.idleTrigger: Avatar has been idle with reason and idle_time_ms."""
        return {
            "event": EventType.SYSTEM_IDLE_TRIGGER,
            "data": {"reason": reason, "idleTimeMs": idle_time_ms},
        }

    @staticmethod
    def system_prompt(text: str) -> dict:
        """system.prompt: Push idle-wakeup text for TTS playback."""
        return {"event": EventType.SYSTEM_PROMPT, "data": {"text": text}}

    @staticmethod
    def error(code: str, message: str, request_id: Optional[str] = None) -> dict:
        """error: Error report with code and message, optional request_id."""
        msg: dict = {
            "event": EventType.ERROR,
            "data": {"code": code, "message": message},
        }
        if request_id is not None:
            msg["requestId"] = request_id
        return msg
