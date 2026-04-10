# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Live Avatar Channel SDK is a Python SDK for live avatar WebSocket protocol supporting text and audio communication. It is structured as a Python package with an optional reference server:

- **liveavatar_channel_sdk**: Core SDK library (WebSocket client + protocol implementation)
- **liveavatar_channel_server_example**: Reference FastAPI/ASGI server implementation

**Python 3.9+**, **pip / uv**

## Build & Run Commands

```bash
# Install all dependencies (editable mode)
pip install -e ".[dev]"

# Or with uv
uv sync

# Run tests
pytest

# Run tests with output
pytest -s -v

# Run the reference server (port 8080, ws://localhost:8080/avatar/ws)
uvicorn liveavatar_channel_server_example.main:app --host 0.0.0.0 --port 8080

# Run the client simulator (in a second terminal)
python -m liveavatar_channel_sdk.example.live_avatar_service_simulator
```

Linting uses **ruff** (`ruff check .`) and formatting uses **black** (`black .`). Tests live in `tests/` and are integration-style. Run with `pytest` — no extra configuration needed beyond `pyproject.toml`.

## Architecture

### Two Connection Modes

1. **Inbound Mode** — the live avatar service provides the WebSocket server address; the developer's server connects to it as a client.
2. **Outbound Mode** — the developer's server provides the WebSocket server address; the live avatar service connects to it as a client. Preferred for low-latency, high-concurrency production deployments where the developer can expose a stable public endpoint.

### Two Transport Channels

| Channel | Text | Audio | Video |
|---|---|---|---|
| **WebSocket** (developer-provided) | ✅ JSON events | ✅ Binary frames | ✅ Binary frames (future) |
| **LiveKit Data Channel** | ✅ Same JSON protocol (no heartbeat) | via LiveKit audio track | via LiveKit video track |

### SDK Layers

```
Application (AvatarChannelListener callbacks)
    ↓
Protocol (message.py / audio_frame.py models + event_type.py constants)
    ↓
Transport (avatar_websocket_client.py via websockets / aiohttp)
```

Key classes and their source files:

| Class | File | Purpose |
|---|---|---|
| `AvatarWebSocketClient` | `avatar_websocket_client.py` | Manages lifecycle, sends JSON text and binary audio/image frames, dispatches events |
| `AvatarChannelListener` | `avatar_channel_listener.py` | Abstract base class defining all protocol event callbacks |
| `AvatarChannelListenerAdapter` | `avatar_channel_listener_adapter.py` | No-op base — subclass and override only the methods you need |
| `StreamingResponseHandler` | `streaming_response_handler.py` | `SortedDict`-based in-order delivery of out-of-order `response.chunk` frames |
| `MessageBuilder` | `message_builder.py` | Fluent factory for all JSON protocol messages |
| `AudioFrameBuilder` | `audio_frame_builder.py` | Fluent builder for 9-byte-header binary audio frames |
| `ImageFrameBuilder` | `image_frame_builder.py` | Fluent builder for 12-byte-header binary image frames |
| `ExponentialBackoffStrategy` | `exponential_backoff_strategy.py` | Optional auto-reconnect (1 s → 60 s max); disabled by default |
| `SessionManager` | `session_manager.py` | Server-side async-safe session registry |

## Protocol

### Text Message Format

All text messages are JSON and follow a three-segment naming convention:

```
<domain>.<action>[.<stage>]
```

| Segment | Role | Examples |
|---|---|---|
| **Domain** | Category | `session`, `input`, `response`, `control`, `system`, `error` |
| **Action** | What happens | `init`, `ready`, `text`, `asr`, `chunk`, `done`, `interrupt`, `prompt`, `idleTrigger` |
| **Stage** (optional) | Stream phase | `partial`, `final`, `start`, `finish`, `cancel` |

All event type constants live in `event_type.py` as `EventType(str, Enum)`.

### Event Reference

| Event | Direction | Description |
|---|---|---|
| `session.init` | avatar → developer | Open session, carries `session_id` and `user_id` |
| `session.ready` | developer → avatar | Acknowledge session established |
| `session.state` | avatar → developer | State sync with `seq` and `timestamp` |
| `session.closing` | avatar → developer | Avatar service about to close (e.g. timeout) |
| `input.text` | avatar → developer | User typed text input |
| `input.asr.partial` | ASR provider → other | Streaming ASR result (`final: false`) |
| `input.asr.final` | ASR provider → other | Final ASR result |
| `input.voice.start` | ASR provider → other | Voice activity start detected |
| `input.voice.finish` | ASR provider → other | Voice activity end detected |
| `response.start` | developer → avatar | Optional: set TTS `speed`, `volume`, `mood` before chunks |
| `response.chunk` | developer → avatar | Streaming text chunk with `seq` and `timestamp` |
| `response.done` | developer → avatar | End of a streaming response |
| `response.audio.start` | TTS provider → other | Audio output starting |
| `response.audio.finish` | TTS provider → other | Audio output finished |
| `response.audio.prompt_start` | developer → avatar | Idle-prompt audio starting |
| `response.audio.prompt_finish` | developer → avatar | Idle-prompt audio finished |
| `response.cancel` | developer → avatar | Cancel an in-progress response stream |
| `control.interrupt` | developer → avatar | Interrupt current playback; optional `request_id` for precise targeting |
| `system.idle_trigger` | avatar → developer | Avatar has been idle; carries `reason` and `idle_time_ms` |
| `system.prompt` | developer → avatar | Push idle-wakeup text for TTS playback |
| `error` | developer → avatar | Error report with `code` and `message` |

`request_id → response_id` is 1 : N. `seq` within a response increments independently from session-level `seq`.

### Session States

Defined as `SessionState(Enum)` in `session_state.py`:

| State | Speaker | System Behaviour |
|---|---|---|
| `IDLE` | — | Waiting for input |
| `LISTENING` | User | ASR active |
| `THINKING` | System (brain) | LLM / TTS preparing |
| `STAGING` | System (body) | Avatar render preparing |
| `SPEAKING` | System (body) | Avatar outputting response |
| `PROMPT_THINKING` | System (brain) | Preparing idle-wakeup script |
| `PROMPT_STAGING` | System (body) | Avatar render preparing (prompt) |
| `PROMPT_SPEAKING` | System (body) | Avatar playing idle-wakeup audio |

### Heartbeat

WebSocket only: native ping/pong control frames (RFC 6455, `0x9` / `0xA`) handled automatically by the `websockets` library. **No heartbeat on the LiveKit data channel.**

## Binary Frame Formats

### Audio Frame (WebSocket only)

```
| Header (9 bytes) | Audio Payload |
```

Total header = 72 bits. Fields in bit order (high → low):

| Field | Bits | Offset | Values | Notes |
|---|---|---|---|---|
| **T** (Type) | 2 | 70–71 | `01` | Fixed: audio frame |
| **C** (Channel) | 1 | 69 | 0 / 1 | 0 = Mono, 1 = Stereo |
| **K** (Key) | 1 | 68 | 0 / 1 | Keyframe / Opus resync |
| **S** (Seq) | 12 | 56–67 | 0–4095 | Wrapping sequence number |
| **TS** (Timestamp) | 20 | 36–55 | 0–1,048,575 | ms, wrapping |
| **SR** (Sample Rate) | 2 | 34–35 | `00`/`01`/`10` | 16 kHz / 24 kHz / 48 kHz |
| **F** (Samples) | 12 | 22–33 | 0–4095 | Samples per frame (e.g. 640 @ 16 kHz/40 ms) |
| **Codec** | 2 | 20–21 | `00`/`01` | PCM / Opus |
| **R** (Reserved) | 4 | 16–19 | `0000` | Reserved |
| **L** (Length) | 16 | 0–15 | 0–65535 | Payload byte length |

Use Python's `struct` module for packing/unpacking in `audio_frame.py`.

**Jitter buffer rules:**
- `TS` and `Seq` are wrapping counters — use modular arithmetic, never direct comparison.
- Sort by `TS` first (primary), `Seq` second (deduplication).
- Max out-of-order window ≈ 200–500 ms.
- Recommended: 16 kHz mono PCM, 640-sample frames (40 ms).

### Image Frame (WebSocket only, multimodal input)

```
| Header (12 bytes) | Image Payload |
```

Total header = 96 bits. Fields in bit order (high → low):

| Field | Bits | Offset | Values | Notes |
|---|---|---|---|---|
| **T** (Type) | 2 | 94–95 | `10` | Fixed: image frame |
| **V** (Version) | 2 | 92–93 | `00` | Protocol version (reserved) |
| **F** (Format) | 4 | 88–91 | 0–4 | 0=JPG, 1=PNG, 2=WebP, 3=GIF, 4=AVIF |
| **Q** (Quality) | 8 | 80–87 | 0–255 | Encode quality / compression level |
| **ID** (Image ID) | 16 | 64–79 | 0–65535 | Unique ID for fragment reassembly |
| **W** (Width) | 16 | 48–63 | 0–65535 | Pixels |
| **H** (Height) | 16 | 32–47 | 0–65535 | Pixels |
| **L** (Length) | 32 | 0–31 | 0–4,294,967,295 | Payload byte length |

Use Python's `struct` module for packing/unpacking in `image_frame.py`.

## Key Design Decisions

- Auto-reconnect is **opt-in** (`await client.enable_auto_reconnect()`).
- `StreamingResponseHandler` buffers `response.chunk` messages and delivers them in `seq` order via `on_chunk_received()`.
- `control.interrupt` accepts an optional `request_id` to precisely target a specific dialogue turn and avoid spurious interrupts from network jitter.
- `system.idle_trigger` / `system.prompt` implement the cold-start wakeup flow; prompt audio and text do **not** count toward idle time accumulation.
- Server session cleanup (cancel tasks, clear audio buffer, remove mappings) happens in `session_manager.remove_session()`.
- All I/O is `async`/`await` — the SDK is built on `asyncio`. Blocking calls must be run via `asyncio.to_thread()`.
- LiveKit data channel uses the **identical JSON protocol** as WebSocket, minus heartbeat frames.