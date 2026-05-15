# Live Avatar Channel SDK (Python)

**English** | [中文](./README.zh.md)

A Python SDK for the Live Avatar WebSocket protocol. Connect your AI backend to a live avatar service with text, audio, and image communication.

**Version 0.2.0** -- simplified Agent API with just 3 public types.

## Requirements

- Python 3.9+
- `websockets >= 12`
- `httpx >= 0.25`

No other runtime dependencies.

## Installation

```bash
# Editable install with all dev dependencies
pip install -e ".[dev]"

# Or with uv
uv sync
```

## Quick Start

The SDK exposes three types:

| Type | Purpose |
|---|---|
| `AvatarAgent` | Single entry point -- lifecycle (start/stop) and all 17 `send_*()` methods |
| `AgentListener` | Callback interface -- override the events you care about (all methods are no-ops by default) |
| `AvatarAgentConfig` | Configuration dataclass -- `api_key`, `avatar_id`, `base_url`, `sandbox`, `timeout`, `developer_tts`, `developer_asr`, `voice_id`, `reconnect` |

### 1. Implement a listener

```python
from liveavatar_channel_sdk import AgentListener

class MyAgent(AgentListener):
    async def on_text_input(self, text: str, request_id: str) -> None:
        """Core callback: user text received."""
        reply = await my_ai.chat(text)

        # Stream the response back
        await self.agent.send_response_start(request_id, "resp-1")
        await self.agent.send_response_chunk(
            request_id, "resp-1", seq=0, timestamp=0, text=reply,
        )
        await self.agent.send_response_done(request_id, "resp-1")

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

    await agent.stop()   # idempotent -- closes WS + calls /session/stop

asyncio.run(main())
```

That is the complete pattern. `start()` blocks until the `session.init` handshake completes (or a timeout occurs). The `session.ready` reply is sent automatically -- you do not need to send it manually.

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
| `send_response_start(request_id, response_id, *, speed, volume, mood)` | `response.start` | Optional: configure TTS parameters before streaming |
| `send_response_chunk(request_id, response_id, seq, timestamp, text)` | `response.chunk` | Streaming text chunk |
| `send_response_done(request_id, response_id)` | `response.done` | End of streaming response |
| `send_response_cancel(response_id)` | `response.cancel` | Cancel an in-progress response stream |

### Developer TTS (you provide audio frames directly)

| Method | Event | Description |
|---|---|---|
| `send_response_audio_start(request_id, response_id)` | `response.audio.start` | Signal that audio output is starting |
| `send_audio_frame(frame: AudioFrame)` | *(binary)* | Send a binary audio frame (9-byte header + PCM/Opus) |
| `send_response_audio_finish(request_id, response_id)` | `response.audio.finish` | Signal that audio output finished |
| `send_prompt_audio_start()` | `response.audio.promptStart` | Idle-prompt audio starting |
| `send_prompt_audio_finish()` | `response.audio.promptFinish` | Idle-prompt audio finished |

### Developer ASR / Omni (you run ASR + VAD on raw audio)

| Method | Event | Description |
|---|---|---|
| `send_voice_start(request_id)` | `input.voice.start` | Voice activity detected |
| `send_asr_partial(request_id, text, seq)` | `input.asr.partial` | Streaming ASR result (partial) |
| `send_voice_finish(request_id)` | `input.voice.finish` | Voice activity ended |
| `send_asr_final(request_id, text)` | `input.asr.final` | Final ASR result |

### Control

| Method | Event | Description |
|---|---|---|
| `send_interrupt(request_id=None)` | `control.interrupt` | Proactive, business-logic-driven interrupt. Optional `request_id` for precise targeting. |
| `send_prompt(text)` | `system.prompt` | Push idle-wakeup text for TTS playback |

### Error

| Method | Event | Description |
|---|---|---|
| `send_error(code, message, request_id=None)` | `error` | Report an error to the platform |

## Listener Callbacks

Override these on `AgentListener`. All are `async` with default no-op implementations.

| Callback | Trigger | When to override |
|---|---|---|
| `on_text_input(text, request_id)` | User text received (typing or platform ASR) | **Core** -- respond to user messages here |
| `on_session_init(session_id, user_id)` | Handshake complete | Logging, metrics |
| `on_session_state(state: SessionState)` | Session state changed | UI sync, debugging |
| `on_session_closing(reason)` | Platform about to close connection | Graceful shutdown |
| `on_idle_trigger(reason, idle_time_ms)` | Prolonged user inactivity | Send idle-wakeup prompt |
| `on_audio_frame(frame: AudioFrame)` | Raw binary audio from platform | Developer ASR mode only |
| `on_error(code, message)` | Error from platform or transport | Error handling / fallback |
| `on_closed(code, reason)` | WebSocket connection closed | Cleanup, reconnect logic |

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
| `reconnect` | `False` | Enable auto-reconnect on disconnect |
| `reconnect_base_delay` | `1.0` | Base delay for exponential backoff (seconds) |
| `reconnect_max_delay` | `60.0` | Maximum delay for exponential backoff (seconds) |

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
6. `stop()` disconnects the WebSocket and calls `POST /v1/session/stop`.

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
