import json
from typing import Any

import httpx2
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

# 1. Initialize the MCP server
mcp = MCPServer("weather-africa")

# 2. Open-Meteo API Endpoints (Free, global coverage, no API key required)
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
USER_AGENT = "weather-africa-mcp/1.0"

# WMO Weather interpretation codes mapped to human-readable descriptions
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
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
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


# 3. Structured Output Schemas (Pydantic Models)
class CurrentConditions(BaseModel):
    """Current live weather conditions at a coordinate."""

    location_name: str = Field(description="Resolved city/region name or coordinates")
    temperature_c: float = Field(description="Current air temperature in Celsius")
    relative_humidity_percent: int = Field(description="Relative humidity percentage")
    wind_speed_kmh: float = Field(description="Wind speed at 10m in km/h")
    condition: str = Field(description="Human-readable weather condition")


class DailyPeriod(BaseModel):
    """One day in a multi-day weather forecast."""

    date: str = Field(description="Forecast date (YYYY-MM-DD)")
    temp_max_c: float = Field(description="Maximum daily temperature in Celsius")
    temp_min_c: float = Field(description="Minimum daily temperature in Celsius")
    precipitation_prob_max: int = Field(description="Max precipitation probability (%)")
    condition: str = Field(description="Human-readable weather condition")


class Forecast(BaseModel):
    """Structured forecast payload returned by `get_forecast`."""

    latitude: float = Field(description="Latitude the forecast is for")
    longitude: float = Field(description="Longitude the forecast is for")
    timezone: str = Field(description="Local timezone identifier (e.g., Africa/Nairobi)")
    current: CurrentConditions = Field(description="Current live weather conditions")
    daily_periods: list[DailyPeriod] = Field(description="Next 5 days forecast")


# 4. Async Network Helper
async def fetch_json(url: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """Make an async GET request with query parameters and error handling."""
    headers = {"User-Agent": USER_AGENT}
    async with httpx2.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, headers=headers, timeout=20.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None


# ==============================================================================
# PRIMITIVE 1: TOOLS (Model-controlled functions invoked by the LLM)
# ==============================================================================


@mcp.tool(annotations=WEATHER_TOOL_ANNOTATIONS)
async def get_forecast(
    latitude: float,
    longitude: float,
    location_label: str = "Requested Coordinates",
) -> Forecast:
    """Get current weather and a 5-day forecast for any coordinate in Kenya, Africa, or globally.

    Args:
        latitude: Latitude of the location (e.g., -1.1025 for Juja, -1.2921 for Nairobi)
        longitude: Longitude of the location (e.g., 37.0144 for Juja, 36.8219 for Nairobi)
        location_label: Optional friendly name for the location
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto",
        "forecast_days": 5,
    }
    data = await fetch_json(OPEN_METEO_FORECAST_URL, params)

    if not data or "current" not in data or "daily" not in data:
        raise ToolError(f"Unable to fetch Open-Meteo forecast for ({latitude}, {longitude}).")

    curr = data["current"]
    daily = data["daily"]

    current_conditions = CurrentConditions(
        location_name=location_label,
        temperature_c=curr["temperature_2m"],
        relative_humidity_percent=curr["relative_humidity_2m"],
        wind_speed_kmh=curr["wind_speed_10m"],
        condition=WMO_WEATHER_CODES.get(curr.get("weather_code", -1), "Unknown"),
    )

    periods: list[DailyPeriod] = []
    dates = daily.get("time", [])
    for i in range(len(dates)):
        code = daily["weather_code"][i]
        prob = daily["precipitation_probability_max"][i]
        periods.append(
            DailyPeriod(
                date=dates[i],
                temp_max_c=daily["temperature_2m_max"][i],
                temp_min_c=daily["temperature_2m_min"][i],
                precipitation_prob_max=prob if prob is not None else 0,
                condition=WMO_WEATHER_CODES.get(code, "Unknown"),
            )
        )

    return Forecast(
        latitude=data.get("latitude", latitude),
        longitude=data.get("longitude", longitude),
        timezone=data.get("timezone", "Africa/Nairobi"),
        current=current_conditions,
        daily_periods=periods,
    )


@mcp.tool(annotations=WEATHER_TOOL_ANNOTATIONS)
async def get_city_weather(city: str, country_code: str = "KE") -> Forecast:
    """Get current weather and a 5-day forecast by searching for a city or town name.

    Args:
        city: City or town name (e.g., Juja, Nairobi, Mombasa, Kisumu, Lagos, Cairo)
        country_code: Optional 2-letter ISO country code filter (default 'KE' for Kenya; pass '' for any country)
    """
    geo_params: dict[str, Any] = {"name": city, "count": 1, "language": "en", "format": "json"}
    if country_code:
        geo_params["country_code"] = country_code.upper()

    geo_data = await fetch_json(OPEN_METEO_GEOCODING_URL, geo_params)
    results = geo_data.get("results") if geo_data else None

    if not results:
        raise ToolError(f"Could not find coordinates for city '{city}' (country={country_code or 'ANY'}).")

    top_match = results[0]
    resolved_name = f"{top_match['name']}, {top_match.get('admin1', '')}, {top_match.get('country', '')}".strip(", ")

    return await get_forecast(
        latitude=top_match["latitude"],
        longitude=top_match["longitude"],
        location_label=resolved_name,
    )


# ==============================================================================
# PRIMITIVE 2: RESOURCES (Read-only URI context attached by the user/client)
# ==============================================================================


@mcp.resource("weather://kenya/cities", mime_type="text/plain")
def get_kenya_cities() -> str:
    """Static resource: reference coordinates for major Kenyan towns and cities."""
    return (
        "Key Kenyan Coordinates (Latitude, Longitude):\n"
        "- Juja, Kiambu: -1.1025, 37.0144\n"
        "- Nairobi: -1.2921, 36.8219\n"
        "- Mombasa: -4.0435, 39.6682\n"
        "- Kisumu: -0.0917, 34.7680\n"
        "- Nakuru: -0.3031, 36.0800\n"
        "- Eldoret: 0.5143, 35.2698"
    )


@mcp.resource("weather://city/{city}", mime_type="application/json")
async def read_city_weather_resource(city: str) -> str:
    """Dynamic resource template: fetch live JSON weather data for a Kenyan city via URI."""
    forecast = await get_city_weather(city=city, country_code="KE")
    return forecast.model_dump_json(indent=2)


# ==============================================================================
# PRIMITIVE 3: PROMPTS (User-triggered workflow templates in the host UI)
# ==============================================================================


@mcp.prompt(title="Kenya & East Africa Weather Briefing")
def africa_weather_briefing(city: str = "Nairobi", country_code: str = "KE") -> str:
    """Reusable prompt template for checking weather and rain risks in Kenya or Africa."""
    return (
        f"Please prepare a concise weather and travel briefing for {city} ({country_code.upper()}).\n\n"
        f"1. Call `get_city_weather` for city '{city}' with country_code '{country_code.upper()}'.\n"
        f"2. Highlight the current temperature (°C), humidity, wind speed, and any heavy rain or thunderstorm risks over the next 5 days.\n"
        f"3. Provide practical advice for commuting, outdoor work, or travel."
    )


# ==============================================================================
# SERVER ENTRY POINT
# ==============================================================================


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()