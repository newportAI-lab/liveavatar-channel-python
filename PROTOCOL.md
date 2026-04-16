# Protocol Overview

**English** | [中文](./PROTOCOL.zh.md)

This protocol defines the WebSocket communication between the Live Avatar (digital human) service and developer services, covering text, audio, and image content.

Since the Live Avatar system also supports text communication via LiveKit Data Channel, the protocol documentation also covers the Data Channel protocol.

## Design Goals

1. WebSocket and WebRTC Data Channel share the same text protocol format.
2. Semantic message type naming for ease of understanding.
3. Streaming data transmission support.
4. Out-of-order resilience.
5. Extensible to multi-user room scenarios.

## Text Message Type Naming Conventions

We use the term "event" to designate message types. To prevent confusion as the number of message types grows, a specific set of conventions has been established.

### Three-Part Semantic Structure

```
<domain>.<action>[.<stage>]
```

#### 1️⃣ Layer 1: Domain (Category)

| Domain | Meaning |
| --- | --- |
| session | Session lifecycle |
| input | User input |
| response | Model output |
| control | Control signals |
| system | System behavior |
| error | Error |
| tool (future) | Tool calls |

---

#### 2️⃣ Layer 2: Action

Describes "what is being done"

| Action      | Example            |
|-------------|--------------------|
| init        | session.init       |
| ready       | session.ready      |
| text        | input.text         |
| asr         | input.asr          |
| chunk       | response.chunk     |
| done        | response.done      |
| cancel      | response.cancel    |
| interrupt   | control.interrupt  |
| prompt      | system.prompt      |
| idleTrigger | system.idleTrigger |

---

#### 3️⃣ Layer 3: Stage (Optional)

Used for "streaming / state"

| Stage | Example |
| --- | --- |
| partial | input.asr.partial |
| final | input.asr.final |

---

# Text Protocol Design

## WebSocket Inbound / Outbound Modes

### Inbound Mode

In Inbound mode, the Live Avatar service provides the WebSocket server address and the developer service connects to it as a client.

```mermaid
sequenceDiagram
    autonumber
    participant User as User (Frontend SDK)
    participant AppServer as Developer Backend
    participant Platform as Live Avatar Service
    participant RTC as RTC Room (SFU)
    participant Avatar as Avatar Engine

    %% Key difference: entire session establishment is server-side only
    rect rgb(255, 240, 220)
    Note over AppServer, Platform: [Inbound Key Difference]
    AppServer->>Platform: /session/start (API Key)
    Platform->>Avatar: Start avatar
    Avatar->>RTC: Join room
    Avatar->>Platform: Start complete
    Platform->>AppServer: { sessionId, clientToken, agentWsUrl, sfuUrl }
    AppServer-->>Platform: Establish WebSocket connection via agentWsUrl
    Note right of AppServer: No sessionToken or frontend involvement in session setup<br/>AppServer calls /session/start directly with API Key<br/>agentWsUrl returned directly to AppServer (never forwarded to frontend)<br/>AppServer initiates WebSocket connection (developer side is WS client)<br/>Developer side needs no public IP
    end
    AppServer->>User: { clientToken, sfuUrl }

    %% 2. RTC link establishment
    User->>RTC: Join room (clientToken)
    User-->>RTC: Publish text/audio stream

    %% 3. Core business loop
    Platform-->>RTC: Subscribe to user text/audio stream
    Platform->>AppServer: Forward to developer backend via WebSocket

    alt Text mode
        AppServer-->>Avatar: Return reply text
        Avatar->>Avatar: Internal TTS conversion
    else Audio mode
        AppServer-->>Avatar: Return reply audio stream
    end

    %% 4. Avatar feedback
    Avatar->>RTC: Publish avatar audio/video stream
    RTC-->>User: Subscribe and render
```

### Outbound Mode

In Outbound mode, the developer service provides the WebSocket server address and the Live Avatar service connects to it as a client.

```mermaid
sequenceDiagram
    autonumber
    participant User as User (Frontend SDK)
    participant AppServer as Developer Backend
    participant Platform as Live Avatar Service
    participant RTC as RTC Room (SFU)
    participant Avatar as Avatar Engine

    %% Key difference: Outbound mode — backend calls /session/start directly, no sessionToken needed
    rect rgb(220, 245, 220)
    Note over AppServer, Platform: [Outbound Key Difference]
    AppServer->>Platform: /session/start (API Key)
    Platform-->>AppServer: Establish WebSocket connection (platform as Client)
    Note left of AppServer: Developer side must expose public IP/domain<br/>Must handle platform handshake auth<br/>Backend calls /session/start directly with API Key — no sessionToken needed
    Platform->>Avatar: Start avatar
    Avatar->>RTC: Join room
    Avatar->>Platform: Start complete
    Platform->>AppServer: { sessionId, clientToken, sfuUrl }
    end

    AppServer->>User: { clientToken, sfuUrl }

    %% 2. RTC link establishment
    User->>RTC: Join room (clientToken)
    User-->>RTC: Publish text/audio stream

    %% 3. Core business loop
    Platform-->>RTC: Subscribe to user text/audio stream
    Platform->>AppServer: Forward to developer backend via WebSocket

    alt Text mode
        AppServer-->>Avatar: Return reply text
        Avatar->>Avatar: Internal TTS conversion
    else Audio mode
        AppServer-->>Avatar: Return reply audio stream
    end

    %% 4. Avatar feedback
    Avatar->>RTC: Publish avatar audio/video stream
    RTC-->>User: Subscribe and render
```

### Choosing Between the Two Modes

- If your business demands **ultra-low latency and large-scale concurrency stability**, and you have a mature ops team capable of exposing a stable public endpoint, **Outbound** offers better architectural clarity and resource control.
- If you prioritize **rapid delivery and internal network security**, and want to avoid complex firewall traversal, **Inbound** introduces only a negligible performance overhead that is nearly imperceptible under async Java frameworks such as Netty or WebFlux.

> **sessionToken Architecture Rule**
>
> Both Inbound and Outbound modes follow the same auth pattern: the **developer backend** calls `/session/start` directly with an API Key and receives `clientToken + sfuUrl` to distribute to the frontend. A `sessionToken` (obtained via `/auth/getAuthToken`) is **not required** in either mode.
>
> `sessionToken` is only used in lightweight managed modes (fully-managed, API Key-managed) where the **frontend** calls `/session/start` directly and the backend only acts as a token relay — keeping the API Key off the client while avoiding deep backend involvement.

---

## Scenario 1: WebSocket Full Flow (Standard Path)

### 1️⃣ Establishing Connection

#### Live Avatar Service → Developer Backend

> The Live Avatar Service **always** sends `session.init` first, regardless of whether Inbound or Outbound mode is used. Developers do not need to handle any difference in direction between the two modes.

```json
{
  "event": "session.init",
  "data": {
    "sessionId": "sess_123",
    "userId": "u_1"
  }
}
```

---

#### Developer Backend → Live Avatar Service

```json
{
  "event": "session.ready"
}
```

---

### 2️⃣ Heartbeat

Relies on standard WebSocket protocol control frames.

Adheres to the standard WebSocket protocol (RFC 6455):

- **Ping (0x9)**: The server may send Ping frames to the client.
- **Pong (0xA)**: Upon receiving a Ping frame, the client must automatically reply with a Pong frame.

---

### 3️⃣ User Text Input

The Live Avatar Service sends a text input message.

```json
{
  "event": "input.text",
  "requestId": "req_1",
  "data": {
    "text": "What is your name?"
  }
}
```

---

### 4️⃣ Developer Service Streaming Output

#### start (Optional)

Sent by the Developer Service **before** the first `response.chunk`. Use this to configure the TTS engine managed by the Live Avatar Service (speed, volume, mood). Omit it to use default settings. If TTS is provided by the developer, this message is also unnecessary.

```json
{
  "event": "response.start",
  "requestId": "req_1",
  "responseId": "res_1",
  "data": {
    "audioConfig": {
      "speed": 1.0,
      "volume": 1.0,
      "mood": "neutral"
    }
  }
}
```

**`speed` reference**

| Value | Meaning |
| --- | --- |
| 0.5 | Very slow (suitable for teaching / elderly users) |
| 0.8 | Slightly slow |
| 1.0 | Normal (default) |
| 1.2 | Slightly fast |
| 1.5 | Very fast |
| 2.0 | Maximum speed (clarity not guaranteed) |

**`volume` reference**

| Value | Meaning |
| --- | --- |
| 0.0 | Muted |
| 0.5 | Quiet |
| 1.0 | Standard (default) |
| 1.2 | Loud |
| 1.5 | Maximum (may clip) |

**`mood` values** (extensible): `neutral` · `happy` · `sad` · `angry` · `excited` · `calm` · `serious`

---

#### chunk (Text)

```json
{
  "event": "response.chunk",
  "requestId": "req_1",
  "responseId": "res_1",
  "seq": 12,
  "timestamp": 1710000000000,
  "data": {
    "text": "Hello"
  }
}
```

---

#### done (Text)

```json
{
  "event": "response.done",
  "requestId": "req_1",
  "responseId": "res_1"
}
```

---

requestId → responseId = 1:N

`seq` increments sequentially within a single response.

A single response may consist of replies from multiple agents.

---

### 5️⃣ State Synchronization (Sent by the Live Avatar Service)

```json
{
  "event": "session.state",
  "seq": 12,
  "timestamp": 1710000000000,
  "data": {
    "state": "SPEAKING"
  }
}
```

`seq` increments sequentially within a single session. All `state` values (subject to future expansion):

| **State** | **Speaker** | **System Behavior** |
| --- | --- | --- |
| **IDLE** | None | Awaiting input |
| **LISTENING** | User | ASR input capture |
| **THINKING** | System (Mind) | LLM/TTS preparation |
| **STAGING** | System (Body) | Preparing Live Avatar generation |
| **SPEAKING** | System (Body) | Live Avatar: normal response output |
| **PROMPT_THINKING** | System (Mind) | Preparing reminder script |
| **PROMPT_STAGING** | System (Body) | Preparing to generate Live Avatar |
| **PROMPT_SPEAKING** | System (Body) | Live Avatar: broadcasting reminder audio |

---

### 6️⃣ Interrupt (Sent by Developer Service)

```json
{
  "event": "control.interrupt",
  "requestId": "req_2"
}
```

A signal initiated by the Developer Service.

The Live Avatar Service is solely responsible for executing the interrupt action. The logic applies identically to both text input and audio input; the distinction lies in the Developer Service's strategy for determining when to interrupt: Text input → trigger immediately. Audio input → relies on VAD (Voice Activity Detection) or a specific policy.

Providing `requestId` helps ensure that a specific, designated conversation is interrupted precisely, preventing erroneous interruptions caused by network instability. This field is optional.

The following sequence diagram illustrates the interrupt execution flow.

> **Interrupt Ownership Rule — tied to ASR ownership:**
> The party that provides ASR is the only one authorized to issue `control.interrupt`.
>
> | ASR Mode | Who may send `control.interrupt` | Platform auto-interrupt |
> |---|---|---|
> | Platform ASR (Scenario 2A) | Developer **and** Platform | Allowed — platform may auto-interrupt based on its own VAD policy |
> | Developer ASR / Omni (Scenario 2B) | Developer **only** | **Forbidden** — platform MUST NOT send `control.interrupt` |
>
> **Rationale:** In Scenario 2B the developer owns VAD, so only the developer knows when speech boundaries occur. A platform-initiated interrupt in this mode would break the developer's ASR pipeline.
>
> **Note:** Voice interrupt handling differs by ASR mode:
>
> - **Platform ASR** — The platform detects VAD and sends `input.voice.start` to the developer, who may then issue `control.interrupt`. The platform may also auto-interrupt based on its own VAD policy.
> - **Developer ASR / Omni** — The developer receives raw audio Binary Frames (Scenario 2B), runs VAD internally, and is solely responsible for issuing `control.interrupt`. This is the path illustrated in the diagram below.

```mermaid
sequenceDiagram
    autonumber
    participant User as User (Frontend SDK)
    participant AppServer as Developer Backend (Handler)
    participant Task as Response Task (LLM/TTS)
    participant Avatar as Live Avatar Service (Platform/RTC)

    Note over User, Avatar: Case 1: Avatar is speaking, user sends a text message
    User->>AppServer: 1. Send text message (input.text)

    rect rgb(240, 248, 255)
        Note right of AppServer: [Text Hard Interrupt]
        AppServer->>Task: 2. cancelCurrentResponse() (terminate old task)
        AppServer->>Avatar: 3. control.interrupt (flush RTC buffer)
    end

    AppServer->>Task: 4. processTextInput (start new task)
    Task-->>Avatar: 5. Push new reply text/audio
    Avatar-->>User: 6. Render new reply

    Note over User, Avatar: Case 2: Avatar is speaking, user starts speaking (Developer ASR / Omni path)
    Avatar->>AppServer: 7. Binary Frames (continuous raw audio forwarded by platform)

    AppServer->>AppServer: 8. asrService.detectVoiceActivity (VAD triggered internally)

    rect rgb(255, 240, 245)
        Note right of AppServer: [Voice Real-time Interrupt]
        AppServer->>Task: 9. cancelCurrentResponse() (cut off at the source)
        AppServer->>Avatar: 10. control.interrupt (issue command)
    end

    AppServer->>AppServer: 11. Continue ASR recognition & business logic
    Note over User, Avatar: Repeat steps 4-6 for new reply flow
```

---

### 7️⃣ Connection Imminently Closing (Sent by the Live Avatar Service)

```json
{
  "event": "session.closing",
  "data": {
    "reason": "timeout"
  }
}
```

This message is typically sent proactively by the system just before a timeout is declared.

---

## Scenario 2: Real-time Voice Input

> **Design Principle — ASR Ownership:**
> Whoever provides ASR is responsible for producing ASR recognition results and VAD judgments — and for sending the corresponding events.
>
> - **Platform ASR** → Platform runs ASR + VAD and sends `input.asr.*` / `input.voice.*` **to** the Developer Service.
> - **Developer ASR / Omni** → Platform forwards raw audio Binary Frames to the Developer Service; the developer runs ASR + VAD and sends `input.asr.*` / `input.voice.*` **back to** the platform (same events, reversed direction). This keeps the platform state machine in sync and enables conversation logging.

---

### Scenario 2A: Platform ASR

The following events are sent by the **Live Avatar Service (Platform) → Developer Service**.

#### ASR Recognition — Streaming Partial Result

```json
{
  "event": "input.asr.partial",
  "requestId": "req_2",
  "seq": 3,
  "data": {
    "text": "What is your",
    "final": false
  }
}
```

---

#### ASR Recognition — Final Result

```json
{
  "event": "input.asr.final",
  "requestId": "req_2",
  "data": {
    "text": "What is your name?"
  }
}
```

---

#### Voice Activity Detection — Speech Start

```json
{
  "event": "input.voice.start",
  "requestId": "req_1"
}
```

#### Voice Activity Detection — Speech End

```json
{
  "event": "input.voice.finish",
  "requestId": "req_1"
}
```

`input.asr.partial` is optional; sending only `input.asr.final` is acceptable.

👉 The subsequent response workflow is identical to that of text input (Scenario 1).

---

### Scenario 2B: Developer ASR / Omni

When the avatar is configured for developer-provided ASR (including Omni multimodal models), the **Live Avatar Service (Platform) → Developer Service** continuously forwards the user's audio as a raw Binary Frame stream throughout the session. There are no start/finish signaling events — the platform performs no VAD and imposes no segmentation.

#### Continuous Raw Audio Stream

Binary Frames are forwarded using the same binary format defined in the [Audio Protocol](#audio-protocol-design-websocket-channel-only) section.

> The raw audio Binary Frame format is identical to the `response.audio.*` Binary Frame format used for developer-managed TTS output — only the transmission direction is reversed.

The developer runs VAD and ASR internally, then sends the **same `input.voice.*` and `input.asr.*` events back to the platform** (direction reversed compared to Scenario 2A):

| Event | Direction | Purpose |
|---|---|---|
| `input.voice.start` | **Developer → Platform** | Notify platform that user started speaking; triggers LISTENING state |
| `input.asr.partial` | **Developer → Platform** | Stream partial recognition results for real-time display |
| `input.voice.finish` | **Developer → Platform** | Notify platform that user stopped speaking |
| `input.asr.final` | **Developer → Platform** | Send final recognition result; platform advances state machine |

After sending `input.asr.final`, the developer processes the recognized text and responds using the standard response events (Scenario 1, Section 4).

---

### Speech Output Start / End Detection (The party providing TTS is responsible for sending these messages)

#### Speech Output Started

```json
{
  "event": "response.audio.start",
  "requestId": "req_1",
  "responseId": "res_1"
}
```

#### Speech Output Finished

```json
{
  "event": "response.audio.finish",
  "requestId": "req_1",
  "responseId": "res_1"
}
```

**Scenario: TTS provided by the Developer Service**

After sending the "Speech Output Started" message, the developer service pushes the corresponding audio data. Once the audio data transmission is complete, the "Speech Output Finished" message is sent.

**Scenario: TTS provided by the Live Avatar Service**

After sending the "Speech Output Started" message, the Live Avatar Service pushes the corresponding audio data. Once the audio data transmission is complete, the "Speech Output Finished" message is sent.

---

## Scenario 3: Server-Initiated Interaction (Idle Wake-up)

### 1️⃣ Idle Event (Sent by the Live Avatar Service)

```json
{
  "event": "system.idleTrigger",
  "data": {
    "reason": "user_idle",
    "idleTimeMs": 120000
  }
}
```

The system detected that the Live Avatar has been idle for a significant period.

### 2️⃣ Idle Prompt Text Message (Sent by the Developer Service)

```json
{
  "event": "system.prompt",
  "data": {
    "text": "Are you still there?"
  }
}
```

---

Upon receiving this message, the Live Avatar Service will use the configured TTS engine to drive the Live Avatar to speak the specified content.

The prompt text does not count toward the accumulated user idle time.

### 3️⃣ Idle Reminder Start Message (Sent by the Developer Service)

```json
{
  "event": "response.audio.promptStart"
}
```

### 4️⃣ Idle Reminder End Message (Sent by the Developer Service)

```json
{
  "event": "response.audio.promptFinish"
}
```

After sending the Idle Reminder Start message, the Developer Service pushes the corresponding reminder audio. The Idle Reminder End message is sent only after the prompt audio transmission is complete.

Prompt audio does not count toward the accumulated user idle time.

---

## Scenario 4: LiveKit DataChannel (Low-Latency Path)

👉 Core Principle:

**Aside from the fact that ping/pong requests are no longer required, the protocol format remains entirely identical; the only difference is that traffic is routed via RTC.**


---

## Scenario 5: Error Handling (Optional)

### Error (Sent by Developer Service)

```json
{
  "event": "error",
  "requestId": "req_1",
  "data": {
    "code": "ASR_FAIL",
    "message": "audio decode error"
  }
}
```

---

### Stream Cancellation (Sent by Developer Service)

```json
{
  "event": "response.cancel",
  "responseId": "response_1"
}
```

---

# Audio Protocol Design (WebSocket Channel Only)

Audio consists of binary data; each audio packet is encapsulated within the following data structure.

## 📦 Data Structure

```
| Header (9 bytes) | Audio Payload |
```

---

## 🧠 Header Bit Definitions

Total: 8 × 9 = 72 bits

Listed in sequential order, indicating the number of bits occupied by each field.

| Field | Bits | Bit Offset (High → Low) | Range / Values | Description |
| --- | --- | --- | --- | --- |
| **T (Type)** | 2 | 70–71 | `01` | Fixed as Audio Frame |
| **C (Channel)** | 1 | 69 | 0 / 1 | 0=Mono, 1=Stereo |
| **K (Key)** | 1 | 68 | 0 / 1 | Key Frame (First Frame / Opus Resync) |
| **S (Seq)** | 12 | 56–67 | 0–4095 | Sequence Number (Wrapping) |
| **TS (Timestamp)** | 20 | 36–55 | 0–1,048,575 | Timestamp (ms, Wrapping) |
| **SR (SampleRate)** | 2 | 34–35 | 00/01/10 | 00=16kHz, 01=24kHz, 10=48kHz |
| **F (Samples)** | 12 | 22–33 | 0–4095 | Samples per frame (e.g., 24k/40ms = 960) |
| **Codec** | 2 | 20–21 | 00/01 | 00=PCM, 01=Opus |
| **R (Reserved)** | 4 | 16–19 | 0000 | Reserved Bits |
| **L (Length)** | 16 | 0–15 | 0–65535 | Payload Length (Bytes) |

Both Seq and TS are incremental; however, due to their limited bit-widths, they must support wrapping.

### Wrapping Rules

Both TS and Seq function as wrapping counters. The receiving end **must** use modular arithmetic for comparisons; direct comparison based on magnitude is prohibited.

### The Jitter Buffer Must Be Based on TS (Not Seq)

Sorting priority:

1. TS (Primary sorting key)
2. Seq (Secondary key for duplicate removal)

### Packet Loss / Out-of-Order Window

Maximum out-of-order window ≈ 200–500 ms

## 🧠 Audio Payload

This contains the actual raw audio binary data, specifically formatted as PCM or Opus binary data.

Whether the audio data is sent from the Live Avatar Service to a developer, or from a developer to the Live Avatar Service, it must strictly adhere to this format.

---

# Image Protocol Design (WebSocket Channel Only)

Image data is transmitted as binary data; each image packet is encapsulated within the following data structure (this applies exclusively to scenarios involving multimodal image stream input).

## 📦 Data Structure

```
| Header (12 bytes) | Image Payload |
```

## 🧠 Header Bit Definitions

Total: 8 × 12 = 96 bits

The following lists the bit allocation for each field, presented in sequential order.

| Field | Bits | Bit Offset (High → Low) | Range / Values | Description |
| --- | --- | --- | --- | --- |
| **T (Type)** | 2 | 94–95 | `10` | Fixed identifier for image frames |
| **V (Version)** | 2 | 92–93 | `00` | Protocol version (reserved for extensions) |
| **F (Format)** | 4 | 88–91 | 0–4 | 0=JPG, 1=PNG, 2=WebP, 3=GIF, 4=AVIF |
| **Q (Quality)** | 8 | 80–87 | 0–255 | Image quality (encoding quality / compression level) |
| **ID (ImageId)** | 16 | 64–79 | 0–65535 | Unique image identifier (used for fragmentation / reassembly) |
| **W (Width)** | 16 | 48–63 | 0–65535 | Image width (pixels) |
| **H (Height)** | 16 | 32–47 | 0–65535 | Image height (pixels) |
| **L (Length)** | 32 | 0–31 | 0–4,294,967,295 | Payload length (bytes) |
