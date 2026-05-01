from __future__ import annotations
from typing import Callable, Awaitable, Optional
from sortedcontainers import SortedDict


class StreamingResponseHandler:
    """
    Buffers response.chunk messages by response_id and delivers them
    in seq order via on_chunk_received callback.
    """

    def __init__(
        self,
        on_chunk_received: Callable[[str, str, int, str], Awaitable[None]],
        on_response_done: Callable[[str, str], Awaitable[None]],
    ):
        self._on_chunk = on_chunk_received
        self._on_done = on_response_done
        # response_id -> SortedDict[seq -> text]
        self._buffers: dict[str, SortedDict] = {}
        # response_id -> next expected seq (initially 0)
        self._next_seq: dict[str, int] = {}

    async def handle_chunk(
        self, request_id: str, response_id: str, seq: int, text: str
    ) -> None:
        """
        Buffer a chunk and deliver all consecutive chunks from the head.
        """
        if response_id not in self._buffers:
            self._buffers[response_id] = SortedDict()
            self._next_seq[response_id] = 0

        buf = self._buffers[response_id]
        buf[seq] = (request_id, text)

        # Deliver all consecutive chunks from next_seq
        while self._next_seq[response_id] in buf:
            s = self._next_seq[response_id]
            rid, chunk_text = buf.pop(s)
            await self._on_chunk(request_id, response_id, s, chunk_text)
            self._next_seq[response_id] += 1

    async def handle_done(self, request_id: str, response_id: str) -> None:
        """
        Flush all remaining buffered chunks in order, then call on_response_done.
        """
        if response_id in self._buffers:
            buf = self._buffers[response_id]
            # Flush remaining in seq order
            for seq in list(buf.keys()):
                rid, chunk_text = buf[seq]
                await self._on_chunk(request_id, response_id, seq, chunk_text)
            del self._buffers[response_id]
            del self._next_seq[response_id]

        await self._on_done(request_id, response_id)

    def clear(self, response_id: Optional[str] = None) -> None:
        """Clear buffer for a specific response_id, or all if None."""
        if response_id is not None:
            self._buffers.pop(response_id, None)
            self._next_seq.pop(response_id, None)
        else:
            self._buffers.clear()
            self._next_seq.clear()
