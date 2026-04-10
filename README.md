# Live Avatar Channel SDK (Python)

**English** | [中文](./README.zh.md)

A Python SDK for the Live Avatar WebSocket protocol, supporting text, audio, and image communication between your server and a live avatar service.

## Requirements

- Python 3.9+
- `websockets >= 12`
- `sortedcontainers`

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

## Running the Reference Server

```bash
uvicorn liveavatar_channel_server_example.main:app --host 0.0.0.0 --port 8080
```

The server exposes `ws://localhost:8080/avatar/ws` and echoes every `input.text` message back as a word-by-word streaming response.

## Running the Client Simulator

In a second terminal (while the server is running):

```bash
python -m liveavatar_channel_sdk.example.live_avatar_service_simulator
```

The simulator connects to the reference server and sends a scripted sequence of protocol events.

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

## Protocol Overview

All text messages are JSON with a three-segment event type:

```
<domain>.<action>[.<stage>]
```

Examples: `session.init`, `input.text`, `response.chunk`, `control.interrupt`

### Common Events

| Event | Direction | Description |
|---|---|---|
| `session.init` | avatar → developer | Open session |
| `session.ready` | developer → avatar | Acknowledge session |
| `input.text` | avatar → developer | User typed text |
| `response.chunk` | developer → avatar | Streaming text chunk (with `seq`) |
| `response.done` | developer → avatar | End of streaming response |
| `control.interrupt` | developer → avatar | Interrupt current playback |
| `system.idle_trigger` | avatar → developer | Avatar has been idle |

For the full protocol reference see [`PROTOCOL.md`](PROTOCOL.md).

## Linting & Formatting

```bash
ruff check .
black .
```
