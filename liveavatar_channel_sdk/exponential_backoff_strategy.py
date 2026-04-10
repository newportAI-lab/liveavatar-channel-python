"""Exponential backoff strategy for auto-reconnect."""

from __future__ import annotations
import asyncio


class ExponentialBackoffStrategy:
    """
    Calculates exponentially increasing delay between reconnect attempts.

    Starts at `base_delay` seconds and doubles each attempt up to `max_delay`.
    Call `reset()` after a successful connection to restart from base_delay.
    """

    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0) -> None:
        self._base = base_delay
        self._max = max_delay
        self._attempt = 0

    def reset(self) -> None:
        """Reset attempt counter after a successful connection."""
        self._attempt = 0

    @property
    def next_delay(self) -> float:
        """Return delay for the current attempt without incrementing."""
        return min(self._base * (2 ** self._attempt), self._max)

    async def wait(self) -> None:
        """Sleep for the current backoff delay, then increment attempt counter."""
        delay = self.next_delay
        self._attempt += 1
        await asyncio.sleep(delay)
