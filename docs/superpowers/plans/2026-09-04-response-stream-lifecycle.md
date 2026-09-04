# Response Stream Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make legacy response send methods enforce one stable response lifecycle without changing their signatures, and add `ResponseStream` as the safe recommended streaming API.

**Architecture:** Add a focused internal lifecycle coordinator owned by each `AvatarAgent`; it stores active responses by `request_id` and serializes state transitions and WebSocket sends under one `asyncio.Lock`. Legacy methods delegate to the coordinator while preserving their signatures, and the public `ResponseStream` uses an owner token so its lifecycle cannot be mixed with legacy calls or another stream for the same request.

**Tech Stack:** Python 3.9+, asyncio, dataclasses, pytest, pytest-asyncio, ruff, black

**Spec:** `docs/superpowers/specs/2026-09-04-response-stream-lifecycle-design.md`

## Global Constraints

- Preserve all existing Python response method signatures and argument order.
- Keep the JSON protocol schema unchanged.
- Permit at most one active text response per `request_id`; allow different
  request IDs to be active concurrently.
- Override a mismatched legacy `response_id` with the active ID and emit `DeprecationWarning`.
- Never infer or rewrite a mismatched `request_id`; raise `ResponseStreamStateError` before sending.
- Keep Python 3.9 compatibility and add no runtime dependency.
- Do not extend this lifecycle state machine to developer-TTS audio events.

## File Map

- Create `liveavatar_channel_sdk/response_stream.py`: public `ResponseStream`, public lifecycle error, and private lifecycle coordinator/state.
- Modify `liveavatar_channel_sdk/avatar_agent.py`: construct the coordinator, delegate legacy methods, and provide the stream factory.
- Modify `liveavatar_channel_sdk/__init__.py`: export the two new public types.
- Create `tests/test_response_stream.py`: coordinator, legacy compatibility, stream lifecycle, failures, and concurrency coverage.
- Modify `tests/test_avatar_agent.py`: update old isolated send tests to valid lifecycle sequences while retaining payload assertions.
- Modify `liveavatar_channel_sdk/example/live_avatar_service_simulator.py`: track `ResponseStream` tasks by request ID and reject only duplicate active deliveries of the same request.
- Modify `README.md`, `README.zh.md`, `PROTOCOL.md`, and `PROTOCOL.zh.md`: make lifecycle rules normative and `ResponseStream` primary.
- Modify `pyproject.toml`: bump the SDK minor version from `0.2.7` to `0.3.0`.

---

### Task 1: Legacy Response Lifecycle Coordinator

**Files:**
- Create: `liveavatar_channel_sdk/response_stream.py`
- Modify: `liveavatar_channel_sdk/avatar_agent.py:150-190,298-333`
- Test: `tests/test_response_stream.py`
- Test: `tests/test_avatar_agent.py:90-185`

**Interfaces:**
- Produces: `ResponseStreamStateError(RuntimeError)`.
- Produces: private `_ResponseLifecycle(send_json: Callable[[dict], Awaitable[None]])` with `legacy_start`, `legacy_chunk`, `legacy_done`, and `legacy_cancel` async methods.
- Produces: `_ActiveResponse(request_id: str, response_id: str, next_seq: int, owner: object | None)`.
- Consumes: existing `MessageBuilder.response_start`, `response_chunk`, `response_done`, and `response_cancel`.

- [ ] **Step 1: Add failing legacy happy-path and automatic-ID-reuse tests**

Create `tests/test_response_stream.py` with a local recording transport and tests equivalent to:

```python
class RecordingWs:
    def __init__(self) -> None:
        self.messages = []

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)


@pytest.mark.asyncio
async def test_legacy_chunks_and_done_reuse_first_response_id(agent):
    ws = RecordingWs()
    agent._ws_client = ws

    await agent.send_response_chunk("req-1", "resp-a", 0, 1000, "first")
    with pytest.warns(DeprecationWarning, match="resp-b"):
        await agent.send_response_chunk("req-1", "resp-b", 1, 1001, "second")
    with pytest.warns(DeprecationWarning, match="resp-c"):
        await agent.send_response_done("req-1", "resp-c")

    assert [message["responseId"] for message in ws.messages] == [
        "resp-a",
        "resp-a",
        "resp-a",
    ]
    assert [message["event"] for message in ws.messages] == [
        EventType.RESPONSE_CHUNK,
        EventType.RESPONSE_CHUNK,
        EventType.RESPONSE_DONE,
    ]
```

Also test `start -> chunk(0) -> chunk(1) -> done` with one stable ID and verify first-chunk-without-start does not synthesize `response.start`.

- [ ] **Step 2: Run the new happy-path tests and verify they fail**

Run: `pytest tests/test_response_stream.py -k "legacy_chunks or legacy_start" -v`

Expected: FAIL because the current methods send each supplied `response_id` and have no lifecycle state.

- [ ] **Step 3: Implement the minimal coordinator and delegate the four legacy methods**

In `response_stream.py`, add the concrete state and error:

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import warnings
from typing import Awaitable, Callable

from liveavatar_channel_sdk.message_builder import MessageBuilder


class ResponseStreamStateError(RuntimeError):
    """Raised when a response operation violates the active stream lifecycle."""


@dataclass
class _ActiveResponse:
    request_id: str
    response_id: str
    next_seq: int = 0
    owner: object | None = None


class _ResponseLifecycle:
    def __init__(self, send_json: Callable[[dict], Awaitable[None]]) -> None:
        self._send_json = send_json
        self._lock = asyncio.Lock()
        self._active: dict[str, _ActiveResponse] = {}
```

Implement these exact transition rules inside the lock:

```python
async def legacy_start(self, request_id, response_id, speed, volume, mood, metadata):
    async with self._lock:
        if request_id in self._active:
            raise self._state_error("start", request_id, response_id)
        self._active[request_id] = _ActiveResponse(request_id, response_id)
        try:
            await self._send_json(
                MessageBuilder.response_start(
                    request_id, response_id, speed, volume, mood, metadata
                )
            )
        except BaseException:
            self._active.pop(request_id, None)
            raise
```

For `legacy_chunk`, establish state only when `request_id` is absent, validate
`seq == next_seq`, warn and replace a mismatched response ID, send, then
increment only on success. Roll back that request's state only if this call
created it and the send fails. For `legacy_done`, require legacy-owned state
under the supplied request ID. For `legacy_cancel`, locate an exact active
response-ID match across the map; if there is no exact match, raise without
sending because the preserved signature contains no request ID and guessing
could affect another request. Both terminal operations clear only their
matched entry after success.

Construct `_ResponseLifecycle(self._send_response_json)` in `AvatarAgent.__init__`, where `_send_response_json` calls `self._require_ws().send_json(message)`. Delegate all four existing public methods without changing their signatures.

- [ ] **Step 4: Run happy-path tests and update isolated existing tests**

Run: `pytest tests/test_response_stream.py -k "legacy_chunks or legacy_start" -v`

Expected: PASS.

Update existing tests that send a first chunk with `seq=3` to use `seq=0`. Update standalone done/cancel tests to establish an active response first, then assert against the final recorded message:

```python
await agent.send_response_chunk("req-1", "resp-1", 0, 1000, "hi")
await agent.send_response_done("req-1", "resp-1")
assert ws.json_messages[-1]["event"] == EventType.RESPONSE_DONE
```

Run: `pytest tests/test_avatar_agent.py -v`

Expected: PASS.

- [ ] **Step 5: Add failing invalid-transition and send-failure tests**

Add parametrized or focused tests proving:

```python
with pytest.raises(ResponseStreamStateError, match="request"):
    await agent.send_response_chunk("req-2", "resp-2", 1, 1001, "wrong turn")

with pytest.raises(ResponseStreamStateError, match="expected seq 1"):
    await agent.send_response_chunk("req-1", "resp-1", 2, 1001, "skipped")
```

Cover duplicate/decreasing/skipped seq, duplicate start for one request,
simultaneous active responses for different requests, done without matching
request state, cancel without an exact active response-ID match, and error
messages that omit chunk text and metadata. Add a `FailingWs` whose selected send number raises `OSError` and
verify start/first-chunk creation rolls back, failed chunk does not increment
seq, and failed done/cancel keeps state available for retry.

- [ ] **Step 6: Run failure tests and verify they fail before completing validation**

Run: `pytest tests/test_response_stream.py -k "mismatch or sequence or duplicate or failure or without_active" -v`

Expected: at least one FAIL until all validation and rollback rules are implemented.

- [ ] **Step 7: Complete transition validation and error messages**

Add helpers with concrete behavior:

```python
def _require_legacy_active(self, operation, request_id=None):
    active = self._active.get(request_id)
    if active is None or active.owner is not None:
        raise ResponseStreamStateError(f"cannot {operation}: no active legacy response")
    return active

def _wire_response_id(self, operation, supplied, active):
    if supplied != active.response_id:
        warnings.warn(
            f"{operation} supplied response_id {supplied!r}; "
            f"using active response_id {active.response_id!r}",
            DeprecationWarning,
            stacklevel=3,
        )
    return active.response_id
```

Ensure `_state_error` includes operation and identifiers but is never passed text or metadata.

- [ ] **Step 8: Verify legacy lifecycle behavior**

Run: `pytest tests/test_response_stream.py tests/test_avatar_agent.py -v`

Expected: PASS.

- [ ] **Step 9: Commit the legacy compatibility layer**

```bash
git add liveavatar_channel_sdk/response_stream.py liveavatar_channel_sdk/avatar_agent.py tests/test_response_stream.py tests/test_avatar_agent.py
git commit -m "fix: enforce legacy response lifecycle"
```

---

### Task 2: Public `ResponseStream` API

**Files:**
- Modify: `liveavatar_channel_sdk/response_stream.py`
- Modify: `liveavatar_channel_sdk/avatar_agent.py`
- Modify: `liveavatar_channel_sdk/__init__.py`
- Test: `tests/test_response_stream.py`

**Interfaces:**
- Consumes: `_ResponseLifecycle` and its request-keyed active-state map and lock from Task 1.
- Produces: `AvatarAgent.response_stream(request_id, *, speed=1.0, volume=1.0, mood=None, metadata=None, send_start=False) -> ResponseStream`.
- Produces: `ResponseStream.send_chunk(text, *, timestamp=None, metadata=None)`, `done(metadata=None)`, and `cancel()`.
- Produces: package-root exports `ResponseStream` and `ResponseStreamStateError`.

- [ ] **Step 1: Write failing public-surface and normal-context tests**

Add tests equivalent to:

```python
def test_response_stream_types_are_exported():
    from liveavatar_channel_sdk import ResponseStream, ResponseStreamStateError
    assert issubclass(ResponseStreamStateError, RuntimeError)


@pytest.mark.asyncio
async def test_response_stream_reuses_id_sequences_chunks_and_auto_dones(agent):
    ws = RecordingWs()
    agent._ws_client = ws

    async with agent.response_stream("req-1") as response:
        response_id = response.response_id
        await response.send_chunk("first", timestamp=1000)
        await response.send_chunk("second", timestamp=1001)

    assert [message["event"] for message in ws.messages] == [
        EventType.RESPONSE_CHUNK,
        EventType.RESPONSE_CHUNK,
        EventType.RESPONSE_DONE,
    ]
    assert {message["responseId"] for message in ws.messages} == {response_id}
    assert [message.get("seq") for message in ws.messages[:2]] == [0, 1]
```

Also assert `request_id` and `response_id` are readable properties and direct `ResponseStream(...)` construction is not part of the documented public workflow.

- [ ] **Step 2: Run the new API tests and verify they fail**

Run: `pytest tests/test_response_stream.py -k "exported or auto_dones" -v`

Expected: FAIL because `ResponseStream` and `response_stream` do not exist.

- [ ] **Step 3: Implement factory, context manager, chunks, and done**

Add lifecycle methods `claim(owner, request_id, response_id, start_message)`,
`stream_chunk(owner, text, timestamp, metadata)`, and
`stream_done(owner, metadata)` that enforce owner identity under the same lock.

Implement the public class with these state fields and transitions:

```python
class ResponseStream:
    def __init__(self, lifecycle, request_id, response_id, *, start_message):
        self._lifecycle = lifecycle
        self._request_id = request_id
        self._response_id = response_id
        self._start_message = start_message
        self._entered = False
        self._terminal = False

    async def __aenter__(self):
        if self._entered:
            raise ResponseStreamStateError("response stream cannot be entered twice")
        await self._lifecycle.claim(
            self, self._request_id, self._response_id, self._start_message
        )
        self._entered = True
        return self

    async def send_chunk(self, text, *, timestamp=None, metadata=None):
        self._require_open("send chunk")
        if timestamp is None:
            timestamp = time.time_ns() // 1_000_000
        await self._lifecycle.stream_chunk(self, text, timestamp, metadata)

    async def done(self, metadata=None):
        self._require_open("finish")
        await self._lifecycle.stream_done(self, metadata)
        self._terminal = True
```

Generate one UUID in `AvatarAgent.response_stream`. Build the optional start
message there only when `send_start=True`; otherwise pass `None`. Export the
two public types from `liveavatar_channel_sdk/__init__.py`.

- [ ] **Step 4: Verify the normal stream API**

Run: `pytest tests/test_response_stream.py -k "exported or auto_dones or send_start or timestamp" -v`

Expected: PASS after adding tests for optional start config and a monkeypatched default epoch-millisecond timestamp.

- [ ] **Step 5: Write failing terminal, exception, ownership, and concurrency tests**

Cover all of these exact outcomes:

- explicit `done()` followed by context exit sends done once;
- `cancel()` followed by context exit sends cancel once and no done;
- an exception in the context sends cancel and the same exception escapes;
- cancel-send failure preserves the original exception and records/logs the secondary failure;
- send after done/cancel, re-entry, and use before entry raise;
- a second stream and a legacy call cannot claim/mutate an active stream for
  the same request;
- a stream cannot mutate legacy-owned state for the same request;
- two tasks released from an `asyncio.Event` to send first legacy chunks for
  the same request produce exactly one active response and one
  `ResponseStreamStateError`;
- two simultaneous `ResponseStream.__aenter__` calls for the same request
  produce one winner and one error;
- legacy responses and `ResponseStream` contexts for different request IDs can
  both remain active and complete independently.

Use `asyncio.gather(..., return_exceptions=True)` and assert one result is successful and one is `ResponseStreamStateError`; do not rely on task scheduling order.

- [ ] **Step 6: Run the safety tests and verify they fail**

Run: `pytest tests/test_response_stream.py -k "explicit_done or cancel or exception or owner or concurrent or reenter" -v`

Expected: FAIL until cancellation, ownership, and terminal-state handling are complete.

- [ ] **Step 7: Implement cancellation and exception-safe context exit**

Implement `stream_cancel(owner)` and `ResponseStream.cancel()`. Context exit must follow:

```python
async def __aexit__(self, exc_type, exc, traceback):
    if self._terminal:
        return False
    if exc is None:
        await self.done()
        return False
    try:
        await self.cancel()
    except BaseException as cancel_error:
        message = f"failed to cancel response stream: {cancel_error}"
        if hasattr(exc, "add_note"):
            exc.add_note(message)
        else:
            logger.warning(message)
    return False
```

Owner validation compares with `is`, not equality. Every state transition and
send remains under the lifecycle lock. Mark terminal only after a successful
terminal send; exceptional exit that cannot cancel keeps coordinator state so
the application can explicitly recover.

- [ ] **Step 8: Verify the complete public API and regressions**

Run: `pytest tests/test_response_stream.py tests/test_avatar_agent.py -v`

Expected: PASS.

Run: `ruff check liveavatar_channel_sdk tests`

Expected: PASS.

- [ ] **Step 9: Commit `ResponseStream`**

```bash
git add liveavatar_channel_sdk/response_stream.py liveavatar_channel_sdk/avatar_agent.py liveavatar_channel_sdk/__init__.py tests/test_response_stream.py
git commit -m "feat: add safe response stream API"
```

---

### Task 3: Request-keyed Simulator Example

**Files:**
- Modify: `liveavatar_channel_sdk/example/live_avatar_service_simulator.py:42-89`
- Test: `tests/test_response_stream.py`

**Interfaces:**
- Consumes: `AvatarAgent.response_stream` from Task 2.
- Produces: an example listener that never starts a second echo task for the
  same request while allowing different request IDs to run concurrently.

- [ ] **Step 1: Add a failing simulator-policy test**

Import `EchoAgent`, inject a fake agent whose `response_stream` records calls,
and invoke `on_text_input` twice with the same request before releasing the
first echo. Assert the duplicate does not create another stream/task. Then
invoke a different request ID and assert it does create an independent task.
Structure the fake AI/echo delay with events rather than real sleeps so the
test is deterministic.

Run: `pytest tests/test_response_stream.py -k simulator -v`

Expected: FAIL because the current listener unconditionally calls `ensure_future`.

- [ ] **Step 2: Replace unconditional task creation with one tracked task**

Change the listener fields and callback policy to:

```python
self._response_tasks: dict[str, asyncio.Task] = {}

async def on_text_input(self, text: str, request_id: str) -> None:
    task = self._response_tasks.get(request_id)
    if task is not None and not task.done():
        logger.warning("Ignoring duplicate active request: request_id=%s", request_id)
        return
    task = asyncio.create_task(self._echo(request_id, text))
    self._response_tasks[request_id] = task
    task.add_done_callback(
        lambda completed, rid=request_id: self._response_tasks.pop(rid, None)
    )
```

Rewrite `_echo` to use:

```python
async with self.agent.response_stream(request_id, send_start=True) as response:
    for word in words:
        await response.send_chunk(word + " ")
        await asyncio.sleep(0.05)
```

Remove direct UUID, seq, timestamp, start, chunk, and done management and their
now-unused imports. Preserve useful logging with `response.response_id`.

- [ ] **Step 3: Verify simulator and SDK tests**

Run: `pytest tests/test_response_stream.py -k simulator -v`

Expected: PASS.

Run: `python -m liveavatar_channel_sdk.example.live_avatar_service_simulator --help`

Expected: module imports successfully; if it proceeds to connection because no
CLI parser exists, interrupt after confirming there is no import/type error and
do not treat the expected unavailable local service as an SDK failure.

- [ ] **Step 4: Commit the simulator migration**

```bash
git add liveavatar_channel_sdk/example/live_avatar_service_simulator.py tests/test_response_stream.py
git commit -m "docs: migrate simulator to response stream"
```

---

### Task 4: Protocol and README Migration Guidance

**Files:**
- Modify: `pyproject.toml:7`
- Modify: `README.md:45-62,145-185,360-380`
- Modify: `README.zh.md:45-62,145-182,350-372`
- Modify: `PROTOCOL.md:290-330,365-390`
- Modify: `PROTOCOL.zh.md:289-325,356-386`
- Test: `tests/test_response_stream.py`

**Interfaces:**
- Consumes: final public API from Task 2.
- Produces: normative lifecycle documentation and copyable safe examples.
- Produces: SDK version `0.3.0` consistently declared in package metadata and both READMEs.

- [ ] **Step 1: Add documentation contract tests**

Add a small test reading the four repository files and asserting both protocol
documents contain the stable-ID and terminal-event rules, and both READMEs
contain `async with` plus `response_stream` while their primary examples do
not contain a hard-coded `"resp-1"`.

Run: `pytest tests/test_response_stream.py -k documentation -v`

Expected: FAIL against the current documentation.

Also assert `pyproject.toml`, `README.md`, and `README.zh.md` declare version
`0.3.0` and no longer declare `0.2.7`.

- [ ] **Step 2: Make `ResponseStream` the primary README example**

Use this English example and its faithful Chinese translation:

```python
class MyAgent(AgentListener):
    async def on_text_input(self, text: str, request_id: str) -> None:
        async with self.agent.response_stream(request_id) as response:
            async for token in my_ai.stream(text):
                await response.send_chunk(token)
```

Add a legacy migration section showing exactly one `uuid.uuid4()` before the
first chunk and reuse through done. Mark `send_response_start`,
`send_response_chunk`, `send_response_done`, and `send_response_cancel` as
deprecated without claiming their signatures were removed. Explain mismatched
response-ID override warnings and wrong-request errors.

- [ ] **Step 3: Add normative protocol lifecycle language**

Immediately before each chunk section, state:

- all chunks in one complete response MUST use the same `requestId` and `responseId`;
- the final chunk MUST be followed by done with the same identifiers, unless the response is explicitly cancelled;
- a new response for the same request ID MUST NOT begin while that request
  already has an active response; distinct request IDs may be processed
  concurrently according to application policy;
- `control.interrupt` is only for a real business-driven interruption and does not replace done/cancel;
- `requestId -> responseId = 1:N` means sequential complete responses, not one response ID per chunk;
- inbound request IDs are propagated unchanged and must not be generated from wall-clock time.

Keep English and Chinese documents semantically aligned.

- [ ] **Step 4: Verify documentation contracts and formatting**

Run: `pytest tests/test_response_stream.py -k documentation -v`

Expected: PASS.

Run: `git diff --check`

Expected: no output and exit code 0.

Verify `python -m build` metadata reports `0.3.0` if the `build` module is
already installed; do not add a runtime dependency solely for this check.

- [ ] **Step 5: Commit documentation**

```bash
git add pyproject.toml README.md README.zh.md PROTOCOL.md PROTOCOL.zh.md tests/test_response_stream.py
git commit -m "docs: release response stream lifecycle in 0.3.0"
```

---

### Task 5: Full Verification and Public API Audit

**Files:**
- Modify only files already in scope if verification exposes a defect.

**Interfaces:**
- Consumes: all deliverables from Tasks 1-4.
- Produces: a verified Python 3.9-compatible release candidate for the lifecycle change.

- [ ] **Step 1: Run formatting checks without rewriting unrelated files**

Run: `black --check liveavatar_channel_sdk/response_stream.py liveavatar_channel_sdk/avatar_agent.py liveavatar_channel_sdk/__init__.py liveavatar_channel_sdk/example/live_avatar_service_simulator.py tests/test_response_stream.py tests/test_avatar_agent.py`

Expected: PASS. If formatting fails, run `black` only on the listed changed
Python files, inspect the diff, and rerun the check.

- [ ] **Step 2: Run linting**

Run: `ruff check liveavatar_channel_sdk tests`

Expected: PASS.

- [ ] **Step 3: Run the full test suite**

Run: `pytest -v`

Expected: PASS with no unhandled task warnings and no unexpected `DeprecationWarning` from correct calls.

- [ ] **Step 4: Check Python 3.9 syntax compatibility**

Run: `python3.9 -m compileall -q liveavatar_channel_sdk tests`

Expected: PASS when `python3.9` is installed. If it is unavailable, record that
fact and rely on the project classifier plus CI's Python 3.9 job; do not change
the project minimum.

- [ ] **Step 5: Audit the final diff against the spec**

Run: `git diff HEAD~4 --stat` and `git diff HEAD~4 --check` (adjust the base to
the pre-implementation commit if intermediate commit count differs).

Verify manually that:

- old method signatures are byte-for-byte compatible at the definition level;
- `ResponseStream` and `ResponseStreamStateError` are package-root exports;
- no developer-TTS audio methods were pulled into the text lifecycle;
- errors never include response text or metadata;
- every coordinator cleanup occurs only after a successful terminal send;
- documentation and simulator use `ResponseStream` as the primary pattern.
- package metadata and both READMEs consistently report SDK version `0.3.0`.

- [ ] **Step 6: Commit any verification-only corrections**

If verification required scoped corrections:

```bash
git add <only-the-corrected-in-scope-files>
git commit -m "fix: address response stream verification findings"
```

If no corrections were required, do not create an empty commit.
