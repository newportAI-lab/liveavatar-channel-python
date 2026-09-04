# Response Stream Lifecycle Design

## Problem

The wire protocol treats a response as a stateful stream: every
`response.chunk` in one response uses the same `requestId` and `responseId`,
and the stream ends with `response.done` using those same identifiers. The
current Python API exposes start, chunk, and done as unrelated stateless send
operations. A caller can therefore generate a new `responseId` for every
chunk; the SDK sends those messages even though the dispatcher rejects them.

The SDK must prevent that failure without breaking the signatures of the
existing Python methods. It must also provide a higher-level API in which
identifier reuse and stream termination are automatic.

## Goals

- Preserve the current Python method signatures and argument order.
- Make correctly ordered legacy calls reuse one active `responseId`.
- Prevent overlapping text responses on one `AvatarAgent`.
- Reject lifecycle errors that cannot be inferred safely, especially a
  mismatched `request_id`.
- Add `ResponseStream` as the recommended response API.
- Keep the existing JSON wire format unchanged.

## Non-goals

- Supporting multiple concurrent text responses on one agent.
- Guessing that two different `request_id` values refer to the same turn.
- Making `AvatarAgent` safe to use from multiple OS threads or event loops.
- Changing developer-TTS audio stream lifecycle in this change.
- Changing dispatcher behavior or the protocol event schema.

## Chosen Compatibility Strategy

The existing public methods remain callable with their existing signatures:

```python
await agent.send_response_start(request_id, response_id, ...)
await agent.send_response_chunk(request_id, response_id, seq, timestamp, text, ...)
await agent.send_response_done(request_id, response_id, ...)
await agent.send_response_cancel(response_id)
```

The first start or chunk establishes the active `(request_id, response_id)`.
While that response is active, the SDK owns the identifiers used on the wire.
A later chunk or terminal operation that supplies another `response_id` does
not send the bad value: the SDK emits `DeprecationWarning` and sends the active
ID instead. This specifically repairs callers that generate a UUID for every
chunk while retaining their source-compatible call shape.

A different `request_id` is never rewritten. The SDK cannot know whether it
is a caller typo or another turn, so it raises `ResponseStreamStateError`
before sending anything.

The legacy methods are documented as deprecated, but they remain available.
No runtime warning is emitted merely for using a legacy method; warnings are
reserved for a supplied `response_id` that the SDK must override. This avoids
warning every existing correct integration while still identifying broken
identifier management.

## Lifecycle State

`AvatarAgent` owns at most one active text response:

```python
@dataclass
class _ActiveResponse:
    request_id: str
    response_id: str
    next_seq: int = 0
    owner: object | None = None
```

`owner` distinguishes a `ResponseStream` instance from legacy method calls so
that legacy calls cannot mutate a stream owned by the new API and one stream
instance cannot operate on another stream's state.

An `asyncio.Lock` protects each lifecycle transition and its associated
WebSocket send as one critical section. This prevents two asyncio tasks from
simultaneously observing no active response and creating different responses.
The SDK continues to support one event loop only; it does not claim OS-thread
safety.

The state and lock live in a focused internal module rather than adding all
lifecycle logic directly to `avatar_agent.py`. `AvatarAgent` delegates state
transitions to that internal component while retaining responsibility for
transport access.

## Legacy Method Semantics

### `send_response_start`

- With no active response, store the supplied identifiers and send
  `response.start`.
- With any active response, raise `ResponseStreamStateError` without sending.
- A failed WebSocket send does not leave a newly created active response.

### `send_response_chunk`

- With no active response, establish one from the supplied identifiers and
  send the chunk. `response.start` remains optional and is not synthesized.
- With an active response and a different `request_id`, raise
  `ResponseStreamStateError` without sending.
- With an active response and a different supplied `response_id`, emit
  `DeprecationWarning` and send the active response ID.
- Require `seq == next_seq`. Duplicate, decreasing, or skipped sequence
  numbers raise `ResponseStreamStateError` without sending.
- Increment `next_seq` only after a successful send.
- If the first chunk send fails, remove the active response created for it.

### `send_response_done`

- Require an active legacy response.
- Require the active `request_id`; a different value raises
  `ResponseStreamStateError`.
- Override a different supplied `response_id` with the active ID and emit
  `DeprecationWarning`.
- Clear active state only after `response.done` is sent successfully. A failed
  send leaves the response active so the caller can retry or cancel it.

### `send_response_cancel`

- Require an active legacy response.
- Override a different supplied `response_id` with the active ID and emit
  `DeprecationWarning`.
- Clear active state only after `response.cancel` is sent successfully.
- Calling cancel without an active response raises
  `ResponseStreamStateError`; the SDK no longer sends cancellation for an
  unknown response.

### `send_interrupt`

`send_interrupt` remains an explicit business-level operation. It neither
finishes nor clears the active response. Code that abandons a response must
cancel or finish it explicitly. This prevents local lifecycle state from
silently diverging from dispatcher state.

## `ResponseStream` API

`ResponseStream` is a public type exported from the package root. Applications
normally create it through `AvatarAgent.response_stream`, not by constructing
it directly.

```python
def response_stream(
    self,
    request_id: str,
    *,
    speed: float = 1.0,
    volume: float = 1.0,
    mood: str | None = None,
    metadata: dict | None = None,
    send_start: bool = False,
) -> ResponseStream:
    ...
```

```python
class ResponseStream:
    @property
    def request_id(self) -> str: ...

    @property
    def response_id(self) -> str: ...

    async def send_chunk(
        self,
        text: str,
        *,
        timestamp: int | None = None,
        metadata: dict | None = None,
    ) -> None: ...

    async def done(self, metadata: dict | None = None) -> None: ...
    async def cancel(self) -> None: ...
```

The SDK generates `response_id` once with `uuid.uuid4()` when the stream is
created. Entering the async context claims the agent's single active response;
if another response is active, entry raises `ResponseStreamStateError`.

When `send_start=True`, entering sends `response.start` using the factory's
audio configuration and metadata. When false, entry only claims the response
and the first chunk is the first wire event. `send_chunk` assigns `seq`
automatically starting at zero. If `timestamp` is omitted, it uses Unix epoch
milliseconds (`time.time_ns() // 1_000_000`), matching the protocol's JSON
timestamp examples; it is not truncated like a binary audio-frame timestamp.

Normal context exit sends `response.done` unless `done()` or `cancel()` has
already terminated the stream. Exceptional exit attempts
`response.cancel`, preserves the original exception, and attaches a cancel
failure as an exception note on Python versions that support notes; on older
supported versions it logs the cancel failure. It never replaces or suppresses
the original exception.

After successful done or cancel, every mutating method raises
`ResponseStreamStateError`. Re-entering the same stream is also rejected.

Example:

```python
async def on_text_input(self, text: str, request_id: str) -> None:
    async with self.agent.response_stream(request_id) as response:
        async for token in my_ai.stream(text):
            await response.send_chunk(token)
```

## Errors and Public Surface

Add public `ResponseStream` and `ResponseStreamStateError` exports. The error
inherits from `RuntimeError` and its message includes the attempted operation,
the supplied identifiers when available, and the active identifiers. It must
not include chunk text or metadata.

No new runtime dependency is required. The implementation remains compatible
with Python 3.9, so type syntax and exception-note handling must respect that
minimum even though the existing repository uses postponed annotations.

## Interaction With Incoming Turns

The SDK does not automatically interrupt, cancel, or finish an active response
when another input arrives. Application policy decides whether to wait,
cancel, or explicitly interrupt. Attempts to start or send chunks for another
`request_id` while a response remains active fail locally. This makes accidental
overlap visible and prevents rejected dispatcher traffic.

The simulator will keep a reference to its current response task. It will not
unconditionally create overlapping echo tasks. For its simple policy, a new
input while responding is logged and ignored; production applications can
instead cancel their model task and close the stream according to business
requirements.

## Documentation Changes

- Make `ResponseStream` the quick-start and recommended streaming example in
  both READMEs.
- Retain a legacy example that creates one `response_id` per complete response
  and reuses it through done.
- State normative MUST/MUST NOT lifecycle rules immediately before the chunk
  protocol section in both protocol documents.
- Explain that `requestId -> responseId = 1:N` means multiple complete,
  sequential response streams, never one ID per chunk.
- State that inbound `request_id` must be propagated unchanged. Remove or fix
  examples that manufacture request IDs from the current time.
- Document that normal user input does not require `control.interrupt`; a
  response that is abandoned still requires explicit done or cancel.

## Test Strategy

Legacy compatibility tests cover:

- start/chunk/chunk/done sends one response ID;
- first chunk creates state without a start event;
- a newly generated ID on every chunk and done is overridden and warned;
- a mismatched request ID sends nothing and raises;
- duplicate, decreasing, and skipped sequence values send nothing and raise;
- duplicate start and overlapping requests are rejected;
- successful done and cancel clear state;
- failed start/first-chunk sends roll back creation;
- failed chunk does not advance sequence;
- failed done/cancel retains state for retry;
- concurrent first chunks result in one active response and one local error.

`ResponseStream` tests cover:

- one generated ID is used for every event;
- sequence numbers and default timestamps are generated automatically;
- optional start configuration is sent before chunks;
- normal exit automatically sends done;
- explicit done avoids duplicate done on exit;
- exception exit sends cancel and preserves the original exception;
- cancel failure does not replace the original exception;
- overlapping streams, legacy/new API mixing, reuse, and writes after terminal
  state are rejected.

Documentation examples are exercised as focused integration-style tests where
practical. The full `pytest` suite and `ruff check .` must pass.

## Success Criteria

- Existing Python calls require no signature changes.
- A legacy caller that supplies a new response ID for each correctly ordered
  chunk sends one stable ID on the wire and receives a warning locally.
- No response can start while another response is active on the same agent.
- Every successful `ResponseStream` context ends in exactly one done or cancel.
- Invalid request association and sequence transitions fail before a WebSocket
  message is sent.
- The README's primary example cannot express per-chunk response IDs.
