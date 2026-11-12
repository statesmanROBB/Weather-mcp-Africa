# ruff: noqa: E402, I001
"""Shared pytest fixtures. All Open-Meteo traffic is mocked; no live calls are made."""

from __future__ import annotations

import httpx2

# respx targets the `httpx` module. httpx2 ships an alias helper for libraries
# migrating from httpx, so alias it before respx is imported anywhere.
httpx2.alias_httpx()

from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
import respx  # noqa: E402

from weather_mcp_africa.client import OpenMeteoClient  # noqa: E402
from weather_mcp_africa.server import AppContext  # noqa: E402


@pytest.fixture
async def weather_client():
    """A client that never retries and never sleeps, used by tool tests."""
    client = OpenMeteoClient(retries=1, retry_backoff=0)
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture
def router():
    """A respx router that does not require every registered route to be called."""
    with respx.mock(assert_all_called=False) as mock_router:
        yield mock_router


def make_context(client: OpenMeteoClient) -> SimpleNamespace:
    """Build the minimal Context shape used by the tools."""
    return SimpleNamespace(
        request_context=SimpleNamespace(lifespan_context=AppContext(client=client))
    )


def geocoding_payload(
    name: str = "Nairobi",
    latitude: float = -1.2921,
    longitude: float = 36.8219,
    country: str = "Kenya",
    country_code: str = "KE",
) -> dict:
    return {
        "results": [
            {
                "id": 1,
                "name": name,
                "latitude": latitude,
                "longitude": longitude,
                "country": country,
                "country_code": country_code,
                "admin1": "Nairobi Area",
                "timezone": "Africa/Nairobi",
                "population": 4397073,
            }
        ]
    }


def forecast_payload(
    latitude: float = -1.2921,
    longitude: float = 36.8219,
    temperature: float = 24.5,
) -> dict:
    return {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": "Africa/Nairobi",
        "current": {
            "time": "2026-11-12T12:00",
            "temperature_2m": temperature,
            "relative_humidity_2m": 65,
            "wind_speed_10m": 12.3,
            "weather_code": 2,
        },
        "daily": {
            "time": [
                "2026-11-12",
                "2026-11-13",
                "2026-11-14",
                "2026-11-15",
                "2026-11-16",
            ],
            "weather_code": [2, 61, 3, 0, 95],
            "temperature_2m_max": [26.0, 24.0, 25.0, 27.0, 23.0],
            "temperature_2m_min": [15.0, 14.0, 15.5, 16.0, 14.5],
            "precipitation_probability_max": [20, 80, 30, 0, 90],
        },
    }


def air_quality_payload(dust: float = 35.0, pm2_5: float = 18.0) -> dict:
    return {
        "timezone": "Africa/Nairobi",
        "current": {
            "time": "2026-11-12T12:00",
            "pm10": 42.0,
            "pm2_5": pm2_5,
            "dust": dust,
            "uv_index": 7.2,
            "european_aqi": 45.0,
        },
        "hourly": {
            "time": [f"2026-11-12T{hour:02d}:00" for hour in range(24)],
            "pm2_5": [pm2_5 + hour * 0.1 for hour in range(24)],
            "dust": [dust + hour * 0.2 for hour in range(24)],
            "uv_index": [max(0.0, 7.2 - hour * 0.3) for hour in range(24)],
        },
    }


def marine_payload(
    wave_height: float | None = 1.4,
    swell_height: float | None = 0.9,
    sea_temperature: float | None = 27.5,
) -> dict:
    return {
        "timezone": "Africa/Nairobi",
        "current": {
            "time": "2026-11-12T12:00",
            "wave_height": wave_height,
            "wave_direction": 120.0,
            "wave_period": 8.5,
            "swell_wave_height": swell_height,
            "sea_surface_temperature": sea_temperature,
        },
        "daily": {
            "time": [
                "2026-11-12",
                "2026-11-13",
                "2026-11-14",
                "2026-11-15",
                "2026-11-16",
            ],
            "wave_height_max": [1.6, 1.8, 1.5, 1.2, 1.1],
            "swell_wave_height_max": [1.0, 1.1, 0.9, 0.8, 0.7],
            "wave_period_max": [9.0, 9.5, 8.8, 8.2, 8.0],
        },
    }


def archive_payload() -> dict:
    return {
        "timezone": "Africa/Nairobi",
        "daily": {
            "time": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "temperature_2m_max": [27.0, 28.0, 26.0],
            "temperature_2m_min": [15.0, 16.0, 14.0],
            "precipitation_sum": [0.0, 12.5, 3.5],
            "et0_fao_evapotranspiration": [4.5, 3.8, 4.1],
            "wind_speed_10m_max": [18.0, 25.0, 20.0],
        },
    }
