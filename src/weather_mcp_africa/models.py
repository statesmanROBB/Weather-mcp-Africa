"""Typed Pydantic request and response schemas for the weather MCP server."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Latitude = Annotated[
    float,
    Field(
        ge=-90,
        le=90,
        description="Latitude in decimal degrees, from -90 (south) to 90 (north).",
    ),
]

Longitude = Annotated[
    float,
    Field(
        ge=-180,
        le=180,
        description="Longitude in decimal degrees, from -180 (west) to 180 (east).",
    ),
]

CityName = Annotated[
    str,
    Field(min_length=1, description="City or town name, for example Nairobi or Mombasa."),
]

DateString = Annotated[
    str,
    Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Calendar date in YYYY-MM-DD format.",
    ),
]

CountryCode = Annotated[
    str,
    Field(
        max_length=2,
        description="Optional ISO 3166-1 alpha-2 country code, for example KE or TZ.",
    ),
]

LocationCount = Annotated[
    int,
    Field(ge=1, le=20, description="Maximum number of matching locations to return (1-20)."),
]

CityList = Annotated[
    list[str],
    Field(
        min_length=2,
        max_length=6,
        description="Two to six city names to compare side by side.",
    ),
]


class StrictModel(BaseModel):
    """Base model that rejects undeclared fields."""

    model_config = ConfigDict(extra="forbid")


class LocationResult(StrictModel):
    """One location returned by the Open-Meteo geocoding API."""

    name: str = Field(description="Resolved place name.")
    latitude: Latitude
    longitude: Longitude
    country: str = Field(default="", description="Country name.")
    country_code: str = Field(default="", description="ISO alpha-2 country code.")
    admin1: str = Field(default="", description="First-level administrative region.")
    timezone: str = Field(default="", description="IANA timezone identifier.")
    population: int | None = Field(default=None, description="Approximate population.")


class LocationSearchResults(StrictModel):
    """Result payload returned by `search_locations`."""

    query: str = Field(description="Original search query.")
    count: int = Field(description="Number of matching locations returned.")
    results: list[LocationResult] = Field(description="Matching locations ordered by relevance.")


class CurrentConditions(StrictModel):
    """Current live weather conditions at a coordinate."""

    location_name: str = Field(description="Resolved city/region name or coordinates.")
    temperature_c: float = Field(description="Current air temperature in Celsius.")
    relative_humidity_percent: int = Field(description="Relative humidity percentage.")
    wind_speed_kmh: float = Field(description="Wind speed at 10m in km/h.")
    condition: str = Field(description="Human-readable weather condition.")


class DailyPeriod(StrictModel):
    """One day in a multi-day weather forecast."""

    date: str = Field(description="Forecast date (YYYY-MM-DD).")
    temp_max_c: float = Field(description="Maximum daily temperature in Celsius.")
    temp_min_c: float = Field(description="Minimum daily temperature in Celsius.")
    precipitation_prob_max: int = Field(description="Max precipitation probability (%).")
    condition: str = Field(description="Human-readable weather condition.")


class Forecast(StrictModel):
    """Structured forecast payload returned by `get_forecast` and `get_city_weather`."""

    latitude: Latitude
    longitude: Longitude
    timezone: str = Field(description="Local timezone identifier (e.g., Africa/Nairobi).")
    current: CurrentConditions = Field(description="Current live weather conditions.")
    daily_periods: list[DailyPeriod] = Field(description="Next 5 days forecast.")


class AirQualityCurrent(StrictModel):
    """Current air quality and UV values."""

    time: str = Field(description="Observation timestamp returned by Open-Meteo.")
    pm10: float | None = Field(default=None, description="PM10 concentration (ug/m3).")
    pm2_5: float | None = Field(default=None, description="PM2.5 concentration (ug/m3).")
    dust: float | None = Field(default=None, description="Saharan dust concentration (ug/m3).")
    uv_index: float | None = Field(default=None, description="Current UV index.")
    european_aqi: float | None = Field(default=None, description="European AQI value.")


class AirQualityHourlyPeriod(StrictModel):
    """One hour in the next-24-hour air quality outlook."""

    time: str = Field(description="Hourly timestamp returned by Open-Meteo.")
    pm2_5: float | None = Field(default=None, description="PM2.5 concentration (ug/m3).")
    dust: float | None = Field(default=None, description="Dust concentration (ug/m3).")
    uv_index: float | None = Field(default=None, description="UV index.")


class AirQualityReport(StrictModel):
    """Air quality, dust, and UV report for a location."""

    location_name: str = Field(description="Resolved city/region name.")
    latitude: Latitude
    longitude: Longitude
    timezone: str = Field(description="Local timezone identifier.")
    current: AirQualityCurrent = Field(description="Current air quality values.")
    hourly_next_24h: list[AirQualityHourlyPeriod] = Field(
        description="Hourly PM2.5, dust, and UV values for the next 24 hours."
    )
    dust_summary: str = Field(description="Plain-language dust and Harmattan risk summary.")
    health_summary: str = Field(description="Plain-language particulate health guidance.")
    uv_summary: str = Field(description="Plain-language UV exposure guidance.")


class MarineCurrent(StrictModel):
    """Current marine conditions at a coastal location."""

    time: str = Field(default="", description="Observation timestamp returned by Open-Meteo.")
    wave_height_m: float | None = Field(default=None, description="Significant wave height (m).")
    wave_direction_deg: float | None = Field(default=None, description="Wave direction (degrees).")
    wave_period_s: float | None = Field(default=None, description="Wave period (seconds).")
    swell_wave_height_m: float | None = Field(default=None, description="Swell wave height (m).")
    sea_surface_temperature_c: float | None = Field(
        default=None, description="Sea surface temperature (C)."
    )


class MarineDailyPeriod(StrictModel):
    """One day in a marine forecast."""

    date: str = Field(description="Forecast date (YYYY-MM-DD).")
    wave_height_max_m: float | None = Field(default=None, description="Maximum wave height (m).")
    swell_wave_height_max_m: float | None = Field(
        default=None, description="Maximum swell wave height (m)."
    )
    wave_period_max_s: float | None = Field(default=None, description="Maximum wave period (s).")


class MarineForecast(StrictModel):
    """Marine and coastal conditions for a location."""

    location_name: str = Field(description="Resolved coastal city/region name.")
    latitude: Latitude
    longitude: Longitude
    timezone: str = Field(description="Local timezone identifier.")
    current: MarineCurrent = Field(description="Current marine conditions.")
    daily_periods: list[MarineDailyPeriod] = Field(description="Five-day marine outlook.")


class HistoricalDailyRecord(StrictModel):
    """One archived day of historical weather."""

    date: DateString
    temp_max_c: float | None = Field(default=None, description="Maximum temperature (C).")
    temp_min_c: float | None = Field(default=None, description="Minimum temperature (C).")
    precipitation_mm: float | None = Field(default=None, description="Total precipitation (mm).")
    et0_mm: float | None = Field(
        default=None, description="FAO reference evapotranspiration (mm)."
    )
    wind_max_kmh: float | None = Field(default=None, description="Maximum wind speed (km/h).")


class HistoricalWeatherSummary(StrictModel):
    """Aggregated historical weather for a date range."""

    location_name: str = Field(description="Resolved city/region name.")
    latitude: Latitude
    longitude: Longitude
    timezone: str = Field(description="Local timezone identifier.")
    start_date: DateString
    end_date: DateString
    mean_temp_max_c: float | None = Field(default=None, description="Mean daily maximum (C).")
    mean_temp_min_c: float | None = Field(default=None, description="Mean daily minimum (C).")
    total_precipitation_mm: float = Field(description="Total rainfall in the period (mm).")
    peak_wind_kmh: float | None = Field(default=None, description="Peak daily wind (km/h).")
    daily_records: list[HistoricalDailyRecord] = Field(description="Per-day historical values.")


class CityComparisonEntry(StrictModel):
    """Weather summary for one city in a comparison report."""

    city: str = Field(description="City name supplied by the caller.")
    resolved_name: str = Field(description="Fully resolved location name.")
    latitude: Latitude
    longitude: Longitude
    timezone: str = Field(description="Local timezone identifier.")
    current: CurrentConditions = Field(description="Current live weather conditions.")
    daily_periods: list[DailyPeriod] = Field(description="Five-day forecast.")


class CityComparisonReport(StrictModel):
    """Side-by-side weather comparison for two to six cities."""

    cities: list[CityComparisonEntry] = Field(description="Comparable weather for each city.")
    warmest_city: str = Field(description="City with the highest current temperature.")
    coolest_city: str = Field(description="City with the lowest current temperature.")
    summary: str = Field(description="Plain-language comparison summary.")
