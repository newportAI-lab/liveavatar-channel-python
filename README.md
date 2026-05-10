# Live Avatar Channel SDK (Python)

**English** | [中文](./README.zh.md)

A Python SDK for the Live Avatar WebSocket protocol, supporting text, audio, and image communication between your server and a live avatar service.

## Requirements

- Python 3.9+
- `websockets >= 12`
- `sortedcontainers`
- `httpx >= 0.25`

Optional (reference server only):

- `fastapi >= 0.100`
- `uvicorn >= 0.20`

## Installation

```bash
# Editable install with all dev dependencies
pip install -e ".[dev]"

# With optional server dependencies
pip install -e ".[dev,server]"

# Or with uv
uv sync
```

## Quick Start

### 1. Implement a listener

Subclass `AvatarChannelListenerAdapter` and override only the events you care about:

```python
from liveavatar_channel_sdk import AvatarChannelListenerAdapter, SessionState

class MyListener(AvatarChannelListenerAdapter):
    async def on_session_init(self, session_id: str, user_id: str) -> None:
        print(f"Session opened: {session_id}  user: {user_id}")

    async def on_input_text(self, request_id: str, text: str) -> None:
        print(f"User said: {text}")
        # Send a streaming response back through the client …

    async def on_chunk_received(self, request_id, response_id, seq, text) -> None:
        print(f"[{seq}] {text}", end="", flush=True)
```

### 2. Connect and send messages

```python
import asyncio
from liveavatar_channel_sdk import AvatarWebSocketClient, MessageBuilder

async def main():
    listener = MyListener()
    client = AvatarWebSocketClient("ws://localhost:8080/avatar/ws", listener)

    # Optional: enable auto-reconnect with exponential backoff (1s → 60s)
    await client.enable_auto_reconnect()

    await client.connect()

    # Send a streaming response
    await client.send_response_start("req-1", "resp-1")
    await client.send_response_chunk("req-1", "resp-1", seq=0, timestamp=0, text="Hello ")
    await client.send_response_chunk("req-1", "resp-1", seq=1, timestamp=40, text="world!")
    await client.send_response_done("req-1", "resp-1")

    await asyncio.sleep(1)
    await client.disconnect()

asyncio.run(main())
```

### 3. Build binary frames

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
await client.send_binary(audio_bytes)

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
await client.send_binary(image_bytes)
```

### 4. Manage sessions via REST API

```python
from liveavatar_channel_sdk import SessionClient

client = SessionClient(
    api_key="sk-...",
    # base_url defaults to https://facemarket.ai/vih/dispatcher
    sandbox=True,  # True = adds X-Env-Sandbox header for testing
)

# Start a new session
result = await client.start(avatar_id="avatar-123")
print(result.session_id, result.agent_ws_url, result.user_token)

# Reconnect to an existing session
result = await client.start(avatar_id="avatar-123", session_id="sess-old")

# Stop a session
await client.stop(session_id=result.session_id)

# Release resources
await client.close()
```

### 5. Outbound mode server (FastAPI)

```python
from fastapi import FastAPI, WebSocket
from liveavatar_channel_sdk import (
    AvatarChannelListenerAdapter, WebSocketAdapter, dispatch_text_event
)

app = FastAPI()

class MyOutboundListener(AvatarChannelListenerAdapter):
    def __init__(self, adapter: WebSocketAdapter):
        self._adapter = adapter

    async def on_session_init(self, session_id, user_id):
        await self._adapter.send_session_ready()

    async def on_input_text(self, request_id, text):
        # Stream response back through the adapter
        await self._adapter.send_response_start(request_id, "resp-1")
        await self._adapter.send_response_chunk(request_id, "resp-1", 0, 0, text)
        await self._adapter.send_response_done(request_id, "resp-1")

@app.websocket("/avatar/ws")
async def outbound_ws(ws: WebSocket):
    await ws.accept()
    adapter = WebSocketAdapter(ws)
    listener = MyOutboundListener(adapter)
    async for raw in ws.iter_text():
        await dispatch_text_event(raw, listener)
```

## Running the Reference Server

The reference server demonstrates **Outbound mode** — your server exposes a WebSocket endpoint that the platform connects to.

```bash
uvicorn liveavatar_channel_server_example.main:app --host 0.0.0.0 --port 8080
```

**Endpoints:**

| Endpoint | Purpose |
|---|---|
| `GET /avatar/ws` | Outbound mode WS endpoint — the platform connects here after you call `POST /session/start` |
| `POST /avatar/session/start` | Mock REST API — simulates the platform's session initiation endpoint for local testing |
| `GET /avatar/platform-ws/{session_id}` | Platform simulator WS — sends `session.init` / `input.text` so the Inbound client can test locally |

## Running the Inbound Client Example

The client simulator demonstrates **Inbound mode** — your server calls `POST /session/start` to get an `agentWsUrl`, then connects to the platform as a WebSocket client.

In a second terminal (while the server is running):

```bash
python -m liveavatar_channel_sdk.example.live_avatar_service_simulator
```

**Flow:** REST call → get `agentWsUrl` → connect → receive `session.init` → send `session.ready` → receive `input.text` → send `response.chunk/done`.

Configuration via environment variables:

```bash
PLATFORM_URL=http://localhost:8080 \
API_KEY=sk-local-test-key \
AVATAR_ID=default-avatar \
python -m liveavatar_channel_sdk.example.live_avatar_service_simulator
```

## Integration Flow

Both Inbound and Outbound modes use the **same protocol**. The only difference is who initiates the WebSocket connection.

### Outbound Mode (platform connects to you)

1. Register your `wsEndpoint` in the Live Avatar console (one-time config).
2. Call `POST /session/start` with your API Key via `SessionClient`:
   ```python
   from liveavatar_channel_sdk import SessionClient
   client = SessionClient(api_key="sk-...")
   result = await client.start(avatar_id="avatar-123")
   ```
3. The platform connects to your registered `wsEndpoint`.
4. Platform sends `session.init` — reply with `session.ready` via your listener.
5. Exchange protocol events over the WebSocket.
6. Platform returns `{sessionId, userToken, sfuUrl}` — deliver `userToken` + `sfuUrl` to your frontend.

### Inbound Mode (you connect to platform)

1. Enable Inbound mode in the Live Avatar console (one-time).
2. Call `POST /session/start` with your API Key — response includes `agentWsUrl`:
   ```python
   from liveavatar_channel_sdk import SessionClient, AvatarWebSocketClient
   
   client = SessionClient(api_key="sk-...")
   result = await client.start(avatar_id="avatar-123")
   
   listener = MyListener()
   ws = AvatarWebSocketClient(result.agent_ws_url, listener)
   await ws.connect()
   ```
3. Platform sends `session.init` — reply with `session.ready`.
4. Deliver `userToken` + `sfuUrl` from the response to your frontend.
5. Exchange protocol events over the WebSocket.

## Running Tests

```bash
pytest
# With output
pytest -s -v
```

## Architecture

```
Application  (AvatarChannelListener callbacks)
     ↓
Protocol     (message.py / audio_frame.py / image_frame.py + event_type.py)
     ↓
Transport    (AvatarWebSocketClient via websockets)
```

### Two Connection Modes

| Mode | Description |
|---|---|
| **Outbound** | Your server exposes a stable public WebSocket endpoint; the avatar service connects to it. Preferred for production. |
| **Inbound** | The avatar service provides the WebSocket URL; your server connects to it as a client. |

### Key Classes

| Class | Purpose |
|---|---|
| `AvatarWebSocketClient` | Manages lifecycle, sends JSON text and binary frames, dispatches events |
| `AvatarChannelListener` | Abstract base — all protocol event callbacks |
| `AvatarChannelListenerAdapter` | No-op base — subclass and override only what you need |
| `StreamingResponseHandler` | In-order delivery of out-of-order `response.chunk` frames |
| `MessageBuilder` | Fluent factory for all JSON protocol messages |
| `AudioFrameBuilder` | Fluent builder for 9-byte-header binary audio frames |
| `ImageFrameBuilder` | Fluent builder for 12-byte-header binary image frames |
| `ExponentialBackoffStrategy` | Optional auto-reconnect (1 s → 60 s); disabled by default |
| `SessionManager` | Server-side async-safe session registry |
| `SessionClient` | Async REST client for `POST /v1/session/start` and `/v1/session/stop` |
| `SessionStartResult` | Typed response from `/session/start` (session_id, tokens, URLs) |
| `SessionStartError` | Structured exception for platform error codes (40001–40007) |
| `MessageSender` | ABC mixin — implement `send_json`/`send_binary` to get all `send_*()` helpers |
| `WebSocketAdapter` | Wraps a server-side `fastapi.WebSocket` as a `MessageSender` for Outbound mode |
| `dispatch_text_event` | Shared function routing every protocol text event to listener callbacks |

## Protocol Overview

All text messages are JSON with a three-segment event type:

```
<domain>.<action>[.<stage>]
```

Examples: `session.init`, `input.text`, `response.chunk`, `control.interrupt`

### Common Events

**Platform → Developer** (developer receives via listener callbacks):

| Event | Description |
|---|---|
| `session.init` | Open session (sent immediately after WS connects) |
| `session.state` | State sync (`IDLE` / `LISTENING` / `THINKING` / `SPEAKING` / …) |
| `session.closing` | Connection about to close (e.g. timeout) |
| `scene.ready` | JS SDK → avatar, LiveKit DataChannel only |
| `input.text` | User typed text (forwarded from frontend) |
| `response.audio.start` | TTS audio starting — **sent by platform when platform provides TTS** |
| `response.audio.finish` | TTS audio finished — **sent by platform when platform provides TTS** |
| `system.idleTrigger` | Avatar has been idle (`reason`, `idle_time_ms`) |

**Developer → Platform** (developer sends via `client.send_*()` or adapter):

| Event | Description |
|---|---|
| `session.ready` | Handshake response — **must** send after `session.init` |
| `session.stop` | Request to end the current session |
| `input.asr.partial` | Streaming ASR result (`final: false`) — **when developer provides ASR (Omni mode)** |
| `input.asr.final` | Final ASR result — **when developer provides ASR (Omni mode)** |
| `input.voice.start` | Voice activity start — **when developer provides ASR (Omni mode)** |
| `input.voice.finish` | Voice activity end — **when developer provides ASR (Omni mode)** |
| `response.start` | Optional: configure TTS params (`speed`, `volume`, `mood`) |
| `response.chunk` | Streaming text chunk with `seq` and `timestamp` |
| `response.done` | End of streaming response |
| `response.cancel` | Cancel an in-progress response stream |
| `response.audio.start` | TTS audio starting — **when developer provides TTS** |
| `response.audio.finish` | TTS audio finished — **when developer provides TTS** |
| `response.audio.promptStart` | Sent before idle-prompt audio starts |
| `response.audio.promptFinish` | Sent after idle-prompt audio finishes |
| `control.interrupt` | Programmatic interrupt for business-logic-driven stops; **not** needed for input-driven flows (platform auto-clears on `input.text` / `input.voice.start`) |
| `system.prompt` | Push idle-wakeup text for TTS playback |
| `error` | Error report with `code` and `message` |

> **Bidirectional events:** `input.asr.*` / `input.voice.*` are sent by whoever provides ASR (developer in Omni mode, platform otherwise). `response.audio.*` events are sent by whoever provides TTS (platform by default, developer when using custom TTS). The SDK provides both listener callbacks (receive) and send helpers (transmit) for these events.

For the full protocol reference see [`PROTOCOL.md`](PROTOCOL.md).

## Linting & Formatting

```bash
ruff check .
black .
```
