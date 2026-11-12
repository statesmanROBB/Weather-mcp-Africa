"""Tests for every MCP tool, with all Open-Meteo HTTP traffic mocked."""

from __future__ import annotations

import httpx2
import pytest
from conftest import (
    air_quality_payload,
    archive_payload,
    forecast_payload,
    geocoding_payload,
    make_context,
    marine_payload,
)
from mcp.server.mcpserver.exceptions import ToolError

from weather_mcp_africa.constants import (
    OPEN_METEO_AIR_QUALITY_URL,
    OPEN_METEO_ARCHIVE_URL,
    OPEN_METEO_FORECAST_URL,
    OPEN_METEO_GEOCODING_URL,
    OPEN_METEO_MARINE_URL,
)
from weather_mcp_africa.server import (
    compare_cities_weather,
    get_air_quality,
    get_city_weather,
    get_forecast,
    get_historical_weather,
    get_marine_forecast,
    search_locations,
)


async def test_search_locations(router, weather_client):
    route = router.get(OPEN_METEO_GEOCODING_URL).mock(
        return_value=httpx2.Response(200, json=geocoding_payload())
    )
    ctx = make_context(weather_client)

    result = await search_locations("Nairobi", ctx, count=3, country_code="KE")

    assert result.query == "Nairobi"
    assert result.count == 1
    assert result.results[0].name == "Nairobi"
    assert result.results[0].country_code == "KE"
    assert route.calls[0].request.url.params["country_code"] == "KE"


async def test_get_forecast(router, weather_client):
    router.get(OPEN_METEO_FORECAST_URL).mock(
        return_value=httpx2.Response(200, json=forecast_payload())
    )
    ctx = make_context(weather_client)

    result = await get_forecast(-1.2921, 36.8219, ctx, location_label="Nairobi")

    assert result.current.location_name == "Nairobi"
    assert result.current.temperature_c == 24.5
    assert result.current.condition == "Partly cloudy"
    assert len(result.daily_periods) == 5
    assert result.daily_periods[1].precipitation_prob_max == 80


async def test_get_city_weather(router, weather_client):
    router.get(OPEN_METEO_GEOCODING_URL).mock(
        return_value=httpx2.Response(200, json=geocoding_payload())
    )
    router.get(OPEN_METEO_FORECAST_URL).mock(
        return_value=httpx2.Response(200, json=forecast_payload())
    )
    ctx = make_context(weather_client)

    result = await get_city_weather("Nairobi", ctx, "KE")

    assert result.current.location_name == "Nairobi, Nairobi Area, Kenya"
    assert result.timezone == "Africa/Nairobi"
    assert result.daily_periods[4].condition == "Thunderstorm"


async def test_get_air_quality(router, weather_client):
    router.get(OPEN_METEO_GEOCODING_URL).mock(
        return_value=httpx2.Response(200, json=geocoding_payload())
    )
    router.get(OPEN_METEO_AIR_QUALITY_URL).mock(
        return_value=httpx2.Response(200, json=air_quality_payload())
    )
    ctx = make_context(weather_client)

    report = await get_air_quality("Nairobi", ctx, "KE")

    assert report.current.pm2_5 == 18.0
    assert report.current.dust == 35.0
    assert report.current.european_aqi == 45.0
    assert len(report.hourly_next_24h) == 24
    assert "Moderate dust" in report.dust_summary
    assert "PM2.5" in report.health_summary
    assert "high" in report.uv_summary


async def test_get_marine_forecast(router, weather_client):
    router.get(OPEN_METEO_GEOCODING_URL).mock(
        return_value=httpx2.Response(
            200,
            json=geocoding_payload(
                name="Mombasa",
                latitude=-4.0435,
                longitude=39.6682,
                country_code="KE",
            ),
        )
    )
    router.get(OPEN_METEO_MARINE_URL).mock(
        return_value=httpx2.Response(200, json=marine_payload())
    )
    ctx = make_context(weather_client)

    report = await get_marine_forecast("Mombasa", ctx, "KE")

    assert report.location_name.startswith("Mombasa")
    assert report.current.wave_height_m == 1.4
    assert report.current.sea_surface_temperature_c == 27.5
    assert len(report.daily_periods) == 5
    assert report.daily_periods[1].wave_height_max_m == 1.8


async def test_get_historical_weather(router, weather_client):
    router.get(OPEN_METEO_GEOCODING_URL).mock(
        return_value=httpx2.Response(200, json=geocoding_payload())
    )
    router.get(OPEN_METEO_ARCHIVE_URL).mock(
        return_value=httpx2.Response(200, json=archive_payload())
    )
    ctx = make_context(weather_client)

    report = await get_historical_weather(
        "Nairobi",
        "2024-01-01",
        "2024-01-03",
        ctx,
        "KE",
    )

    assert report.start_date == "2024-01-01"
    assert report.end_date == "2024-01-03"
    assert report.mean_temp_max_c == 27.0
    assert report.mean_temp_min_c == 15.0
    assert report.total_precipitation_mm == 16.0
    assert report.peak_wind_kmh == 25.0
    assert len(report.daily_records) == 3


async def test_compare_cities_weather(router, weather_client):
    coordinates = {
        "Nairobi": (-1.2921, 36.8219, "Kenya", "KE"),
        "Lagos": (6.5244, 3.3792, "Nigeria", "NG"),
        "Cape Town": (-33.9249, 18.4241, "South Africa", "ZA"),
    }

    def geocode_handler(request):
        name = request.url.params["name"]
        latitude, longitude, country, country_code = coordinates[name]
        return httpx2.Response(
            200,
            json=geocoding_payload(
                name=name,
                latitude=latitude,
                longitude=longitude,
                country=country,
                country_code=country_code,
            ),
        )

    def forecast_handler(request):
        latitude = float(request.url.params["latitude"])
        longitude = float(request.url.params["longitude"])
        return httpx2.Response(
            200,
            json=forecast_payload(
                latitude=latitude,
                longitude=longitude,
                temperature=25.0 + latitude / 10,
            ),
        )

    router.get(OPEN_METEO_GEOCODING_URL).mock(side_effect=geocode_handler)
    router.get(OPEN_METEO_FORECAST_URL).mock(side_effect=forecast_handler)
    ctx = make_context(weather_client)

    report = await compare_cities_weather(["Nairobi", "Lagos", "Cape Town"], ctx)

    assert len(report.cities) == 3
    assert {entry.city for entry in report.cities} == set(coordinates)
    assert report.warmest_city == "Lagos"
    assert report.coolest_city == "Cape Town"
    assert "Compared 3 cities" in report.summary


async def test_city_not_found_raises_tool_error(router, weather_client):
    router.get(OPEN_METEO_GEOCODING_URL).mock(
        return_value=httpx2.Response(200, json={"results": []})
    )
    ctx = make_context(weather_client)

    with pytest.raises(ToolError, match="Could not find coordinates"):
        await get_city_weather("Atlantis", ctx, "ZZ")


async def test_upstream_http_500_raises_tool_error(router, weather_client):
    route = router.get(OPEN_METEO_FORECAST_URL).mock(
        return_value=httpx2.Response(500, json={"reason": "upstream boom"})
    )
    ctx = make_context(weather_client)

    with pytest.raises(ToolError, match="HTTP 500"):
        await get_forecast(-1.2921, 36.8219, ctx)

    assert route.call_count == 1


async def test_invalid_historical_date_range(router, weather_client):
    ctx = make_context(weather_client)

    with pytest.raises(ToolError, match="must be on or before"):
        await get_historical_weather(
            "Nairobi",
            "2024-05-02",
            "2024-05-01",
            ctx,
        )


async def test_invalid_historical_date_format(router, weather_client):
    ctx = make_context(weather_client)

    with pytest.raises(ToolError, match="YYYY-MM-DD"):
        await get_historical_weather("Nairobi", "01/05/2024", "2024-05-02", ctx)


async def test_inland_marine_null_data_raises_tool_error(router, weather_client):
    router.get(OPEN_METEO_GEOCODING_URL).mock(
        return_value=httpx2.Response(200, json=geocoding_payload(name="Kisumu"))
    )
    router.get(OPEN_METEO_MARINE_URL).mock(
        return_value=httpx2.Response(
            200,
            json={
                "timezone": "Africa/Nairobi",
                "current": {
                    "wave_height": None,
                    "swell_wave_height": None,
                    "sea_surface_temperature": None,
                },
                "daily": {"time": []},
            },
        )
    )
    ctx = make_context(weather_client)

    with pytest.raises(ToolError, match="Marine data is unavailable"):
        await get_marine_forecast("Kisumu", ctx, "KE")


async def test_ttl_cache_prevents_duplicate_http_calls(router, weather_client):
    requests = []

    def geocode_handler(request):
        requests.append(request)
        return httpx2.Response(200, json=geocoding_payload())

    def forecast_handler(request):
        requests.append(request)
        return httpx2.Response(200, json=forecast_payload())

    geocode_route = router.get(OPEN_METEO_GEOCODING_URL).mock(side_effect=geocode_handler)
    forecast_route = router.get(OPEN_METEO_FORECAST_URL).mock(side_effect=forecast_handler)
    ctx = make_context(weather_client)

    first = await get_city_weather("Nairobi", ctx, "KE")
    second = await get_city_weather("Nairobi", ctx, "KE")

    assert first.model_dump() == second.model_dump()
    assert len(requests) == 2
    assert geocode_route.call_count == 1
    assert forecast_route.call_count == 1
