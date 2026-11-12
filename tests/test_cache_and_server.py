"""Tests for the TTL cache, MCP registration surface, and CLI entrypoint."""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

import weather_mcp_africa.server as server_module
from weather_mcp_africa.cache import AsyncTTLCache
from weather_mcp_africa.models import LocationResult
from weather_mcp_africa.server import mcp


async def test_cache_get_set_and_miss():
    cache = AsyncTTLCache[int](maxsize=4, ttl=60, name="test")

    assert await cache.get("missing") is None
    await cache.set("answer", 42)
    assert await cache.get("answer") == 42

    await cache.clear()
    assert await cache.get("answer") is None


async def test_cache_get_or_set_only_calls_factory_once():
    cache = AsyncTTLCache[str](maxsize=4, ttl=60, name="test")
    calls = 0

    async def factory() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return "value"

    first, first_hit = await cache.get_or_set("key", factory)
    second, second_hit = await cache.get_or_set("key", factory)

    assert first == second == "value"
    assert first_hit is False
    assert second_hit is True
    assert calls == 1


async def test_cache_prevents_concurrent_stampede():
    cache = AsyncTTLCache[str](maxsize=4, ttl=60, name="test")
    calls = 0

    async def factory() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return "shared"

    results = await asyncio.gather(
        *(cache.get_or_set("same-key", factory) for _ in range(5))
    )

    assert [value for value, _ in results] == ["shared"] * 5
    assert calls == 1


def test_model_rejects_out_of_range_coordinates():
    with pytest.raises(ValidationError):
        LocationResult(name="Bad", latitude=91.0, longitude=0.0)
    with pytest.raises(ValidationError):
        LocationResult(name="Bad", latitude=0.0, longitude=181.0)


async def test_tool_resource_and_prompt_registration():
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    expected_tools = {
        "search_locations",
        "get_forecast",
        "get_city_weather",
        "get_air_quality",
        "get_marine_forecast",
        "get_historical_weather",
        "compare_cities_weather",
    }
    assert expected_tools <= set(tools)

    for name in expected_tools:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is True
        assert annotations.destructive_hint is False
        assert annotations.idempotent_hint is True
        assert annotations.open_world_hint is True

    assert "ctx" not in tools["get_forecast"].input_schema["properties"]

    resources = {str(resource.uri) for resource in await mcp.list_resources()}
    assert {"weather://africa/hubs", "weather://kenya/cities"} <= resources

    templates = {
        template.uri_template for template in await mcp.list_resource_templates()
    }
    assert {
        "weather://city/{city}",
        "weather://air-quality/{city}",
        "weather://marine/{city}",
    } <= templates

    prompts = {prompt.name: prompt for prompt in await mcp.list_prompts()}
    assert prompts["africa_weather_briefing"].title == "Africa Weather & Travel Briefing"
    assert (
        prompts["coastal_marine_safety_briefing"].title
        == "Coastal & Marine Safety Briefing"
    )


async def test_static_resource_and_prompt_render():
    contents = await mcp.read_resource("weather://africa/hubs")
    payload = json.loads(contents[0].content)
    assert "Nairobi, Kenya" in payload
    assert payload["Mombasa, Kenya"]["role"] == "Coastal hub"

    result = await mcp.get_prompt(
        "africa_weather_briefing",
        {"city": "Nairobi", "country_code": "ke"},
    )
    rendered = json.dumps(result.model_dump())
    assert "Nairobi" in rendered
    assert "get_air_quality" in rendered


def test_cli_stdio_transport(monkeypatch):
    calls: dict[str, object] = {}

    def fake_run(**kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(server_module.mcp, "run", fake_run)
    server_module.main(["--transport", "stdio"])

    assert calls == {"transport": "stdio"}


def test_cli_http_transport(monkeypatch):
    calls: dict[str, object] = {}

    def fake_run(**kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(server_module.mcp, "run", fake_run)
    server_module.main(["--transport", "http", "--host", "0.0.0.0", "--port", "9090"])

    assert calls == {
        "transport": "streamable-http",
        "host": "0.0.0.0",
        "port": 9090,
    }
