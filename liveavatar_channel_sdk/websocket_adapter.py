"""
WebSocketAdapter -- wraps a server-side ``fastapi.WebSocket`` (or compatible)
to expose the :class:`MessageSender` interface.

In Outbound mode the developer runs a WebSocket **server**.  The platform
connects to it as a client.  ``WebSocketAdapter`` lets the developer's
message loop use the same ``send_*()`` helpers as the client-side
:class:`AvatarWebSocketClient`.
"""

from __future__ import annotations

import json

from fastapi import WebSocket

from liveavatar_channel_sdk.message_sender import MessageSender


class WebSocketAdapter(MessageSender):
    """Adapt a server-side ``fastapi.WebSocket`` to the ``MessageSender`` API.

    Usage in an Outbound-mode handler::

        ws: WebSocket = ...
        adapter = WebSocketAdapter(ws)
        listener = MyListener()

        async for raw in ws.iter_text():
            await dispatch_text_event(raw, listener)
    """

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws

    async def send_json(self, message: dict) -> None:
        await self._ws.send_text(json.dumps(message))

    async def send_binary(self, data: bytes) -> None:
        await self._ws.send_bytes(data)
