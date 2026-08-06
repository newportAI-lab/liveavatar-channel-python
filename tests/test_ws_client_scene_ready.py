from __future__ import annotations

import asyncio

import pytest

from liveavatar_channel_sdk._ws_client import _AvatarWsClient
from liveavatar_channel_sdk.message_builder import MessageBuilder


class FakeCallbacks:
    def __init__(self) -> None:
        self.scene_ready_count = 0
        self.resource_transition_data = None

    async def on_scene_ready(self) -> None:
        self.scene_ready_count += 1

    async def on_resource_transition(self, data) -> None:
        self.resource_transition_data = data


@pytest.mark.asyncio
async def test_ws_client_routes_scene_ready_to_callbacks():
    callbacks = FakeCallbacks()
    client = _AvatarWsClient(
        "ws://example.invalid",
        callbacks,
        asyncio.Event(),
    )

    await client._handle_text('{"event":"scene.ready"}')

    assert callbacks.scene_ready_count == 1


def test_scene_ready_builder_has_no_payload():
    assert MessageBuilder.scene_ready() == {"event": "scene.ready"}


@pytest.mark.asyncio
async def test_ws_client_routes_resource_transition_to_callbacks():
    callbacks = FakeCallbacks()
    client = _AvatarWsClient(
        "ws://example.invalid",
        callbacks,
        asyncio.Event(),
    )

    await client._handle_text(
        '{"event":"scene.resourceTransition","data":'
        '{"previousResourceId":"video-a","nextResourceId":"video-b",'
        '"message":"switch from video-a to video-b"}}'
    )

    assert callbacks.resource_transition_data.previous_resource_id == "video-a"
    assert callbacks.resource_transition_data.next_resource_id == "video-b"
    assert callbacks.resource_transition_data.message == "switch from video-a to video-b"


@pytest.mark.asyncio
async def test_ws_client_does_not_route_malformed_resource_transition():
    callbacks = FakeCallbacks()
    client = _AvatarWsClient(
        "ws://example.invalid",
        callbacks,
        asyncio.Event(),
    )

    await client._handle_text(
        '{"event":"scene.resourceTransition","data":{"nextResourceId":"video-b"}}'
    )

    assert callbacks.resource_transition_data is None


@pytest.mark.asyncio
async def test_ws_client_does_not_route_blank_resource_transition_ids():
    callbacks = FakeCallbacks()
    client = _AvatarWsClient(
        "ws://example.invalid",
        callbacks,
        asyncio.Event(),
    )

    await client._handle_text(
        '{"event":"scene.resourceTransition","data":'
        '{"previousResourceId":"   ","nextResourceId":"video-b"}}'
    )

    assert callbacks.resource_transition_data is None
