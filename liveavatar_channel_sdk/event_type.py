from enum import Enum


class EventType(str, Enum):
    """Protocol event type constants following the domain.action[.stage] naming convention."""

    # Session events
    SESSION_INIT = "session.init"
    SESSION_READY = "session.ready"
    SESSION_STATE = "session.state"
    SESSION_CLOSING = "session.closing"
    SESSION_STOP = "session.stop"

    # Scene events (LiveKit DataChannel only; JS SDK → Live Avatar Service)
    SCENE_READY = "scene.ready"

    # Input events
    INPUT_TEXT = "input.text"
    INPUT_ASR_PARTIAL = "input.asr.partial"
    INPUT_ASR_FINAL = "input.asr.final"
    INPUT_VOICE_START = "input.voice.start"
    INPUT_VOICE_FINISH = "input.voice.finish"

    # Response events
    RESPONSE_START = "response.start"
    RESPONSE_CHUNK = "response.chunk"
    RESPONSE_DONE = "response.done"
    RESPONSE_AUDIO_START = "response.audio.start"
    RESPONSE_AUDIO_FINISH = "response.audio.finish"
    RESPONSE_AUDIO_PROMPT_START = "response.audio.promptStart"
    RESPONSE_AUDIO_PROMPT_FINISH = "response.audio.promptFinish"
    RESPONSE_CANCEL = "response.cancel"

    # Control events
    CONTROL_INTERRUPT = "control.interrupt"

    # System events
    SYSTEM_IDLE_TRIGGER = "system.idleTrigger"
    SYSTEM_PROMPT = "system.prompt"

    # Error events
    ERROR = "error"
