"""Shared async HTTP client and cache integration for Open-Meteo APIs."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx2

from .cache import AsyncTTLCache
from .constants import (
    HTTP_RETRIES,
    HTTP_RETRY_BACKOFF_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    LONG_CACHE_MAXSIZE,
    LONG_CACHE_TTL_SECONDS,
    MAX_CONCURRENT_REQUESTS,
    OPEN_METEO_AIR_QUALITY_URL,
    OPEN_METEO_ARCHIVE_URL,
    OPEN_METEO_FORECAST_URL,
    OPEN_METEO_GEOCODING_URL,
    OPEN_METEO_MARINE_URL,
    SHORT_CACHE_MAXSIZE,
    SHORT_CACHE_TTL_SECONDS,
    USER_AGENT,
)

logger = logging.getLogger(__name__)

RETRYABLE_EXCEPTIONS = (httpx2.TimeoutException, httpx2.TransportError)


class UpstreamAPIError(RuntimeError):
    """Raised when an Open-Meteo request fails after retries."""


def _cache_key(url: str, params: dict[str, Any]) -> str:
    serialized = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return f"{url}?{serialized}"


class OpenMeteoClient:
    """Concurrency-limited async Open-Meteo client with retries and TTL caching."""

    def __init__(
        self,
        *,
        timeout: float = HTTP_TIMEOUT_SECONDS,
        max_concurrency: int = MAX_CONCURRENT_REQUESTS,
        retries: int = HTTP_RETRIES,
        retry_backoff: float = HTTP_RETRY_BACKOFF_SECONDS,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be greater than zero")
        if retries <= 0:
            raise ValueError("retries must be greater than zero")
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._retries = retries
        self._retry_backoff = retry_backoff
        self._closed = False
        self._client = httpx2.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx2.Timeout(timeout),
            transport=transport,
        )
        self._long_cache = AsyncTTLCache[dict[str, Any]](
            maxsize=LONG_CACHE_MAXSIZE,
            ttl=LONG_CACHE_TTL_SECONDS,
            name="long-ttl",
        )
        self._short_cache = AsyncTTLCache[dict[str, Any]](
            maxsize=SHORT_CACHE_MAXSIZE,
            ttl=SHORT_CACHE_TTL_SECONDS,
            name="short-ttl",
        )

    async def __aenter__(self) -> OpenMeteoClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        if not self._closed:
            self._closed = True
            await self._client.aclose()

    @staticmethod
    def _response_reason(response: httpx2.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            reason = payload.get("reason") or payload.get("error")
            if reason:
                return str(reason)
        text = response.text.strip()
        return text[:200] if text else response.reason_phrase

    async def _request_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(1, self._retries + 1):
            try:
                async with self._semaphore:
                    response = await self._client.get(url, params=params)
            except RETRYABLE_EXCEPTIONS as exc:
                last_error = exc
                logger.warning(
                    "Open-Meteo transport error for %s (attempt %d/%d): %s",
                    url,
                    attempt,
                    self._retries,
                    exc,
                )
            else:
                if response.status_code >= 500:
                    last_error = UpstreamAPIError(
                        f"Open-Meteo returned HTTP {response.status_code} for {url}."
                    )
                    logger.warning(
                        "Open-Meteo server error for %s (attempt %d/%d): HTTP %d",
                        url,
                        attempt,
                        self._retries,
                        response.status_code,
                    )
                else:
                    try:
                        response.raise_for_status()
                    except httpx2.HTTPStatusError as exc:
                        message = (
                            f"Open-Meteo returned HTTP {response.status_code}: "
                            f"{self._response_reason(response)}"
                        )
                        logger.error("Open-Meteo request failed for %s: %s", url, message)
                        raise UpstreamAPIError(message) from exc
                    try:
                        data = response.json()
                    except ValueError as exc:
                        logger.error("Open-Meteo returned invalid JSON for %s", url)
                        raise UpstreamAPIError(
                            f"Open-Meteo returned invalid JSON for {url}."
                        ) from exc
                    if not isinstance(data, dict):
                        raise UpstreamAPIError(
                            f"Open-Meteo returned an unexpected payload for {url}."
                        )
                    return data

            if attempt < self._retries:
                delay = self._retry_backoff * (2 ** (attempt - 1))
                if delay:
                    await asyncio.sleep(delay)

        logger.error("Open-Meteo request failed after %d attempts: %s", self._retries, url)
        message = f"Open-Meteo request failed after {self._retries} attempts: {url}"
        if last_error is not None:
            message = f"{message} ({last_error})"
        raise UpstreamAPIError(message) from last_error

    async def _get(
        self,
        url: str,
        params: dict[str, Any],
        cache: AsyncTTLCache[dict[str, Any]],
    ) -> dict[str, Any]:
        key = _cache_key(url, params)
        data, hit = await cache.get_or_set(key, lambda: self._request_json(url, params))
        if hit:
            logger.debug("Serving %s from %s cache", url, cache.name)
        return data

    async def fetch_geocoding(
        self,
        name: str,
        *,
        count: int = 1,
        country_code: str = "",
    ) -> dict[str, Any]:
        """Resolve a place name through the Open-Meteo geocoding API."""
        params: dict[str, Any] = {
            "name": name,
            "count": count,
            "language": "en",
            "format": "json",
        }
        if country_code:
            params["country_code"] = country_code.upper()
        return await self._get(OPEN_METEO_GEOCODING_URL, params, self._long_cache)

    async def fetch_forecast(self, latitude: float, longitude: float) -> dict[str, Any]:
        """Fetch current conditions and a five-day forecast."""
        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max"
            ),
            "timezone": "auto",
            "forecast_days": 5,
        }
        return await self._get(OPEN_METEO_FORECAST_URL, params, self._short_cache)

    async def fetch_air_quality(self, latitude: float, longitude: float) -> dict[str, Any]:
        """Fetch current and hourly air quality, dust, and UV data."""
        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "pm10,pm2_5,dust,uv_index,european_aqi",
            "hourly": "pm2_5,dust,uv_index",
            "timezone": "auto",
            "forecast_days": 2,
        }
        return await self._get(OPEN_METEO_AIR_QUALITY_URL, params, self._short_cache)

    async def fetch_marine(self, latitude: float, longitude: float) -> dict[str, Any]:
        """Fetch current and daily marine conditions."""
        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "current": (
                "wave_height,wave_direction,wave_period,swell_wave_height,"
                "sea_surface_temperature"
            ),
            "daily": "wave_height_max,swell_wave_height_max,wave_period_max",
            "timezone": "auto",
            "forecast_days": 5,
        }
        return await self._get(OPEN_METEO_MARINE_URL, params, self._short_cache)

    async def fetch_historical(
        self,
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """Fetch archived daily weather for a date range."""
        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date,
            "end_date": end_date,
            "daily": (
                "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                "et0_fao_evapotranspiration,wind_speed_10m_max"
            ),
            "timezone": "auto",
        }
        return await self._get(OPEN_METEO_ARCHIVE_URL, params, self._long_cache)
