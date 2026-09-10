# Response Lifecycle and Streaming System Prompt Design

## Scope

Upgrade the WebSocket Agent Python SDK from version `0.3.0` to `0.4.0` with
response-specific lifecycle observation and streaming `system.prompt` support.
The existing one-shot `AvatarAgent.send_prompt()` API and its wire behavior remain
unchanged. This change does not add RTC transport support or alter provider content
generation.

The SDK must stop treating session-level state as evidence that a particular
response completed. It will expose `response.state` directly and correlate locally
created prompt streams by their response identity.

## Public API

### Lifecycle event model

Add an immutable `ResponseStateEvent` dataclass with these fields:

```python
session_id: str
request_id: str
response_id: str
seq: int
timestamp: int
state: str
reason: str | None
```

`state` and `reason` remain strings rather than closed enums. Current protocol
values may be documented as constants, but unknown future values must reach the
application unchanged and must not terminate the receive loop. Unknown additional
JSON fields are ignored.

Add a default no-op callback to `AgentListener`:

```python
async def on_response_state(self, event: ResponseStateEvent) -> None:
    ...
```

Every valid, non-stale lifecycle event is delivered through this callback,
including events for responses that this SDK process did not create.

### Prompt stream

Add `AvatarAgent.prompt_stream()`:

```python
def prompt_stream(
    self,
    request_id: str,
    *,
    response_id: str | None = None,
) -> PromptStream:
    ...
```

The SDK generates a UUID response ID when one is not supplied. Blank request or
response IDs are rejected locally. The returned object exposes read-only
`request_id` and `response_id` properties and is used as an async context manager:

```python
async with agent.prompt_stream("course-step-42") as prompt:
    await prompt.send("Now let's look at the next question.")
    await prompt.send("Take your time.")

terminal = await prompt.wait_finished()
```

`__aenter__` registers the pending response before sending
`system.prompt.start`. It does not wait for `ACCEPTED`. `send()` emits
`system.prompt.chunk` with sequence numbers starting at 1 and a Unix millisecond
timestamp. A successful context exit sends `system.prompt.done`; an exceptional
exit marks the local stream closed without inventing a platform terminal event.
There is no prompt-specific cancel wire event in the supplied protocol.

`done()` means only that text production ended. `wait_finished()` waits for the
first platform `REJECTED` or `FINISHED` event and returns that
`ResponseStateEvent`. Cancelling the waiting coroutine does not alter platform
state or synthesize a lifecycle result. A caller may invoke `wait_finished()`
after leaving the stream context.

Duplicate `done()`, `send()` after `done()`, re-entry, and concurrent terminal
operations raise `PromptStreamStateError`. Concurrent `send()` calls are
serialized and receive unique, monotonically increasing sequence numbers in lock
acquisition order. Failed sends do not consume a sequence number. Empty text is
allowed because the protocol only requires non-empty identities.

Export `PromptStream`, `PromptStreamStateError`, and `ResponseStateEvent` from the
package root.

## Wire Messages

Add event constants and message builders for:

```text
system.prompt.start
system.prompt.chunk
system.prompt.done
response.state
```

The prompt builders require non-empty `requestId` and `responseId`. Chunk builders
require an integer `seq >= 1`, an integer timestamp, and text. They produce the
exact camelCase payloads in the handoff document. No metadata extension is added
to these new messages because it is not defined by the protocol.

The legacy `system.prompt` builder and `send_prompt(text, metadata=None)` remain
byte-for-byte compatible in structure.

## Lifecycle Coordination

Introduce a focused coordinator owned by `AvatarAgent`. It maintains:

- the last accepted lifecycle sequence for each session;
- pending responses keyed by `(session_id, response_id)`;
- each pending response's expected `request_id`, latest event, first terminal
  event, and completion future.

Prompt registration requires an established `AvatarAgent.session_id` and occurs
under the coordinator lock before the start message is sent. If sending start
fails, registration is rolled back and its future is failed with the same
exception. Registration rejects a duplicate `(session_id, response_id)` rather
than replacing an existing response.

On receipt of a syntactically valid `response.state` event, the coordinator:

1. Under its lock, drops the event when `seq` is less than or equal to the last
   accepted sequence for that session. Sequence gaps are accepted.
2. Advances the session sequence watermark.
3. Looks up `(session_id, response_id)` and verifies the stored request ID.
4. Updates a matching pending response unless it already has a terminal event.
5. Records and completes the future only for the first `REJECTED` or `FINISHED`.
6. Releases the lock before completing futures or invoking application callbacks.

An identity mismatch neither updates nor completes the local response, but the
event is still delivered to `on_response_state` so the application can observe
and report it. A duplicate or older event is not redelivered because
`sessionId + seq` is the event identity for online deduplication.

Pending terminal results remain available through their `PromptStream` handle.
The coordinator removes them when the agent stops; outstanding waiters are
cancelled without fabricating a platform reason. Reconnection does not reset the
per-session sequence watermark or promise replay. Starting a new session resets
all lifecycle state.

The WebSocket client parses the event into `ResponseStateEvent` and passes it to
the coordinator bridge. Malformed required fields are logged and isolated to that
message, consistent with the existing receive-loop behavior.

## Integration with Existing Response APIs

The current `ResponseStream` already establishes a stable response identity for
text responses when `send_start=True`. This upgrade will make explicit identity
establishment the default for newly created `ResponseStream` instances, while
retaining the `send_start` argument as a deprecated compatibility override for
callers that deliberately target an older server. It also registers the response
before sending start and adds `ResponseStream.wait_finished()` with the same
terminal and cancellation semantics as `PromptStream.wait_finished()`. Existing
low-level `send_response_start/chunk/done` methods retain their signatures and
validation; `send_response_start()` likewise registers before its wire send so
lifecycle callbacks can correlate responses created through the low-level API.

For low-level response methods, the raw `on_response_state` callback is the
observation API; no new global `AvatarAgent.wait_for_response(response_id)` method
is added. This avoids ambiguous lookup when sessions change and prevents an
unbounded public result registry. Applications wanting an awaitable should use
`ResponseStream` or `PromptStream`.

The lifecycle coordinator is transport-response tracking, distinct from the
existing `_ResponseLifecycle`, which serializes outbound text response streams.
They will not be merged: one owns inbound platform lifecycle events and futures;
the other owns outbound chunk ordering. This keeps the change surgical and avoids
changing established response streaming behavior.

No lifecycle completion is inferred from `session.state`, `response.done`,
`response.audio.finish`, WebSocket closure, or local task cancellation.

## Error and Compatibility Behavior

- Unknown lifecycle state or reason values are delivered as raw strings.
- Missing or wrongly typed required lifecycle fields invalidate only that event.
- A callback exception is logged and suppressed by the existing listener bridge.
- A terminal reason is never interpreted as success by the SDK; applications
  advance work only when `state == "FINISHED"` and `reason == "COMPLETED"`.
- First-terminal-wins applies even if a later terminal has a higher event sequence.
- Legacy one-shot prompt behavior does not register a locally awaitable response.
- Streaming prompt support is opt-in by calling `prompt_stream()`; documentation
  will state that it requires a dispatcher version supporting the new protocol.

## Files and Documentation

Expected production changes are limited to:

- `event_type.py` and `message_builder.py` for wire definitions;
- a new lifecycle model/coordinator module;
- a new prompt stream module;
- `_ws_client.py` and `avatar_agent.py` for receive/send integration;
- `__init__.py` for public exports;
- `pyproject.toml`, `README.md`, `README.zh.md`, `PROTOCOL.md`, and
  `PROTOCOL.zh.md` for versioning and migration guidance.

Tests will live in focused lifecycle and prompt-stream test modules, with small
additions to existing message-builder, WebSocket routing, package-export, and
version checks.

## Verification

Implementation follows red-green-refactor. Tests must demonstrate:

1. Exact prompt start/chunk/done wire shapes and local identity validation.
2. Registration happens before start can receive an immediate lifecycle event.
3. Chunks send immediately without waiting for `ACCEPTED`.
4. Concurrent sends produce unique sequence numbers starting at 1.
5. `done()` is not completion; only a matching terminal lifecycle event completes
   `wait_finished()`.
6. Duplicate and older session sequences are ignored, while sequence gaps work.
7. The first terminal cannot be overwritten.
8. Request-ID mismatches cannot complete a local pending response.
9. Unknown state/reason and unknown local response IDs still reach the callback.
10. Delayed `session.state=IDLE` has no effect on response completion.
11. Cancellation and WebSocket/media completion never synthesize `COMPLETED`.
12. The legacy `send_prompt()` payload remains unchanged.
13. Existing tests, `ruff check .`, and `black --check .` pass.
14. Package metadata and both READMEs report version `0.4.0`.
