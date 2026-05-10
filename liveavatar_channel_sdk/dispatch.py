"""Shared text-message dispatch for the Live Avatar Channel protocol.

A single function — :func:`dispatch_text_event` — routes every protocol
text message to the correct :class:`AvatarChannelListener` callback.
Both the WebSocket client (Inbound mode) and server-side message loops
(Outbound mode) share this function so event routing is defined once.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from liveavatar_channel_sdk.avatar_channel_listener import AvatarChannelListener
from liveavatar_channel_sdk.event_type import EventType
from liveavatar_channel_sdk.session_state import SessionState
from liveavatar_channel_sdk.streaming_response_handler import StreamingResponseHandler

logger = logging.getLogger(__name__)


async def dispatch_text_event(
    raw: str,
    listener: AvatarChannelListener,
    streaming: Optional[StreamingResponseHandler] = None,
) -> None:
    """Parse *raw* JSON and route to the matching *listener* callback.

    Args:
        raw: JSON string received over the transport.
        listener: Callback receiver (your :class:`AvatarChannelListener` impl).
        streaming: Optional ``StreamingResponseHandler`` for in-order chunk
            delivery. When ``None``, ``response.chunk`` and ``response.done``
            are delivered directly to the listener (no buffering).
    """
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Received non-JSON text message: %.120s", raw)
        return

    event_type = msg.get("event")
    data = msg.get("data", {})

    try:
        if event_type == EventType.SESSION_INIT:
            await listener.on_session_init(
                session_id=data["sessionId"],
                user_id=data["userId"],
            )

        elif event_type == EventType.SESSION_READY:
            await listener.on_session_ready()

        elif event_type == EventType.SESSION_STATE:
            state = SessionState(data["state"])
            await listener.on_session_state(
                state=state,
                seq=msg["seq"],
                timestamp=msg["timestamp"],
            )

        elif event_type == EventType.SESSION_CLOSING:
            await listener.on_session_closing(reason=data.get("reason"))

        elif event_type == EventType.SESSION_STOP:
            await listener.on_session_stop()

        elif event_type == EventType.SCENE_READY:
            await listener.on_scene_ready()

        elif event_type == EventType.INPUT_TEXT:
            await listener.on_input_text(
                request_id=msg["requestId"],
                text=data["text"],
            )

        elif event_type == EventType.INPUT_ASR_PARTIAL:
            await listener.on_asr_partial(
                request_id=msg["requestId"],
                text=data["text"],
                seq=msg["seq"],
            )

        elif event_type == EventType.INPUT_ASR_FINAL:
            await listener.on_asr_final(
                request_id=msg["requestId"],
                text=data["text"],
            )

        elif event_type == EventType.INPUT_VOICE_START:
            await listener.on_voice_start(request_id=msg["requestId"])

        elif event_type == EventType.INPUT_VOICE_FINISH:
            await listener.on_voice_finish(request_id=msg["requestId"])

        elif event_type == EventType.RESPONSE_START:
            await listener.on_response_start(
                request_id=msg["requestId"],
                response_id=msg["responseId"],
                audio_config=data.get("audioConfig"),
            )

        elif event_type == EventType.RESPONSE_CHUNK:
            if streaming is not None:
                await streaming.handle_chunk(
                    request_id=msg["requestId"],
                    response_id=msg["responseId"],
                    seq=msg["seq"],
                    text=data["text"],
                )
            else:
                await listener.on_chunk_received(
                    request_id=msg["requestId"],
                    response_id=msg["responseId"],
                    seq=msg["seq"],
                    text=data["text"],
                )

        elif event_type == EventType.RESPONSE_DONE:
            if streaming is not None:
                await streaming.handle_done(
                    request_id=msg["requestId"],
                    response_id=msg["responseId"],
                )
            else:
                await listener.on_response_done(
                    request_id=msg["requestId"],
                    response_id=msg["responseId"],
                )

        elif event_type == EventType.RESPONSE_AUDIO_START:
            await listener.on_response_audio_start(
                request_id=msg["requestId"],
                response_id=msg["responseId"],
            )

        elif event_type == EventType.RESPONSE_AUDIO_FINISH:
            await listener.on_response_audio_finish(
                request_id=msg["requestId"],
                response_id=msg["responseId"],
            )

        elif event_type == EventType.RESPONSE_AUDIO_PROMPT_START:
            await listener.on_response_audio_prompt_start()

        elif event_type == EventType.RESPONSE_AUDIO_PROMPT_FINISH:
            await listener.on_response_audio_prompt_finish()

        elif event_type == EventType.RESPONSE_CANCEL:
            if streaming is not None:
                streaming.clear(msg.get("responseId"))
            await listener.on_response_cancel(response_id=msg["responseId"])

        elif event_type == EventType.CONTROL_INTERRUPT:
            await listener.on_control_interrupt(request_id=msg.get("requestId"))

        elif event_type == EventType.SYSTEM_IDLE_TRIGGER:
            await listener.on_idle_trigger(
                reason=data["reason"],
                idle_time_ms=data["idleTimeMs"],
            )

        elif event_type == EventType.SYSTEM_PROMPT:
            await listener.on_system_prompt(text=data["text"])

        elif event_type == EventType.ERROR:
            await listener.on_error(
                request_id=msg.get("requestId"),
                code=data["code"],
                message=data["message"],
            )

        else:
            logger.warning("Unknown event type: %s", event_type)

    except Exception as exc:
        logger.error("Error dispatching %s: %s", event_type, exc)
