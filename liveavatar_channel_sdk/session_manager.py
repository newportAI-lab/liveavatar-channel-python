"""
Server-side async-safe session registry.

Tracks active WebSocket sessions keyed by session_id.
Cancels any registered asyncio Tasks when a session is removed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Async-safe registry for active avatar sessions.

    Thread-safety note: operations acquire an asyncio.Lock so they are safe
    to call from multiple coroutines within a single event loop.  Do *not*
    call from a different thread without wrapping in run_coroutine_threadsafe.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # session_id -> arbitrary session data (e.g. the WebSocket object)
        self._sessions: Dict[str, Any] = {}
        # session_id -> list of asyncio Tasks to cancel on removal
        self._tasks: Dict[str, List[asyncio.Task]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def add_session(self, session_id: str, session_data: Any) -> None:
        """Register a new session.

        Args:
            session_id: Unique session identifier (from session.init).
            session_data: Arbitrary data to associate with the session
                          (e.g. the WebSocket connection object).
        """
        async with self._lock:
            self._sessions[session_id] = session_data
            self._tasks[session_id] = []
            logger.debug("Session added: %s", session_id)

    async def get_session(self, session_id: str) -> Optional[Any]:
        """Return the session data for *session_id*, or None if not found."""
        async with self._lock:
            return self._sessions.get(session_id)

    async def register_task(self, session_id: str, task: asyncio.Task) -> None:
        """Associate an asyncio Task with a session so it is cancelled on removal."""
        async with self._lock:
            if session_id in self._tasks:
                self._tasks[session_id].append(task)

    async def remove_session(self, session_id: str) -> None:
        """Remove a session and cancel all associated tasks.

        Safe to call even if the session_id is not present.
        """
        async with self._lock:
            self._sessions.pop(session_id, None)
            tasks = self._tasks.pop(session_id, [])

        for task in tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        logger.debug("Session removed: %s (cancelled %d tasks)", session_id, len(tasks))

    async def all_session_ids(self) -> List[str]:
        """Return a snapshot of all active session IDs."""
        async with self._lock:
            return list(self._sessions.keys())

    async def session_count(self) -> int:
        """Return the number of active sessions."""
        async with self._lock:
            return len(self._sessions)
