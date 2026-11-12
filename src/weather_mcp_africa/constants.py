"""Shared constants for the Africa Weather MCP server."""

from __future__ import annotations

from mcp.types import ToolAnnotations

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPEN_METEO_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

USER_AGENT = "weather-africa-mcp/2.0 (+https://github.com/statesmanROBB/weather-mcp-africa)"

DEFAULT_COUNTRY_CODE = "KE"
DEFAULT_FORECAST_DAYS = 5
MAX_COMPARISON_CITIES = 6
MIN_COMPARISON_CITIES = 2

LONG_CACHE_TTL_SECONDS = 24 * 60 * 60
SHORT_CACHE_TTL_SECONDS = 10 * 60
LONG_CACHE_MAXSIZE = 512
SHORT_CACHE_MAXSIZE = 512

MAX_CONCURRENT_REQUESTS = 10
HTTP_TIMEOUT_SECONDS = 20.0
HTTP_RETRIES = 3
HTTP_RETRY_BACKOFF_SECONDS = 0.5

WMO_WEATHER_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

WEATHER_TOOL_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)

AFRICA_WEATHER_HUBS: dict[str, dict[str, float | str]] = {
    "Nairobi, Kenya": {"latitude": -1.2921, "longitude": 36.8219, "role": "East Africa hub"},
    "Mombasa, Kenya": {"latitude": -4.0435, "longitude": 39.6682, "role": "Coastal hub"},
    "Kisumu, Kenya": {"latitude": -0.0917, "longitude": 34.768, "role": "Lake Victoria hub"},
    "Dar es Salaam, Tanzania": {"latitude": -6.7924, "longitude": 39.2083, "role": "Coastal hub"},
    "Kampala, Uganda": {"latitude": 0.3476, "longitude": 32.5825, "role": "Great Lakes hub"},
    "Addis Ababa, Ethiopia": {"latitude": 9.032, "longitude": 38.7469, "role": "Highland hub"},
    "Lagos, Nigeria": {"latitude": 6.5244, "longitude": 3.3792, "role": "West Africa coastal hub"},
    "Accra, Ghana": {"latitude": 5.6037, "longitude": -0.187, "role": "West Africa coastal hub"},
    "Dakar, Senegal": {"latitude": 14.7167, "longitude": -17.4677, "role": "Sahel coastal hub"},
    "Cairo, Egypt": {"latitude": 30.0444, "longitude": 31.2357, "role": "North Africa hub"},
    "Cape Town, South Africa": {
        "latitude": -33.9249,
        "longitude": 18.4241,
        "role": "Southern Africa coastal hub",
    },
    "Johannesburg, South Africa": {
        "latitude": -26.2041,
        "longitude": 28.0473,
        "role": "Southern Africa hub",
    },
}
