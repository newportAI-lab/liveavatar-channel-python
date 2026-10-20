# Live Avatar Channel SDK (Python)

**English** | [中文](./README.zh.md)

A Python SDK for the Live Avatar WebSocket protocol. Connect your AI backend to a live avatar service with text, audio, and image communication.

**Version 0.4.2**

## Installation

```bash
pip install liveavatar-channel-sdk
```

## Development Install

```bash
# Editable install with all dev dependencies
pip install -e ".[dev]"

# Or with uv
uv sync
```

## Requirements

- Python 3.9+
- `websockets >= 12`
- `httpx >= 0.25`

No other runtime dependencies.

## Quick Start

The SDK's core public types:

| Type | Purpose |
|---|---|
| `AvatarAgent` | Single entry point -- lifecycle (start/stop) and all 17 `send_*()` methods |
| `AgentListener` | Callback interface -- override the events you care about (all methods are no-ops by default) |
| `AvatarAgentConfig` | Configuration dataclass -- `api_key`, `avatar_id`, `base_url`, `sandbox`, `timeout`, `developer_tts`, `developer_asr`, `voice_id`, `voice_config`, `reconnect` |

Additional types include `ResponseStream`, `PromptStream`,
`ResponseStateEvent`, their state errors, binary frame types, and session models.

### 1. Implement a listener

```python
from liveavatar_channel_sdk import AgentListener, ResponseStateEvent

class MyAgent(AgentListener):
    async def on_text_input(self, text: str, request_id: str) -> None:
        response = self.agent.response_stream(request_id)
        async with response:
            async for token in my_ai.stream(text):
                await response.send_chunk(token)

        terminal = await response.wait_finished()
        if terminal.state == "FINISHED" and terminal.reason == "COMPLETED":
            advance_business_workflow(request_id)

    async def on_response_state(self, event: ResponseStateEvent) -> None:
        print(event.response_id, event.state, event.reason)

    async def on_session_init(self, session_id: str, user_id: str) -> None:
        print(f"Session opened: {session_id}  user: {user_id}")
```

### 2. Create the agent and start

```python
import asyncio
from liveavatar_channel_sdk import AvatarAgent, AvatarAgentConfig

async def main():
    listener = MyAgent()
    config = AvatarAgentConfig(
        api_key="sk-...",
        avatar_id="avatar-123",
        # base_url defaults to https://facemarket.ai/vih/dispatcher
        # sandbox=True   # adds X-Env-Sandbox header
    )
    agent = AvatarAgent(config, listener)
    listener.agent = agent   # bidirectional reference

    result = await agent.start()   # REST + WS + auto session.ready handshake
    print(f"Session: {result.session_id}")
    print(f"User token: {result.user_token}")
    print(f"SFU URL: {result.sfu_url}")

    # ... wait for callbacks ...

    await agent.stop()   # idempotent -- sends session.stop, then closes WS

asyncio.run(main())
```

That is the complete pattern. `start()` blocks until the `session.init` handshake completes (or a timeout occurs). The `session.ready` reply is sent automatically -- you do not need to send it manually.

### Response-stream migration

`response_stream()` is the recommended API. It creates one `response_id`, keeps
the sequence numbers in order, and sends `response.done` when its async context
exits normally. Propagate the inbound `request_id` unchanged; do not generate it
from wall-clock time.

The lower-level response methods remain callable with their existing signatures,
but `send_response_start`, `send_response_chunk`, `send_response_done`, and
`send_response_cancel` are deprecated. For a legacy integration, create exactly
one response ID before the first chunk and reuse it through `done`:

```python
import uuid

response_id = str(uuid.uuid4())
await agent.send_response_start(request_id, response_id)
await agent.send_response_chunk(request_id, response_id, 0, timestamp, token)
await agent.send_response_done(request_id, response_id)
```

If an active legacy response receives a different `response_id` in a chunk or
done call, the SDK sends the active ID and emits a `DeprecationWarning` so the
caller can migrate safely. A wrong `request_id` is never rewritten: it raises
`ResponseStreamStateError` before sending. The preserved
`send_response_cancel(response_id)` signature has no `request_id`; it cancels
only when that response ID has exactly one active legacy response. Zero or
multiple matches raise `ResponseStreamStateError`.

By default, `response_stream()` registers the generated response identity before
sending `response.start`. Set `send_start=False` only when deliberately targeting
an older dispatcher. `response.done` means that text production ended; it does
not mean avatar playback finished. `wait_finished()` resolves only from the first
matching platform `REJECTED` or `FINISHED` lifecycle event.

### Streaming system prompts

Use `prompt_stream()` when an idle or course prompt is produced incrementally:

```python
async with agent.prompt_stream("course-step-42") as prompt:
    await prompt.send("Now let's look at the next question.")
    await prompt.send("Take your time.")

terminal = await prompt.wait_finished()
if terminal.state == "FINISHED" and terminal.reason == "COMPLETED":
    advance_course_once()
```

The SDK generates one `response_id`, sends `system.prompt.start`, numbers chunks
from 1, and sends `system.prompt.done` on normal context exit. Chunks may be sent
immediately; they do not wait for `ACCEPTED`. The older `send_prompt()` remains a
one-shot compatibility API with unchanged behavior.

Streaming prompts require a dispatcher that supports
`system.prompt.start/chunk/done` and `response.state`.

Do not use `session.state=IDLE`, `response.done`, `system.prompt.done`,
`response.audio.finish`, a media-track end, or local task cancellation as proof
that a response completed. Business progression requires the expected
`response_id` with `state == "FINISHED"` and `reason == "COMPLETED"`.

## Build Binary Frames

You only need binary frames for **Developer TTS** mode (`AudioFrame`) or **multimodal image input** (`ImageFrame`).

```python
from liveavatar_channel_sdk import AudioFrameBuilder, ImageFrameBuilder

# 16 kHz mono PCM audio (640 samples / 40 ms)
audio_bytes = (
    AudioFrameBuilder()
    .mono()
    .sample_rate_16k()
    .pcm()
    .seq(0)
    .timestamp(0)
    .samples(640)
    .payload(pcm_data)
    .build()
)
await agent.send_audio_frame(audio_bytes)

# JPEG image frame
image_bytes = (
    ImageFrameBuilder()
    .jpeg()
    .quality(85)
    .image_id(1)
    .size(1280, 720)
    .payload(jpeg_data)
    .build()
)
# Send via WebSocket binary message (image frames are not yet exposed
# as a dedicated send method -- use the internal transport directly
# if needed).
```

The raw `AudioFrame` dataclass is also available for direct construction:

```python
from liveavatar_channel_sdk import AudioFrame

frame = AudioFrame(
    channel=0, seq=100, timestamp=5000,
    sample_rate=0, samples=640, codec=0,
    payload=pcm_data,
)
packed = frame.pack()   # bytes (9-byte header + payload)
```

## Send Methods

All send methods are available on `AvatarAgent`. They are grouped by protocol role.

### Platform TTS (default -- platform renders audio from text)

| Method | Event | Description |
|---|---|---|
| `send_response_start(request_id, response_id, *, speed, volume, mood, metadata=None)` | `response.start` | Deprecated; optional TTS configuration before streaming |
| `send_response_chunk(request_id, response_id, seq, timestamp, text, metadata=None)` | `response.chunk` | Deprecated; streaming text chunk |
| `send_response_done(request_id, response_id, metadata=None)` | `response.done` | Deprecated; end of streaming response |
| `send_response_cancel(response_id)` | `response.cancel` | Deprecated; cancel an in-progress response stream by exact response ID |

### Developer TTS (you provide audio frames directly)

| Method | Event | Description |
|---|---|---|
| `send_response_audio_start(request_id, response_id, metadata=None)` | `response.audio.start` | Signal that audio output is starting |
| `send_audio_frame(frame: AudioFrame)` | *(binary)* | Send a binary audio frame (9-byte header + PCM/Opus) |
| `send_response_audio_finish(request_id, response_id, metadata=None)` | `response.audio.finish` | Signal that audio output finished |
| `send_prompt_audio_start()` | `response.audio.promptStart` | Idle-prompt audio starting |
| `send_prompt_audio_finish()` | `response.audio.promptFinish` | Idle-prompt audio finished |
| `send_external_audio(pcm, timestamp_us=0)` | *(binary)* | External PCM. It is played and does not drive lip sync. Do not use `response.audio.*` |

### Developer ASR / Omni (you run ASR + VAD on raw audio)

| Method | Event | Description |
|---|---|---|
| `send_voice_start(request_id, metadata=None)` | `input.voice.start` | Voice activity detected |
| `send_asr_partial(request_id, text, seq, metadata=None)` | `input.asr.partial` | Streaming ASR result (partial) |
| `send_voice_finish(request_id, metadata=None)` | `input.voice.finish` | Voice activity ended |
| `send_asr_final(request_id, text, metadata=None)` | `input.asr.final` | Final ASR result |

### Control

| Method | Event | Description |
|---|---|---|
| `send_interrupt(request_id=None, metadata=None, interrupt_scope=None)` | `control.interrupt` | Stop voice, clear external audio, or both. See the scope table below |
| `send_prompt(text, metadata=None)` | `system.prompt` | Push idle-wakeup text for TTS playback |

`send_interrupt` adds the string parameter `interrupt_scope`.

| Value | Effect |
|---|---|
| omitted, empty, or `VOICE_ONLY` | Stop voice playback. External audio continues |
| `BGM_ONLY` | Clear queued external audio. Voice playback continues |
| `VOICE_AND_ACCOMPANIMENT` | Stop voice playback and clear queued external audio |

The value is sent as `data.interruptScope` on `control.interrupt`. Leading and trailing spaces are removed. Any other value is rejected before sending. Audio that belongs to the base video is not cleared.

`AvatarAgentConfig` adds the optional parameter `external_audio_config`.

| Field | Values |
|---|---|
| `sampleRate` | `0` or omitted follows the session voice format. Otherwise 16000, 24000, 44100, or 48000 |
| `channels` | `0` or omitted follows the session voice format. Otherwise 1 or 2 |

It is sent as `externalAudioConfig` on session start. `send_external_audio(pcm, timestamp_us=0)` is a new method. `pcm` is 16-bit little-endian PCM, and `timestamp_us` of `0` lets the platform choose the presentation time. Its sample rate and channel count must match `external_audio_config` when that parameter is set. When it is not set, they must match the TTS audio format used for this session.

One binary frame, including its header, must not exceed 65536 bytes. A larger frame closes the WebSocket. Send each later packet before the audio already queued has finished playing. For example, do not wait a full 200 ms before sending the next 200 ms packet. Make the first packet longer than the later packets, while still staying under the 65536-byte limit, so playback has audio waiting when it starts.

`metadata` is optional business context merged into the message `data` payload.
It is useful for correlating multi-step application flows such as interviews,
where the same exchange spans prompt, ASR, response, and control events.
Metadata cannot override reserved protocol data fields such as `text`,
`final`, or `audioConfig`.

### Error

| Method | Event | Description |
|---|---|---|
| `send_error(code, message, request_id=None)` | `error` | Report an error to the platform |

### Custom

| Method | Event | Description |
|---|---|---|
| `send_custom_event(request_id, event, data=None)` | *(custom)* | Send an application-specific event not defined in the standard protocol |

## Listener Callbacks

Override these on `AgentListener`. All are `async` with default no-op implementations.

| Callback | Trigger | When to override |
|---|---|---|
| `on_text_input(text, request_id)` | User text received (typing or platform ASR) | **Core** -- respond to user messages here |
| `on_session_init(session_id, user_id)` | Handshake complete | Logging, metrics |
| `on_session_state(state: SessionState)` | Session state changed | UI sync, debugging |
| `on_response_state(event: ResponseStateEvent)` | Response lifecycle update | Completion, rejection, interruption, and failure handling |
| `on_resource_transition(data: ResourceTransitionData)` | Renderer is about to switch video resources | Logging, analytics, business sync |
| `on_session_closing(reason)` | Platform about to close connection | Graceful shutdown |
| `on_idle_trigger(reason, idle_time_ms)` | Prolonged user inactivity | Send idle-wakeup prompt |
| `on_scene_ready()` | Frontend scene ready (platform forwards `scene.ready`) | Begin the conversation |
| `on_audio_frame(frame: AudioFrame)` | Raw binary audio from platform | Developer ASR mode only |
| `on_error(code, message)` | Error from platform or transport | Error handling / fallback |
| `on_closed(code, reason)` | WebSocket connection closed | Cleanup, reconnect logic |

### Video Resource Transition Callback

`scene.resourceTransition` is delivered only to the agent WebSocket when the
renderer has finished the current video and is about to switch to the next
configured video resource. It is a one-way notification: returning from the
callback does not acknowledge, cancel, or delay the renderer switch.

```python
class MyListener(AgentListener):
    async def on_resource_transition(self, data: ResourceTransitionData) -> None:
        logger.info(
            "avatar video switched: %s -> %s",
            data.previous_resource_id,
            data.next_resource_id,
        )
```

Field meanings:

| Field | Required | Meaning |
|---|---|---|
| `previous_resource_id` | Yes | Stable business ID of the video resource being switched away from. It is not a URL, file path, or display name. |
| `next_resource_id` | Yes | Stable business ID of the video resource the renderer is about to switch to. It is not a URL, file path, or display name. |
| `message` | No | Human-readable context from the platform. Treat it as optional diagnostic text and do not branch business logic on it. |

`session_id`, `request_id`, and `timestamp` are message envelope fields, not
fields inside `ResourceTransitionData`. The event intentionally does not expose
`stream_id` because the active WebSocket session already scopes the stream. If
the platform sends a malformed payload with either resource ID missing or blank,
the SDK drops it and does not invoke `on_resource_transition`.

## AvatarAgentConfig

| Field | Default | Description |
|---|---|---|
| `api_key` | *(required)* | Platform API Key (server-side only) |
| `avatar_id` | *(required)* | Unique avatar identifier |
| `base_url` | `https://facemarket.ai/vih/dispatcher` | Platform base URL |
| `sandbox` | `False` | Enable sandbox mode (adds `X-Env-Sandbox` header) |
| `timeout` | `30.0` | HTTP request + handshake timeout in seconds |
| `developer_tts` | `False` | Set to `True` when you provide TTS audio frames |
| `developer_asr` | `True` | Developer runs ASR + VAD by default; set to `False` for platform ASR |
| `voice_id` | `None` | Override the avatar's default voice |
| `voice_config` | `None` | Optional `/session/start` voice settings: `volume`, `speed`, `stability`, `similarity_boost`, `style`, `pitch` |
| `reconnect` | `True` | Enable auto-reconnect on disconnect |
| `reconnect_base_delay` | `1.0` | Base delay for exponential backoff (seconds) |
| `reconnect_max_delay` | `60.0` | Maximum delay for exponential backoff (seconds) |

Example:

```python
config = AvatarAgentConfig(
    api_key="sk-...",
    avatar_id="avatar-123",
    voice_config={
        "volume": 80,
        "speed": 1.25,
        "stability": 0.6,
        "similarity_boost": 0.7,
        "style": 0.2,
        "pitch": 1.1,
    },
)
```

The SDK sends this as `voiceConfig` in `/session/start`; `similarity_boost` is serialized as `similarityBoost`.

## Architecture

```
Developer code (implements AgentListener, calls agent.start() / agent.send_*())
    |
    v
AvatarAgent  (single entry point: lifecycle, REST, WS, event dispatch)
    |         internal: _AvatarWsClient / MessageBuilder / AudioFrameBuilder
    v
Platform (Live Avatar Service)
```

The SDK handles everything inside `start()`:

1. Creates an HTTPX client with your API Key.
2. Calls `POST /v1/session/start` with your `avatar_id`.
3. Connects to the returned `agentWsUrl` via WebSocket.
4. Waits for `session.init` and replies `session.ready` automatically.
5. Dispatches incoming events to your `AgentListener` callbacks.
6. `stop()` sends `session.stop` over the WebSocket, then disconnects.

### Session States

The platform sends `session.state` events as the session transitions. States are defined in `SessionState`:

| State | Speaker | System Behaviour |
|---|---|---|
| `IDLE` | -- | Waiting for input |
| `LISTENING` | User | ASR active |
| `THINKING` | System (brain) | LLM / TTS preparing |
| `STAGING` | System (body) | Avatar render preparing |
| `SPEAKING` | System (body) | Avatar outputting response |
| `PROMPT_THINKING` | System (brain) | Preparing idle-wakeup script |
| `PROMPT_STAGING` | System (body) | Avatar render preparing (prompt) |
| `PROMPT_SPEAKING` | System (body) | Avatar playing idle-wakeup audio |

## Running the Example

The SDK includes a simulator that demonstrates the Agent pattern end-to-end.

You need a running platform endpoint. For local testing you can point it at any server that implements the Live Avatar WebSocket protocol.

```bash
# Set your platform details
PLATFORM_URL=http://localhost:8080 \
API_KEY=sk-local-test-key \
AVATAR_ID=default-avatar \
python -m liveavatar_channel_sdk.example.live_avatar_service_simulator
```

The simulator (`live_avatar_service_simulator.py`) shows the full pattern: it creates an `AgentListener`, wires it to an `AvatarAgent`, starts the session, echoes user input word-by-word, then stops cleanly.

## Protocol Overview

All text messages are JSON with a three-segment event type:

```
<domain>.<action>[.<stage>]
```

Examples: `session.init`, `input.text`, `response.chunk`, `control.interrupt`

### Events Received (via AgentListener callbacks)

| Event | Callback | Description |
|---|---|---|
| `session.init` | `on_session_init` | Open session (SDK auto-replies `session.ready`) |
| `session.state` | `on_session_state` | State sync with `seq` and `timestamp` |
| `session.closing` | `on_session_closing` | Platform about to close (e.g. timeout) |
| `scene.ready` | `on_scene_ready` | Frontend scene ready; conversation may begin |
| `scene.resourceTransition` | `on_resource_transition` | Renderer is about to switch video resources |
| `input.text` | `on_text_input` | User typed text or platform ASR final result |
| `system.idleTrigger` | `on_idle_trigger` | Avatar has been idle (`reason`, `idle_time_ms`) |
| `error` | `on_error` | Error from platform |
| *(binary audio)* | `on_audio_frame` | Raw audio frame (Developer ASR mode only) |

### Events Sent (via agent.send_*() methods)

| Event | Send Method | Description |
|---|---|---|
| `response.start` | `send_response_start` | Optional: configure TTS speed/volume/mood |
| `response.chunk` | `send_response_chunk` | Streaming text chunk |
| `response.done` | `send_response_done` | End of streaming response |
| `response.cancel` | `send_response_cancel` | Cancel an in-progress stream |
| `response.audio.start` | `send_response_audio_start` | Developer TTS: audio starting |
| `response.audio.finish` | `send_response_audio_finish` | Developer TTS: audio finished |
| `response.audio.promptStart` | `send_prompt_audio_start` | Idle-prompt audio starting |
| `response.audio.promptFinish` | `send_prompt_audio_finish` | Idle-prompt audio finished |
| `input.voice.start` | `send_voice_start` | Developer ASR: voice activity start |
| `input.voice.finish` | `send_voice_finish` | Developer ASR: voice activity end |
| `input.asr.partial` | `send_asr_partial` | Developer ASR: partial recognition |
| `input.asr.final` | `send_asr_final` | Developer ASR: final recognition |
| `control.interrupt` | `send_interrupt` | Proactive interrupt (business-logic-driven) |
| `system.prompt` | `send_prompt` | Push idle-wakeup text |
| `error` | `send_error` | Error report |
| *(custom)* | `send_custom_event` | Application-specific event not in the standard protocol |

> **Bidirectional events:** `input.asr.*` / `input.voice.*` are sent by whoever provides ASR (developer in Omni mode, platform otherwise). The SDK provides both listener callbacks (receive) and send helpers (transmit) for these events. Set `developer_asr=True` in your config when your code runs ASR.

For the full protocol specification see [`PROTOCOL.md`](PROTOCOL.md).

### Heartbeat

WebSocket native ping/pong control frames (RFC 6455, `0x9` / `0xA`) are handled automatically by the `websockets` library with `ping_interval=5` s.

## Running Tests

```bash
pytest
# With output
pytest -s -v
```

## Linting & Formatting

```bash
ruff check .
black .
```
