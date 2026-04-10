# Live Avatar Channel Python SDK — Design Spec

**Date:** 2026-04-10  
**Status:** Approved  
**Scope:** WebSocket channel only (Inbound + Outbound modes); LiveKit Data Channel excluded.

---

## 1. Goals & Non-Goals

**Goals:**
- Python SDK (`liveavatar_channel_sdk`) implementing the Live Avatar WebSocket protocol
- FastAPI reference server (`liveavatar_channel_server_example`) with HTTP session start + WebSocket handler
- Paired simulators for Inbound and Outbound modes that demonstrate the full protocol flow
- Unit tests for binary frame pack/unpack and streaming response ordering

**Non-Goals:**
- LiveKit Data Channel support (future work)
- Real LLM/TTS integration in the example server (echo/simulator only)
- Audio jitter buffer implementation (protocol framing only)

---

## 2. Project Structure

```
liveavatar-channel-python/
├── pyproject.toml                        # Single pyproject, two packages + dev extras
├── CLAUDE.md
├── PROTOCOL.md
├── tests/
│   ├── test_audio_frame.py
│   ├── test_image_frame.py
│   ├── test_message_builder.py
│   └── test_streaming_response_handler.py
│
├── liveavatar_channel_sdk/
│   ├── __init__.py
│   ├── event_type.py                     # EventType(str, Enum)
│   ├── session_state.py                  # SessionState(Enum)
│   ├── message.py                        # Dataclass message models
│   ├── audio_frame.py                    # AudioFrame pack/unpack via struct
│   ├── image_frame.py                    # ImageFrame pack/unpack via struct
│   ├── message_builder.py                # Fluent factory for JSON protocol messages
│   ├── audio_frame_builder.py            # Fluent builder for 9-byte-header binary frames
│   ├── image_frame_builder.py            # Fluent builder for 12-byte-header binary frames
│   ├── avatar_channel_listener.py        # ABC defining all protocol event callbacks
│   ├── avatar_channel_listener_adapter.py # No-op default implementation
│   ├── streaming_response_handler.py     # SortedDict-based in-order chunk delivery
│   ├── exponential_backoff_strategy.py   # 1s→60s auto-reconnect (opt-in)
│   ├── session_manager.py                # Server-side async-safe session registry
│   ├── avatar_websocket_client.py        # Core: connection lifecycle + event dispatch
│   └── example/
│       ├── __init__.py
│       ├── live_avatar_service_inbound_simulator.py
│       └── live_avatar_service_outbound_simulator.py
│
└── liveavatar_channel_server_example/
    ├── __init__.py
    ├── main.py                           # FastAPI app + startup hook
    ├── start_session.py                  # POST /avatar/start → { sessionId, wsUrl }
    └── websocket_handler.py              # WS /avatar/ws/{session_id} (outbound) or inbound connector
```

**Key dependencies:**
| Package | Purpose |
|---|---|
| `websockets>=12` | SDK WebSocket transport |
| `fastapi` + `uvicorn` | Example server |
| `sortedcontainers` | `StreamingResponseHandler` internals |
| `pydantic` | Message model validation (optional) |
| `pytest` + `pytest-asyncio` | Testing |

---

## 3. Architecture

### Two Connection Modes

**Inbound:** Live Avatar service provides the WebSocket server; the developer's server connects as a client.

```
LiveAvatarServiceInboundSimulator        Developer Server Example
     (WS Server, :9090)              ←connect—  (WS Client)
          |                                           |
          |——— session.init ──────────────────────→  |
          |  ←────────── session.ready ────────────  |
          |——— input.text("hello") ────────────────→ |
          | ←─── response.chunk × N + response.done ─|
          |——— session.state(SPEAKING) ─────────────→|
```

**Outbound:** Developer's server provides the WebSocket server; the Live Avatar service connects as a client.

```
LiveAvatarServiceOutboundSimulator       Developer Server Example
     (WS Client)              ——connect→  (WS Server, FastAPI :8080)
          |                                           |
          |  ←────────── session.init ────────────── |
          |——— session.ready ──────────────────────→ |
          |  ←───────── input.text("hello") ──────── |
          |——— response.chunk × N + response.done ──→|
```

**communication:** The complete messages transimited in the websocket channel.

```
live avatar Service  <---WebSocket--->  Developer Server (This Example)
     (Client)                                    (Server)
        |                                           |
        |-------- session.init ------------------>|
        |<------- session.ready -------------------|
        |                                           |
        |-------- input.text("hello") ------------>|
        |                                           | (AI Processing)
        |<------- response.chunk -------------------|
        |<------- response.chunk -------------------|
        |<------- response.done --------------------|
        |                                           |
        |-------- audio frames ------------------->|
        |                                           | (ASR Processing)
        |<------- input.voice.start --------------->|
        |<------- input.asr.partial ----------------|
        |<------- input.asr.final ------------------|
        |<------- input.voice.finish --------------->|
        |                                           | (AI Processing)
        |<------- response.chunk -------------------|
        |<------- response.done --------------------|
        |<------- response.audio.start -------------|
        |<------- response.audio.finish -------------|
        |                                           |
        |-------- system.idleTrigger ------------->|
        |                                           | (Business Logic)
        |<------- system.prompt --------------------|
        |<------- system.promptStart ---------------|
        |<------- system.promptFinish ---------------|
```

### SDK Layers

```
Application (AvatarChannelListener callbacks)
    ↓
Protocol (message.py / audio_frame.py / image_frame.py + event_type.py)
    ↓
Transport (avatar_websocket_client.py via websockets library)
```

---

## 4. SDK Core

### `AvatarWebSocketClient`

Unified interface for both modes:

```python
class AvatarWebSocketClient:
    def __init__(self, listener: AvatarChannelListener): ...

    async def connect(self, url: str) -> None          # Outbound: actively connect to developer WS server
    async def accept(self, websocket) -> None           # Inbound: accept an already-established WS connection
    async def disconnect(self) -> None

    async def send_text(self, message: dict) -> None   # Send JSON message
    async def send_audio(self, frame: bytes) -> None   # Send binary audio frame
    async def send_image(self, frame: bytes) -> None   # Send binary image frame

    async def enable_auto_reconnect(
        self, strategy: ExponentialBackoffStrategy
    ) -> None                                          # opt-in, Outbound mode only
```

`connect()` and `accept()` both set the same internal `_ws` connection object. After either is called, the send/receive logic is identical. Internally, two asyncio tasks are launched:
- `_recv_loop`: receives messages, dispatches to listener callbacks
- Heartbeat is handled automatically by the `websockets` library (native ping/pong)

Binary frames are distinguished from text messages by checking `isinstance(msg, bytes)`.

### `AvatarChannelListener` (ABC)

All callbacks are `async`. Full list:

```python
on_session_init(session_id, user_id)
on_session_ready()
on_session_state(state: SessionState, seq, timestamp)
on_session_closing(reason)
on_input_text(request_id, text)
on_asr_partial(request_id, text, seq)
on_asr_final(request_id, text)
on_voice_start(request_id)
on_voice_finish(request_id)
on_response_start(request_id, response_id, audio_config)
on_chunk_received(request_id, response_id, seq, text)
on_response_done(request_id, response_id)
on_response_audio_start(request_id, response_id)
on_response_audio_finish(request_id, response_id)
on_response_audio_prompt_start()
on_response_audio_prompt_finish()
on_response_cancel(response_id)
on_idle_trigger(reason, idle_time_ms)
on_system_prompt(text)
on_control_interrupt(request_id)
on_error(request_id, code, message)
on_audio_frame(frame: AudioFrame)
on_image_frame(frame: ImageFrame)
```

`AvatarChannelListenerAdapter` provides empty (`pass`) implementations of all methods.

### `StreamingResponseHandler`

- Keyed by `response_id`, each entry is a `SortedDict[seq → text]`
- On each `response.chunk`: insert into sorted dict, deliver all consecutive chunks from current head
- On `response.done`: flush remaining buffered chunks in order, then call `on_response_done`
- Gaps (missing seq) are held in the buffer until filled or `done` received

### `ExponentialBackoffStrategy`

- Initial delay: 1s, max delay: 60s, multiplier: 2×
- Only active when `enable_auto_reconnect()` has been called
- Resets on successful connection
- Outbound mode only (Inbound mode is server-driven)

### `SessionManager`

- `asyncio.Lock`-protected dict mapping `session_id → session_state`
- Methods: `create_session`, `get_session`, `remove_session`
- `remove_session` cancels pending tasks and clears audio buffer refs

---

## 5. Binary Frame Formats

### Audio Frame (9-byte header)

| Field | Bits | Values | Notes |
|---|---|---|---|
| T (Type) | 2 | `01` | Fixed: audio frame |
| C (Channel) | 1 | 0/1 | Mono/Stereo |
| K (Key) | 1 | 0/1 | Keyframe / Opus resync |
| S (Seq) | 12 | 0–4095 | Wrapping sequence number |
| TS (Timestamp) | 20 | 0–1,048,575 | ms, wrapping |
| SR (SampleRate) | 2 | 00/01/10 | 16/24/48 kHz |
| F (Samples) | 12 | 0–4095 | Samples per frame |
| Codec | 2 | 00/01 | PCM/Opus |
| R (Reserved) | 4 | `0000` | Reserved |
| L (Length) | 16 | 0–65535 | Payload byte length |

Packing uses Python `struct` with big-endian byte order. Seq and TS use modular arithmetic for wrap comparison.

### Image Frame (12-byte header)

| Field | Bits | Values | Notes |
|---|---|---|---|
| T (Type) | 2 | `10` | Fixed: image frame |
| V (Version) | 2 | `00` | Reserved |
| F (Format) | 4 | 0–4 | JPG/PNG/WebP/GIF/AVIF |
| Q (Quality) | 8 | 0–255 | Encode quality |
| ID (ImageId) | 16 | 0–65535 | Fragment reassembly |
| W (Width) | 16 | 0–65535 | Pixels |
| H (Height) | 16 | 0–65535 | Pixels |
| L (Length) | 32 | 0–4,294,967,295 | Payload byte length |

---

## 6. Example Server

### Endpoints

| Endpoint | Description |
|---|---|
| `POST /avatar/start` | Create session, return `{ sessionId, wsUrl }` |
| `GET /avatar/ws/{session_id}` | Outbound mode WS endpoint |

### Mode Selection

Environment variable `MODE=inbound|outbound` (default: `outbound`).

- **Outbound**: FastAPI WebSocket endpoint at `/avatar/ws/{session_id}`. On connect, sends `session.init`, waits for `session.ready`, then sends `input.text` events and streams echo chunks back.
- **Inbound**: On app startup, connects to the LiveAvatar WS server URL (from env var `AVATAR_WS_URL`). Registers session and handles events identically to outbound.

### Simulators

**`LiveAvatarServiceInboundSimulator`** (`python -m liveavatar_channel_sdk.example.live_avatar_service_inbound_simulator`):
1. Start `websockets.serve` on `:9090`
2. Accept connection → send `session.init`
3. Wait for `session.ready`
4. Every 3s: send `input.text`
5. Receive and print `response.chunk` until `response.done`
6. Print `session.state` updates

**`LiveAvatarServiceOutboundSimulator`** (`python -m liveavatar_channel_sdk.example.live_avatar_service_outbound_simulator`):
1. Connect to `AVATAR_WS_URL` (default: `ws://localhost:8080/avatar/ws/{session_id}`)
2. Receive `session.init` → send `session.ready`
3. Wait for `input.text`
4. Stream echo response as chunks + done
5. Send `session.state(SPEAKING)` then `session.state(IDLE)`

---

## 7. Testing

| File | Coverage |
|---|---|
| `test_audio_frame.py` | pack→unpack round-trip; wrapping seq/ts boundary values |
| `test_image_frame.py` | pack→unpack round-trip |
| `test_message_builder.py` | All message types, required fields present, JSON structure |
| `test_streaming_response_handler.py` | In-order delivery; out-of-order buffering; gap filling; done flush |

Run: `pytest -s -v`

---

## 8. Error Handling

| Situation | Behaviour |
|---|---|
| `ConnectionClosed` in `_recv_loop` | If auto-reconnect enabled: backoff retry. Otherwise: call `on_session_closing`. |
| JSON parse failure | Log warning, skip message, keep connection alive |
| Unknown event type | Log debug, skip message (forward-compatible) |
| `SessionManager` concurrent access | All operations protected by `asyncio.Lock` |
| `send_*` on closed connection | Raise `ConnectionClosed`; caller decides to reconnect or abort |
