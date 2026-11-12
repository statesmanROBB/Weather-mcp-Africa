"""MCPServer definition, tools, resources, prompts, and CLI entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from collections.abc import AsyncIterator, Awaitable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from pydantic import ValidationError

from .client import OpenMeteoClient, UpstreamAPIError
from .constants import (
    AFRICA_WEATHER_HUBS,
    DEFAULT_COUNTRY_CODE,
    MAX_COMPARISON_CITIES,
    MAX_CONCURRENT_REQUESTS,
    MIN_COMPARISON_CITIES,
    WEATHER_TOOL_ANNOTATIONS,
    WMO_WEATHER_CODES,
)
from .models import (
    AirQualityCurrent,
    AirQualityHourlyPeriod,
    AirQualityReport,
    CityComparisonEntry,
    CityComparisonReport,
    CityList,
    CityName,
    CountryCode,
    CurrentConditions,
    DailyPeriod,
    DateString,
    Forecast,
    HistoricalDailyRecord,
    HistoricalWeatherSummary,
    Latitude,
    LocationCount,
    LocationResult,
    LocationSearchResults,
    Longitude,
    MarineCurrent,
    MarineDailyPeriod,
    MarineForecast,
)

logger = logging.getLogger(__name__)

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(slots=True)
class AppContext:
    """Lifespan state shared by every tool, resource, and prompt."""

    client: OpenMeteoClient


@asynccontextmanager
async def app_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    """Create and close the shared Open-Meteo client for the server lifetime."""
    client = OpenMeteoClient()
    logger.info(
        "Open-Meteo client ready (max concurrency=%d)",
        MAX_CONCURRENT_REQUESTS,
    )
    try:
        yield AppContext(client=client)
    finally:
        await client.close()
        logger.info("Open-Meteo client closed")


mcp = MCPServer(
    "weather-africa",
    title="Africa Weather Intelligence",
    version="0.2.0",
    instructions=(
        "Zero-key weather intelligence for Africa and the world. Use the tools to resolve "
        "locations, fetch forecasts, air quality, marine conditions, historical archives, "
        "and multi-city comparisons from Open-Meteo."
    ),
    lifespan=app_lifespan,
)


def configure_logging(level: int = logging.INFO) -> None:
    """Send structured application logs to stderr, never stdout."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def _client(ctx: Context) -> OpenMeteoClient:
    lifespan_context = ctx.request_context.lifespan_context
    if not isinstance(lifespan_context, AppContext):
        raise RuntimeError("Weather MCP lifespan context is unavailable.")
    return lifespan_context.client


def _describe_weather(code: int | None) -> str:
    if code is None:
        return "Unknown"
    return WMO_WEATHER_CODES.get(code, "Unknown")


def _float_at(series: Any, index: int) -> float | None:
    if not isinstance(series, list) or index >= len(series):
        return None
    value = series[index]
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_at(series: Any, index: int) -> int | None:
    value = _float_at(series, index)
    return None if value is None else int(round(value))


def _validate_date(value: str, field_name: str) -> date:
    if not _DATE_PATTERN.fullmatch(value):
        raise ToolError(
            f"{field_name} must use YYYY-MM-DD format (received {value!r})."
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolError(
            f"{field_name} is not a valid calendar date (received {value!r})."
        ) from exc


async def _call_upstream(
    awaitable: Awaitable[dict[str, Any]],
    description: str,
) -> dict[str, Any]:
    try:
        return await awaitable
    except UpstreamAPIError as exc:
        raise ToolError(f"Unable to fetch {description} from Open-Meteo: {exc}") from exc


async def _resolve_location(
    client: OpenMeteoClient,
    city: str,
    country_code: str,
) -> LocationResult:
    name = city.strip()
    if not name:
        raise ToolError("City name must not be empty.")

    data = await _call_upstream(
        client.fetch_geocoding(name, count=1, country_code=country_code),
        f"geocoding results for {name!r}",
    )
    raw_results = data.get("results")
    if not isinstance(raw_results, list) or not raw_results:
        country_label = country_code.upper() if country_code else "ANY"
        raise ToolError(
            f"Could not find coordinates for city {city!r} (country={country_label})."
        )

    record = raw_results[0]
    if not isinstance(record, dict):
        raise ToolError(f"Open-Meteo returned an invalid location record for {city!r}.")
    try:
        return LocationResult(
            name=str(record.get("name") or city),
            latitude=float(record["latitude"]),
            longitude=float(record["longitude"]),
            country=str(record.get("country") or ""),
            country_code=str(record.get("country_code") or ""),
            admin1=str(record.get("admin1") or ""),
            timezone=str(record.get("timezone") or ""),
            population=record.get("population"),
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise ToolError(
            f"Open-Meteo returned an invalid location record for {city!r}."
        ) from exc


def _display_name(location: LocationResult) -> str:
    parts = [location.name, location.admin1, location.country]
    return ", ".join(part for part in parts if part)


def _forecast_from_data(
    data: dict[str, Any],
    *,
    latitude: float,
    longitude: float,
    location_name: str,
) -> Forecast:
    current = data.get("current")
    daily = data.get("daily")
    if not isinstance(current, dict) or not isinstance(daily, dict):
        raise ToolError(f"Open-Meteo returned an incomplete forecast for {location_name}.")

    try:
        current_conditions = CurrentConditions(
            location_name=location_name,
            temperature_c=float(current["temperature_2m"]),
            relative_humidity_percent=int(round(float(current["relative_humidity_2m"]))),
            wind_speed_kmh=float(current["wind_speed_10m"]),
            condition=_describe_weather(_int_at([current.get("weather_code")], 0)),
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise ToolError(
            f"Open-Meteo returned incomplete current conditions for {location_name}."
        ) from exc

    dates = daily.get("time")
    if not isinstance(dates, list) or not dates:
        raise ToolError(f"Open-Meteo returned no daily forecast for {location_name}.")

    periods: list[DailyPeriod] = []
    for index, day in enumerate(dates):
        temp_max = _float_at(daily.get("temperature_2m_max"), index)
        temp_min = _float_at(daily.get("temperature_2m_min"), index)
        if temp_max is None or temp_min is None:
            continue
        precipitation_probability = _int_at(
            daily.get("precipitation_probability_max"), index
        )
        periods.append(
            DailyPeriod(
                date=str(day),
                temp_max_c=temp_max,
                temp_min_c=temp_min,
                precipitation_prob_max=precipitation_probability or 0,
                condition=_describe_weather(_int_at(daily.get("weather_code"), index)),
            )
        )

    if not periods:
        raise ToolError(f"Open-Meteo returned an empty daily forecast for {location_name}.")

    return Forecast(
        latitude=latitude,
        longitude=longitude,
        timezone=str(data.get("timezone") or "UTC"),
        current=current_conditions,
        daily_periods=periods,
    )


async def _city_forecast(
    client: OpenMeteoClient,
    city: str,
    country_code: str,
) -> tuple[LocationResult, Forecast]:
    location = await _resolve_location(client, city, country_code)
    data = await _call_upstream(
        client.fetch_forecast(location.latitude, location.longitude),
        f"forecast for {_display_name(location)}",
    )
    forecast = _forecast_from_data(
        data,
        latitude=location.latitude,
        longitude=location.longitude,
        location_name=_display_name(location),
    )
    return location, forecast


def _dust_summary(dust: float | None) -> str:
    if dust is None:
        return "Dust data is unavailable for this location."
    if dust >= 100:
        return (
            f"Severe dust event ({dust:.1f} ug/m3). Harmattan or Saharan dust is likely; "
            "expect reduced visibility and respiratory irritation."
        )
    if dust >= 50:
        return (
            f"Elevated dust ({dust:.1f} ug/m3). Sensitive groups should limit prolonged "
            "outdoor exertion."
        )
    if dust >= 20:
        return f"Moderate dust ({dust:.1f} ug/m3). Minor visibility and airway irritation possible."
    return f"Low dust ({dust:.1f} ug/m3). No significant dust event detected."


def _health_summary(pm2_5: float | None, european_aqi: float | None) -> str:
    aqi_text = (
        f" European AQI is {european_aqi:.0f}."
        if european_aqi is not None
        else ""
    )
    if pm2_5 is None:
        return f"PM2.5 data is unavailable.{aqi_text}".strip()
    if pm2_5 <= 10:
        guidance = "Air quality is good; outdoor activity is safe for most people."
    elif pm2_5 <= 25:
        guidance = "Air quality is acceptable; unusually sensitive people may notice effects."
    elif pm2_5 <= 50:
        guidance = "Sensitive groups should reduce prolonged outdoor exertion."
    elif pm2_5 <= 75:
        guidance = "Health effects are possible; consider limiting outdoor activity."
    else:
        guidance = (
            "Unhealthy air; avoid prolonged outdoor exertion and use filtration "
            "if available."
        )
    return f"PM2.5 is {pm2_5:.1f} ug/m3. {guidance}{aqi_text}".strip()


def _uv_summary(uv_index: float | None) -> str:
    if uv_index is None:
        return "UV data is unavailable."
    if uv_index < 3:
        category = "low"
        advice = "Minimal protection needed."
    elif uv_index < 6:
        category = "moderate"
        advice = "Use sunscreen and shade around midday."
    elif uv_index < 8:
        category = "high"
        advice = "Protect skin and eyes; avoid midday sun where possible."
    elif uv_index < 11:
        category = "very high"
        advice = "Limit sun exposure and use SPF 30+ sunscreen, hat, and sunglasses."
    else:
        category = "extreme"
        advice = "Avoid direct sun; unprotected skin can burn quickly."
    return f"UV index is {uv_index:.1f} ({category}). {advice}"


@mcp.tool(annotations=WEATHER_TOOL_ANNOTATIONS)
async def search_locations(
    query: CityName,
    ctx: Context,
    count: LocationCount = 5,
    country_code: CountryCode = "",
) -> LocationSearchResults:
    """Search for cities and towns by name and return matching coordinates.

    Args:
        query: Place name to search for, such as Nairobi, Mombasa, or Lagos.
        count: Maximum number of matches to return (1-20).
        country_code: Optional ISO alpha-2 filter, such as KE or TZ.
    """
    search_term = query.strip()
    if not search_term:
        raise ToolError("Search query must not be empty.")

    data = await _call_upstream(
        _client(ctx).fetch_geocoding(
            search_term,
            count=count,
            country_code=country_code,
        ),
        f"location search for {search_term!r}",
    )
    raw_results = data.get("results")
    if not isinstance(raw_results, list) or not raw_results:
        raise ToolError(
            f"No locations found for {search_term!r}"
            f" (country={country_code.upper() if country_code else 'ANY'})."
        )

    results: list[LocationResult] = []
    for record in raw_results[:count]:
        if not isinstance(record, dict):
            continue
        try:
            results.append(
                LocationResult(
                    name=str(record.get("name") or search_term),
                    latitude=float(record["latitude"]),
                    longitude=float(record["longitude"]),
                    country=str(record.get("country") or ""),
                    country_code=str(record.get("country_code") or ""),
                    admin1=str(record.get("admin1") or ""),
                    timezone=str(record.get("timezone") or ""),
                    population=record.get("population"),
                )
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise ToolError(
                f"Open-Meteo returned an invalid location record for {search_term!r}."
            ) from exc

    if not results:
        raise ToolError(f"No valid locations found for {search_term!r}.")
    return LocationSearchResults(
        query=search_term,
        count=len(results),
        results=results,
    )


@mcp.tool(annotations=WEATHER_TOOL_ANNOTATIONS)
async def get_forecast(
    latitude: Latitude,
    longitude: Longitude,
    ctx: Context,
    location_label: str = "Requested Coordinates",
) -> Forecast:
    """Get current weather and a 5-day forecast for any coordinate on Earth.

    Args:
        latitude: Latitude in decimal degrees (-90 to 90).
        longitude: Longitude in decimal degrees (-180 to 180).
        location_label: Optional friendly name for the location.
    """
    data = await _call_upstream(
        _client(ctx).fetch_forecast(latitude, longitude),
        f"forecast for ({latitude}, {longitude})",
    )
    return _forecast_from_data(
        data,
        latitude=latitude,
        longitude=longitude,
        location_name=location_label,
    )


@mcp.tool(annotations=WEATHER_TOOL_ANNOTATIONS)
async def get_city_weather(
    city: CityName,
    ctx: Context,
    country_code: CountryCode = DEFAULT_COUNTRY_CODE,
) -> Forecast:
    """Get current weather and a 5-day forecast by city name.

    Args:
        city: City or town name, such as Juja, Nairobi, Mombasa, Lagos, or Cairo.
        country_code: Optional ISO alpha-2 country filter. Defaults to KE; pass '' for any country.
    """
    _, forecast = await _city_forecast(_client(ctx), city, country_code)
    return forecast


@mcp.tool(annotations=WEATHER_TOOL_ANNOTATIONS)
async def get_air_quality(
    city: CityName,
    ctx: Context,
    country_code: CountryCode = "",
) -> AirQualityReport:
    """Get current air quality, dust, and UV conditions for a city.

    Dust is critical for tracking Harmattan, Saharan, and East African dust events.

    Args:
        city: City or town name.
        country_code: Optional ISO alpha-2 country filter. Pass '' for any country.
    """
    client = _client(ctx)
    location = await _resolve_location(client, city, country_code)
    data = await _call_upstream(
        client.fetch_air_quality(location.latitude, location.longitude),
        f"air quality for {_display_name(location)}",
    )

    current = data.get("current")
    if not isinstance(current, dict):
        raise ToolError(
            f"Open-Meteo returned no current air quality data for {_display_name(location)}."
        )

    pm10 = _float_at([current.get("pm10")], 0)
    pm2_5 = _float_at([current.get("pm2_5")], 0)
    dust = _float_at([current.get("dust")], 0)
    uv_index = _float_at([current.get("uv_index")], 0)
    european_aqi = _float_at([current.get("european_aqi")], 0)
    if all(value is None for value in (pm10, pm2_5, dust, uv_index, european_aqi)):
        raise ToolError(
            f"Open-Meteo returned no usable air quality values for {_display_name(location)}."
        )

    hourly = data.get("hourly")
    hourly_periods: list[AirQualityHourlyPeriod] = []
    if isinstance(hourly, dict):
        times = hourly.get("time")
        if isinstance(times, list):
            for index, timestamp in enumerate(times[:24]):
                hourly_periods.append(
                    AirQualityHourlyPeriod(
                        time=str(timestamp),
                        pm2_5=_float_at(hourly.get("pm2_5"), index),
                        dust=_float_at(hourly.get("dust"), index),
                        uv_index=_float_at(hourly.get("uv_index"), index),
                    )
                )

    return AirQualityReport(
        location_name=_display_name(location),
        latitude=location.latitude,
        longitude=location.longitude,
        timezone=str(data.get("timezone") or location.timezone or "UTC"),
        current=AirQualityCurrent(
            time=str(current.get("time") or ""),
            pm10=pm10,
            pm2_5=pm2_5,
            dust=dust,
            uv_index=uv_index,
            european_aqi=european_aqi,
        ),
        hourly_next_24h=hourly_periods,
        dust_summary=_dust_summary(dust),
        health_summary=_health_summary(pm2_5, european_aqi),
        uv_summary=_uv_summary(uv_index),
    )


@mcp.tool(annotations=WEATHER_TOOL_ANNOTATIONS)
async def get_marine_forecast(
    city: CityName,
    ctx: Context,
    country_code: CountryCode = "",
) -> MarineForecast:
    """Get current marine conditions and a 5-day coastal forecast for a city.

    Args:
        city: Coastal city name, such as Mombasa, Dar es Salaam, Lagos, or Cape Town.
        country_code: Optional ISO alpha-2 country filter. Pass '' for any country.
    """
    client = _client(ctx)
    location = await _resolve_location(client, city, country_code)
    data = await _call_upstream(
        client.fetch_marine(location.latitude, location.longitude),
        f"marine forecast for {_display_name(location)}",
    )

    current = data.get("current")
    current_data = current if isinstance(current, dict) else {}
    wave_height = _float_at([current_data.get("wave_height")], 0)
    swell_height = _float_at([current_data.get("swell_wave_height")], 0)
    sea_temperature = _float_at([current_data.get("sea_surface_temperature")], 0)
    if wave_height is None and swell_height is None and sea_temperature is None:
        raise ToolError(
            f"Marine data is unavailable for {_display_name(location)}. "
            "Open-Meteo returns null wave data for inland locations; try a coastal city "
            "such as Mombasa, Dar es Salaam, Lagos, or Cape Town."
        )

    daily = data.get("daily")
    daily_periods: list[MarineDailyPeriod] = []
    if isinstance(daily, dict):
        dates = daily.get("time")
        if isinstance(dates, list):
            for index, day in enumerate(dates):
                daily_periods.append(
                    MarineDailyPeriod(
                        date=str(day),
                        wave_height_max_m=_float_at(daily.get("wave_height_max"), index),
                        swell_wave_height_max_m=_float_at(
                            daily.get("swell_wave_height_max"), index
                        ),
                        wave_period_max_s=_float_at(
                            daily.get("wave_period_max"), index
                        ),
                    )
                )

    return MarineForecast(
        location_name=_display_name(location),
        latitude=location.latitude,
        longitude=location.longitude,
        timezone=str(data.get("timezone") or location.timezone or "UTC"),
        current=MarineCurrent(
            time=str(current_data.get("time") or ""),
            wave_height_m=wave_height,
            wave_direction_deg=_float_at([current_data.get("wave_direction")], 0),
            wave_period_s=_float_at([current_data.get("wave_period")], 0),
            swell_wave_height_m=swell_height,
            sea_surface_temperature_c=sea_temperature,
        ),
        daily_periods=daily_periods,
    )


@mcp.tool(annotations=WEATHER_TOOL_ANNOTATIONS)
async def get_historical_weather(
    city: CityName,
    start_date: DateString,
    end_date: DateString,
    ctx: Context,
    country_code: CountryCode = "",
) -> HistoricalWeatherSummary:
    """Get archived daily weather and summary statistics for a date range.

    Args:
        city: City or town name.
        start_date: Inclusive start date in YYYY-MM-DD format.
        end_date: Inclusive end date in YYYY-MM-DD format.
        country_code: Optional ISO alpha-2 country filter. Pass '' for any country.
    """
    start = _validate_date(start_date, "start_date")
    end = _validate_date(end_date, "end_date")
    if start > end:
        raise ToolError(
            f"start_date ({start_date}) must be on or before end_date ({end_date})."
        )

    client = _client(ctx)
    location = await _resolve_location(client, city, country_code)
    data = await _call_upstream(
        client.fetch_historical(
            location.latitude,
            location.longitude,
            start_date,
            end_date,
        ),
        f"historical weather for {_display_name(location)}",
    )

    daily = data.get("daily")
    dates = daily.get("time") if isinstance(daily, dict) else None
    if not isinstance(dates, list) or not dates:
        raise ToolError(
            f"Open-Meteo returned no historical daily data for {_display_name(location)}."
        )

    records: list[HistoricalDailyRecord] = []
    for index, day in enumerate(dates):
        records.append(
            HistoricalDailyRecord(
                date=str(day),
                temp_max_c=_float_at(daily.get("temperature_2m_max"), index),
                temp_min_c=_float_at(daily.get("temperature_2m_min"), index),
                precipitation_mm=_float_at(daily.get("precipitation_sum"), index),
                et0_mm=_float_at(
                    daily.get("et0_fao_evapotranspiration"), index
                ),
                wind_max_kmh=_float_at(daily.get("wind_speed_10m_max"), index),
            )
        )

    max_values = [record.temp_max_c for record in records if record.temp_max_c is not None]
    min_values = [record.temp_min_c for record in records if record.temp_min_c is not None]
    precipitation_values = [
        record.precipitation_mm
        for record in records
        if record.precipitation_mm is not None
    ]
    wind_values = [record.wind_max_kmh for record in records if record.wind_max_kmh is not None]

    return HistoricalWeatherSummary(
        location_name=_display_name(location),
        latitude=location.latitude,
        longitude=location.longitude,
        timezone=str(data.get("timezone") or location.timezone or "UTC"),
        start_date=start_date,
        end_date=end_date,
        mean_temp_max_c=round(sum(max_values) / len(max_values), 2) if max_values else None,
        mean_temp_min_c=round(sum(min_values) / len(min_values), 2) if min_values else None,
        total_precipitation_mm=round(sum(precipitation_values), 2),
        peak_wind_kmh=round(max(wind_values), 2) if wind_values else None,
        daily_records=records,
    )


@mcp.tool(annotations=WEATHER_TOOL_ANNOTATIONS)
async def compare_cities_weather(cities: CityList, ctx: Context) -> CityComparisonReport:
    """Compare current weather and 5-day forecasts for two to six cities.

    Args:
        cities: Two to six city names, for example ["Nairobi", "Lagos", "Cape Town"].
    """
    names = [city.strip() for city in cities if city.strip()]
    if len(names) < MIN_COMPARISON_CITIES or len(names) > MAX_COMPARISON_CITIES:
        raise ToolError(
            f"Provide between {MIN_COMPARISON_CITIES} and {MAX_COMPARISON_CITIES} city names."
        )

    client = _client(ctx)
    results = await asyncio.gather(
        *(_city_forecast(client, name, "") for name in names),
        return_exceptions=True,
    )

    entries: list[CityComparisonEntry] = []
    failures: list[str] = []
    for name, result in zip(names, results, strict=True):
        if isinstance(result, BaseException):
            failures.append(f"{name}: {result}")
            continue
        location, forecast = result
        entries.append(
            CityComparisonEntry(
                city=name,
                resolved_name=_display_name(location),
                latitude=location.latitude,
                longitude=location.longitude,
                timezone=forecast.timezone,
                current=forecast.current,
                daily_periods=forecast.daily_periods,
            )
        )

    if failures:
        raise ToolError("Unable to compare cities: " + "; ".join(failures))
    if not entries:
        raise ToolError("Unable to compare the requested cities.")

    warmest = max(entries, key=lambda entry: entry.current.temperature_c)
    coolest = min(entries, key=lambda entry: entry.current.temperature_c)
    summary = (
        f"{warmest.city} is currently warmest at {warmest.current.temperature_c:.1f} C; "
        f"{coolest.city} is coolest at {coolest.current.temperature_c:.1f} C. "
        f"Compared {len(entries)} cities across their five-day forecasts."
    )
    return CityComparisonReport(
        cities=entries,
        warmest_city=warmest.city,
        coolest_city=coolest.city,
        summary=summary,
    )


@mcp.resource("weather://africa/hubs", mime_type="application/json")
def get_africa_weather_hubs() -> str:
    """Static resource: major African weather, travel, and coastal hubs."""
    return json.dumps(AFRICA_WEATHER_HUBS, indent=2)


@mcp.resource("weather://kenya/cities", mime_type="text/plain")
def get_kenya_cities() -> str:
    """Backward-compatible static resource: reference coordinates for Kenyan hubs."""
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
async def read_city_weather_resource(city: str, ctx: Context) -> str:
    """Dynamic resource template: live JSON weather for a Kenyan city."""
    try:
        _, forecast = await _city_forecast(_client(ctx), city, DEFAULT_COUNTRY_CODE)
    except ToolError as exc:
        raise ResourceError(str(exc)) from exc
    return forecast.model_dump_json(indent=2)


@mcp.resource("weather://air-quality/{city}", mime_type="application/json")
async def read_air_quality_resource(city: str, ctx: Context) -> str:
    """Dynamic resource template: live JSON air quality for a city."""
    try:
        report = await get_air_quality(city, ctx, "")
    except ToolError as exc:
        raise ResourceError(str(exc)) from exc
    return report.model_dump_json(indent=2)


@mcp.resource("weather://marine/{city}", mime_type="application/json")
async def read_marine_resource(city: str, ctx: Context) -> str:
    """Dynamic resource template: live JSON marine forecast for a coastal city."""
    try:
        report = await get_marine_forecast(city, ctx, "")
    except ToolError as exc:
        raise ResourceError(str(exc)) from exc
    return report.model_dump_json(indent=2)


@mcp.prompt(title="Africa Weather & Travel Briefing")
def africa_weather_briefing(city: str = "Nairobi", country_code: str = "KE") -> str:
    """Reusable prompt for a city weather, air quality, and travel briefing."""
    normalized_country = country_code.upper()
    return (
        f"Please prepare a concise weather and travel briefing for {city} "
        f"({normalized_country}).\n\n"
        f"1. Call `get_city_weather` for city '{city}' with country_code "
        f"'{normalized_country}'.\n"
        "2. Call `get_air_quality` for the same city and summarize dust, PM2.5, and UV risk.\n"
        "3. Highlight current temperature (°C), humidity, wind speed, and heavy rain or "
        "thunderstorm risks over the next 5 days.\n"
        "4. Provide practical advice for commuting, outdoor work, and travel."
    )


@mcp.prompt(title="Coastal & Marine Safety Briefing")
def coastal_marine_safety_briefing(city: str = "Mombasa", country_code: str = "KE") -> str:
    """Reusable prompt for coastal and marine safety planning."""
    normalized_country = country_code.upper()
    return (
        f"Prepare a coastal and marine safety briefing for {city} "
        f"({normalized_country}).\n\n"
        f"1. Call `get_marine_forecast` for city '{city}' with country_code "
        f"'{normalized_country}'.\n"
        "2. Summarize wave height, swell, wave period, and sea surface temperature.\n"
        "3. Call `get_city_weather` and check for rain, thunderstorms, and high wind.\n"
        "4. Advise small craft, swimmers, fishers, and beachgoers on safety risks for the "
        "next five days."
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the MCP server."""
    parser = argparse.ArgumentParser(
        prog="weather-mcp-africa",
        description="Africa Weather MCP server (STDIO or Streamable HTTP).",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport protocol to use (default: stdio).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for Streamable HTTP transport (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for Streamable HTTP transport (default: 8000).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the MCP server over STDIO or Streamable HTTP."""
    args = build_parser().parse_args(argv)
    configure_logging()
    logger.info("Starting Africa Weather MCP server (transport=%s)", args.transport)
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        logger.info("Listening for Streamable HTTP on http://%s:%d/mcp", args.host, args.port)
        mcp.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
