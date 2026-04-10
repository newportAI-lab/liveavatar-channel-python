import pytest
import asyncio
from liveavatar_channel_sdk.streaming_response_handler import StreamingResponseHandler

@pytest.mark.asyncio
async def test_in_order_delivery():
    """Chunks arriving in order are delivered immediately."""
    received = []
    done_called = []

    async def on_chunk(req_id, resp_id, seq, text):
        received.append((seq, text))

    async def on_done(req_id, resp_id):
        done_called.append(resp_id)

    handler = StreamingResponseHandler(on_chunk, on_done)
    await handler.handle_chunk("req-1", "resp-1", 0, "Hello")
    await handler.handle_chunk("req-1", "resp-1", 1, " world")
    await handler.handle_chunk("req-1", "resp-1", 2, "!")
    assert received == [(0, "Hello"), (1, " world"), (2, "!")]

    await handler.handle_done("req-1", "resp-1")
    assert done_called == ["resp-1"]


@pytest.mark.asyncio
async def test_out_of_order_delivery():
    """Chunks arriving out of order are buffered until gap is filled."""
    received = []

    async def on_chunk(req_id, resp_id, seq, text):
        received.append((seq, text))

    async def on_done(req_id, resp_id):
        pass

    handler = StreamingResponseHandler(on_chunk, on_done)
    # Deliver seq 2 and 1 before seq 0
    await handler.handle_chunk("req-1", "resp-1", 2, "C")
    assert received == []  # blocked waiting for seq 0

    await handler.handle_chunk("req-1", "resp-1", 1, "B")
    assert received == []  # still blocked

    await handler.handle_chunk("req-1", "resp-1", 0, "A")
    # Now all three should be delivered in order
    assert received == [(0, "A"), (1, "B"), (2, "C")]


@pytest.mark.asyncio
async def test_gap_filling():
    """Partial delivery when some chunks arrive, then gap is filled."""
    received = []

    async def on_chunk(req_id, resp_id, seq, text):
        received.append((seq, text))

    async def on_done(req_id, resp_id):
        pass

    handler = StreamingResponseHandler(on_chunk, on_done)
    await handler.handle_chunk("req-1", "resp-1", 0, "A")
    assert received == [(0, "A")]

    await handler.handle_chunk("req-1", "resp-1", 3, "D")  # gap at 1, 2
    assert received == [(0, "A")]  # only A delivered

    await handler.handle_chunk("req-1", "resp-1", 1, "B")
    assert received == [(0, "A"), (1, "B")]  # B delivered, still waiting for 2

    await handler.handle_chunk("req-1", "resp-1", 2, "C")
    assert received == [(0, "A"), (1, "B"), (2, "C"), (3, "D")]  # all delivered


@pytest.mark.asyncio
async def test_done_flushes_remaining():
    """handle_done flushes buffered chunks that haven't been delivered yet."""
    received = []
    done_called = []

    async def on_chunk(req_id, resp_id, seq, text):
        received.append((seq, text))

    async def on_done(req_id, resp_id):
        done_called.append(resp_id)

    handler = StreamingResponseHandler(on_chunk, on_done)
    # Deliver out of order, then done before seq 0 arrives
    await handler.handle_chunk("req-1", "resp-1", 1, "B")
    await handler.handle_chunk("req-1", "resp-1", 2, "C")
    assert received == []  # waiting for seq 0

    await handler.handle_done("req-1", "resp-1")
    # done should flush remaining in order
    assert received == [(1, "B"), (2, "C")]
    assert done_called == ["resp-1"]


@pytest.mark.asyncio
async def test_multiple_responses_independent():
    """Multiple response_ids are buffered independently."""
    received = {"resp-1": [], "resp-2": []}

    async def on_chunk(req_id, resp_id, seq, text):
        received[resp_id].append((seq, text))

    async def on_done(req_id, resp_id):
        pass

    handler = StreamingResponseHandler(on_chunk, on_done)
    await handler.handle_chunk("req-1", "resp-1", 0, "A1")
    await handler.handle_chunk("req-2", "resp-2", 0, "A2")
    await handler.handle_chunk("req-1", "resp-1", 1, "B1")

    assert received["resp-1"] == [(0, "A1"), (1, "B1")]
    assert received["resp-2"] == [(0, "A2")]
