# Response Lifecycle and Streaming System Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the WebSocket Agent Python SDK to expose response lifecycle events, track first terminal results, stream `system.prompt`, and release the additions as version `0.4.0`.

**Architecture:** Add raw-string lifecycle models and an inbound coordinator keyed by `(session_id, response_id)`, while retaining the existing outbound response coordinator. Route WebSocket lifecycle messages through the coordinator and listener, then reuse the coordinator's pending handles from both prompt and response streams.

**Tech Stack:** Python 3.9+, asyncio, dataclasses, websockets, pytest, pytest-asyncio, ruff, black

**Spec:** `docs/superpowers/specs/2026-09-10-response-lifecycle-prompt-stream-design.md`

## Global Constraints

- Keep `AvatarAgent.send_prompt(text, metadata=None)` and legacy `system.prompt` wire behavior unchanged.
- Preserve unknown lifecycle `state` and `reason` values as strings.
- Deduplicate lifecycle events by `sessionId + seq`; accept sequence gaps.
- Never infer response completion from session state, done messages, audio finish, disconnect, or cancellation.
- Register response identity before sending a start event.
- Upgrade package and README version references from `0.3.0` to `0.4.0`.
- Do not add runtime dependencies or RTC transport code.

---

### Task 1: Protocol Models and Wire Builders

**Files:**
- Create: `liveavatar_channel_sdk/response_state.py`
- Modify: `liveavatar_channel_sdk/event_type.py`
- Modify: `liveavatar_channel_sdk/message_builder.py`
- Modify: `liveavatar_channel_sdk/__init__.py`
- Test: `tests/test_response_state.py`
- Test: `tests/test_message_builder.py`

**Interfaces:**
- Produces: `ResponseStateEvent(session_id, request_id, response_id, seq, timestamp, state, reason)`.
- Produces: `MessageBuilder.system_prompt_start(request_id, response_id)`, `system_prompt_chunk(request_id, response_id, seq, timestamp, text)`, and `system_prompt_done(request_id, response_id)`.
- Produces: event constants `RESPONSE_STATE`, `SYSTEM_PROMPT_START`, `SYSTEM_PROMPT_CHUNK`, and `SYSTEM_PROMPT_DONE`.

- [ ] **Step 1: Write failing model and builder tests**

Add tests that instantiate `ResponseStateEvent` with an unknown state/reason and assert the strings are preserved. Add literal wire-shape assertions for all three prompt messages, including `seq == 1`. Add parameterized invalid-input tests for blank IDs and chunk sequence values `0` and `-1`. Add a package-root import assertion.

- [ ] **Step 2: Verify the focused tests fail for missing symbols**

Run: `pytest tests/test_response_state.py tests/test_message_builder.py -q`

Expected: FAIL because the lifecycle model, exports, constants, and builders do not exist.

- [ ] **Step 3: Implement the minimal protocol surface**

Create a frozen dataclass whose fields exactly match the public interface. Add constants and builders producing:

```python
{"event": EventType.SYSTEM_PROMPT_START, "requestId": request_id, "responseId": response_id}
{"event": EventType.SYSTEM_PROMPT_CHUNK, "requestId": request_id, "responseId": response_id,
 "seq": seq, "timestamp": timestamp, "data": {"text": text}}
{"event": EventType.SYSTEM_PROMPT_DONE, "requestId": request_id, "responseId": response_id}
```

Use a private `_require_non_blank_id(name, value)` helper in `message_builder.py`; raise `ValueError` locally. Require `seq` to be an integer excluding booleans and at least 1.

- [ ] **Step 4: Verify Task 1 passes**

Run: `pytest tests/test_response_state.py tests/test_message_builder.py -q`

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add liveavatar_channel_sdk/response_state.py liveavatar_channel_sdk/event_type.py liveavatar_channel_sdk/message_builder.py liveavatar_channel_sdk/__init__.py tests/test_response_state.py tests/test_message_builder.py
git commit -m "feat: add response lifecycle protocol models"
```

### Task 2: Inbound Lifecycle Coordinator and WebSocket Routing

**Files:**
- Create: `liveavatar_channel_sdk/response_lifecycle.py`
- Modify: `liveavatar_channel_sdk/_ws_client.py`
- Modify: `liveavatar_channel_sdk/avatar_agent.py`
- Test: `tests/test_response_lifecycle.py`
- Test: `tests/test_ws_client.py`

**Interfaces:**
- Consumes: `ResponseStateEvent` from Task 1.
- Produces: private `_ResponseLifecycleCoordinator.register(session_id, request_id, response_id) -> _PendingResponse`, `rollback(pending, exc)`, `handle(event) -> bool`, and `reset()`.
- Produces: `_PendingResponse.wait_finished() -> ResponseStateEvent`.
- Produces: `AgentListener.on_response_state(event)` and matching `_AgentCallbacks` bridge method.

- [ ] **Step 1: Write failing coordinator tests**

Cover literal events for: matching terminal completion; `ACCEPTED` not completing; duplicate and lower `seq` ignored; a sequence gap accepted; first terminal retained; request mismatch not completing; unknown local response reported as accepted for callback delivery; and reset cancelling outstanding waiters. Verify future completion happens after the coordinator lock is released by awaiting a callback that re-enters coordinator state.

- [ ] **Step 2: Verify coordinator tests fail**

Run: `pytest tests/test_response_lifecycle.py -q`

Expected: FAIL because `response_lifecycle.py` does not exist.

- [ ] **Step 3: Implement coordinator state transitions**

Use one `asyncio.Lock`, a `dict[str, int]` sequence watermark, and a pending map keyed by `tuple[str, str]`. Under lock, decide deduplication and state updates; use `loop.call_soon` or perform `Future.set_result/set_exception/cancel` after leaving the lock. Return `False` only for stale/duplicate events so the bridge can suppress duplicate callbacks but publish all unique events.

- [ ] **Step 4: Write failing WebSocket routing tests**

Send `_handle_text()` exact JSON for known and unknown state/reason values. Assert all fields reach a recording callback unchanged. Send malformed lifecycle JSON and assert subsequent valid input is still handled. Send duplicate `sessionId + seq` and assert a single callback.

- [ ] **Step 5: Verify routing tests fail**

Run: `pytest tests/test_ws_client.py -q`

Expected: FAIL because `response.state` is unhandled.

- [ ] **Step 6: Wire parser, coordinator, and listener bridge**

Construct `ResponseStateEvent` using required top-level fields and `data["state"]`, with optional `data.get("reason")`. Give `_AvatarWsClient` an `on_response_state` callback route. In `AvatarAgent`, send events through the coordinator first and invoke `_ListenerBridge.on_response_state` outside coordinator locking only when `handle()` returns true. Reset coordinator state on stop and before accepting a new session.

- [ ] **Step 7: Verify Task 2 and existing agent tests pass**

Run: `pytest tests/test_response_lifecycle.py tests/test_ws_client.py tests/test_avatar_agent.py -q`

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```bash
git add liveavatar_channel_sdk/response_lifecycle.py liveavatar_channel_sdk/_ws_client.py liveavatar_channel_sdk/avatar_agent.py tests/test_response_lifecycle.py tests/test_ws_client.py
git commit -m "feat: receive and track response lifecycle events"
```

### Task 3: Streaming System Prompt API

**Files:**
- Create: `liveavatar_channel_sdk/prompt_stream.py`
- Modify: `liveavatar_channel_sdk/avatar_agent.py`
- Modify: `liveavatar_channel_sdk/__init__.py`
- Test: `tests/test_prompt_stream.py`

**Interfaces:**
- Consumes: prompt builders from Task 1 and coordinator registration from Task 2.
- Produces: `AvatarAgent.prompt_stream(request_id, *, response_id=None) -> PromptStream`.
- Produces: `PromptStream.send(text, *, timestamp=None)`, `done()`, and `wait_finished()`.
- Produces: `PromptStreamStateError(RuntimeError)`.

- [ ] **Step 1: Write failing happy-path tests**

Create a connected fake agent, enter a prompt stream, issue two sends without any `ACCEPTED`, exit, and assert exact event order `start/chunk/chunk/done`, stable IDs, sequences `1, 2`, and supplied timestamps. Assert generated response IDs are non-empty and explicit IDs are preserved.

- [ ] **Step 2: Verify happy-path tests fail**

Run: `pytest tests/test_prompt_stream.py -q`

Expected: FAIL because `PromptStream` and `AvatarAgent.prompt_stream()` do not exist.

- [ ] **Step 3: Implement stream registration and sends**

Use a per-stream `asyncio.Lock`. `__aenter__` calls coordinator registration before sending start and rolls registration back if the send fails. `send()` allocates and transmits the next sequence while holding the lock, incrementing only after success. `__aexit__` sends done only on success; on exceptions it closes local sending without emitting done or a synthetic terminal.

- [ ] **Step 4: Write failing concurrency and state tests**

Test concurrent sends for unique sequences, duplicate done, send after done, use before enter, re-entry, concurrent done, start-send rollback, and blank IDs. Test that `done()` leaves `wait_finished()` pending, a matching terminal resolves it, a mismatched request does not, and cancelling the waiter does not change stored lifecycle state.

- [ ] **Step 5: Verify the new tests fail for the intended missing behavior**

Run: `pytest tests/test_prompt_stream.py -q`

Expected: FAIL on the unimplemented state/concurrency behavior.

- [ ] **Step 6: Implement deterministic terminal and wait behavior**

Guard entered/closed flags under the stream lock, share the coordinator's pending future, and use `asyncio.shield()` in `wait_finished()` so caller cancellation does not cancel shared lifecycle state. Export both public types from package root.

- [ ] **Step 7: Verify Task 3 passes**

Run: `pytest tests/test_prompt_stream.py -q`

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add liveavatar_channel_sdk/prompt_stream.py liveavatar_channel_sdk/avatar_agent.py liveavatar_channel_sdk/__init__.py tests/test_prompt_stream.py
git commit -m "feat: add streaming system prompt API"
```

### Task 4: Existing Response Stream Lifecycle Integration

**Files:**
- Modify: `liveavatar_channel_sdk/response_stream.py`
- Modify: `liveavatar_channel_sdk/avatar_agent.py`
- Test: `tests/test_response_stream.py`

**Interfaces:**
- Consumes: coordinator from Task 2.
- Produces: `ResponseStream.wait_finished() -> ResponseStateEvent`.
- Changes: `AvatarAgent.response_stream(..., send_start=True)` defaults to explicit start; `send_start=False` remains an explicit compatibility override.

- [ ] **Step 1: Write failing response integration tests**

Assert the default response stream sends `response.start` before its first chunk and is registered before that send. Assert `wait_finished()` remains pending after `response.done`, resolves only for a matching first terminal, and is shielded from waiter cancellation. Assert explicit `send_start=False` retains the previous no-start wire flow.

- [ ] **Step 2: Verify integration tests fail**

Run: `pytest tests/test_response_stream.py -q`

Expected: FAIL because the default is still false and no lifecycle waiter exists.

- [ ] **Step 3: Add inbound lifecycle registration to ResponseStream**

Pass the coordinator and session-ID provider into each stream. Register before the outbound lifecycle `claim()` sends start, roll back both registrations on failure, and expose the shielded pending waiter. Register `send_response_start()` before sending and roll it back on failure; lifecycle observation for low-level methods stays callback-only.

- [ ] **Step 4: Verify response-stream regression suite**

Run: `pytest tests/test_response_stream.py tests/test_avatar_agent.py -q`

Expected: PASS, including legacy method behavior.

- [ ] **Step 5: Commit Task 4**

```bash
git add liveavatar_channel_sdk/response_stream.py liveavatar_channel_sdk/avatar_agent.py tests/test_response_stream.py tests/test_avatar_agent.py
git commit -m "feat: correlate response streams with platform lifecycle"
```

### Task 5: Version, Migration Documentation, and Full Verification

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `README.zh.md`
- Modify: `PROTOCOL.md`
- Modify: `PROTOCOL.zh.md`
- Modify: `liveavatar_channel_sdk/example/live_avatar_service_simulator.py`
- Test: `tests/test_response_stream.py`

**Interfaces:**
- Documents: lifecycle completion requires matching `responseId`, `FINISHED`, and `COMPLETED`.
- Documents: prompt `done`, response `done`, audio finish, and session `IDLE` are not completion.
- Releases: package version `0.4.0`.

- [ ] **Step 1: Update version expectation tests first**

Change existing version assertions to require `0.4.0` in `pyproject.toml`, `README.md`, and `README.zh.md`, then run the focused test and confirm failure while metadata remains `0.3.0`.

Run: `pytest tests/test_response_stream.py -q`

Expected: FAIL with missing `0.4.0` references.

- [ ] **Step 2: Update package metadata and developer documentation**

Set `project.version = "0.4.0"`. Add English and Chinese examples for `on_response_state`, `prompt_stream`, and `wait_finished`. State the minimum compatible dispatcher requirement without inventing a numeric server version: the endpoint must support `system.prompt.start/chunk/done` and `response.state`. Update protocol event tables and migration guidance. Update the simulator only where needed to demonstrate checking `FINISHED/COMPLETED`; do not add course business logic.

- [ ] **Step 3: Verify version and documentation tests pass**

Run: `pytest tests/test_response_stream.py -q`

Expected: PASS.

- [ ] **Step 4: Run the complete verification matrix**

Run:

```bash
pytest -q
ruff check .
black --check .
git diff --check
```

Expected: all commands exit 0 with no warnings introduced by this change.

- [ ] **Step 5: Commit release documentation**

```bash
git add pyproject.toml README.md README.zh.md PROTOCOL.md PROTOCOL.zh.md liveavatar_channel_sdk/example/live_avatar_service_simulator.py tests/test_response_stream.py
git commit -m "docs: release response lifecycle support in 0.4.0"
```

### Task 6: Final Requirement Audit

**Files:**
- Review only: all files changed by Tasks 1-5

**Interfaces:**
- Consumes: the complete implementation and handoff acceptance criteria.
- Produces: verification evidence; no speculative API additions.

- [ ] **Step 1: Inspect the complete branch diff**

Run: `git diff HEAD~5 --stat && git diff HEAD~5 --check`

Expected: only protocol, lifecycle, stream, test, documentation, example, and version files are changed.

- [ ] **Step 2: Map WebSocket Python acceptance criteria to tests**

Confirm explicit tests cover parsing, unknown values, deduplication, first-terminal-wins, pre-start registration, no ACCEPTED wait, concurrent prompt sequencing, done versus completion, delayed IDLE isolation, legacy prompt compatibility, and unknown local responses.

- [ ] **Step 3: Re-run full tests and static checks**

Run: `pytest -q && ruff check . && black --check . && git status --short`

Expected: tests and checks pass; status shows only intentionally uncommitted plan tracking changes, if any.

