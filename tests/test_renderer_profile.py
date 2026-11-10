"""Session model HTTP contract; no platform or renderer access."""
import json
import httpx
import pytest
from liveavatar_channel_sdk.avatar_agent import AvatarAgent, AvatarAgentConfig, AgentListener

@pytest.mark.asyncio
@pytest.mark.parametrize("profile", [None, "normal", "pet", "4k"])
async def test_model_body(profile):
    captured = []
    def handle(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "data": {
            "sessionId": "test", "sfuUrl": "wss://invalid", "userToken": "test"}})
    agent = AvatarAgent(AvatarAgentConfig(api_key="test", avatar_id="avatar", renderer_profile=profile), AgentListener())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="https://invalid") as client:
        agent._http_client = client
        await agent._rest_start()
    assert ("rendererProfile" in captured[0]) == (profile is not None)
    if profile is not None:
        assert captured[0]["rendererProfile"] == profile

@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["", "PET", "pet ", "baby", 1, True, {}, []])
async def test_invalid_model_never_sends(profile):
    agent = AvatarAgent(AvatarAgentConfig(api_key="test", avatar_id="avatar", renderer_profile=profile), AgentListener())
    def fail(request):
        raise AssertionError("invalid model must not send HTTP")
    async with httpx.AsyncClient(transport=httpx.MockTransport(fail), base_url="https://invalid") as client:
        agent._http_client = client
        with pytest.raises(ValueError):
            await agent._rest_start()
