# Africa Weather MCP Server

Zero-key weather intelligence for Africa and the world, exposed as a Python **Model Context
Protocol (MCP)** server. It uses the modern `MCPServer` SDK API, `pydantic` output schemas,
`httpx2` async I/O, and the Open-Meteo family of APIs.

The server supports both **STDIO** (desktop hosts such as Claude Desktop) and **Streamable HTTP**
(remote or containerized deployments). It has no API keys, no paid tiers, and no required
configuration.

## Architecture

```text
┌────────────────────────────┐   STDIO JSON-RPC 2.0   ┌──────────────────────────────────┐
│ MCP Host / Agent / Client  │ ◄────────────────────► │ src/weather_mcp_africa/          │
│ Claude Desktop, Inspector, │   or Streamable HTTP   │                                  │
│ custom Python clients      │   POST /mcp            │ server.py  tools/resources/prompts│
└────────────────────────────┘                        │ client.py  shared httpx2 + retry │
                                                      │ cache.py   async-safe TTLCache   │
                                                      │ models.py  Pydantic schemas      │
                                                      │ constants.py API URLs/WMO codes  │
                                                      └────────────────┬─────────────────┘
                                                                       │ HTTPS / JSON
                                                                       ▼
                                                      ┌──────────────────────────────────┐
                                                      │ Open-Meteo APIs                  │
                                                      │ Forecast · Geocoding · Air       │
                                                      │ Quality · Marine · Archive       │
                                                      └──────────────────────────────────┘
```

The root `weather.py` file is a compatibility shim, so `uv run weather.py` continues to work.
The installed console script is `weather-mcp-africa`.

### Design highlights

- **Async-safe TTL caching:** geocoding and historical archive responses are cached for 24 hours;
  live forecast, air quality, and marine responses are cached for 10 minutes.
- **Concurrency limiting:** a shared `asyncio.Semaphore(10)` caps upstream requests.
- **Retries and timeouts:** transient transport errors and HTTP 5xx responses are retried with
  exponential backoff, then surfaced as clear `ToolError` messages.
- **Protocol hygiene:** structured logs always go to `stderr`; `stdout` is reserved for STDIO
  JSON-RPC framing.
- **Strict validation:** latitude/longitude bounds, city list size, date format/order, and typed
  output schemas are enforced with Pydantic.
- **Safe host hints:** every read tool declares `read_only_hint=True`, `destructive_hint=False`,
  `idempotent_hint=True`, and `open_world_hint=True`.

## Installation

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/statesmanROBB/weather-mcp-africa.git
cd weather-mcp-africa
uv sync
```

## Running the server

### STDIO (default)

```bash
uv run weather.py
# or
uv run weather-mcp-africa
```

### Streamable HTTP

```bash
uv run weather.py --transport http --host 127.0.0.1 --port 8000
# or
uv run weather-mcp-africa --transport http --host 0.0.0.0 --port 8000
```

The MCP endpoint is `http://<host>:<port>/mcp`. CLI options:

| Option | Values | Default | Description |
| --- | --- | --- | --- |
| `--transport` | `stdio`, `http` | `stdio` | STDIO or Streamable HTTP transport. |
| `--host` | host string | `127.0.0.1` | Bind address for HTTP mode. |
| `--port` | integer | `8000` | Bind port for HTTP mode. |

### Claude Desktop configuration

```json
{
  "mcpServers": {
    "weather-africa": {
      "command": "/home/robb/.local/bin/uv",
      "args": [
        "--directory",
        "/ABSOLUTE/PATH/TO/weather-mcp-africa",
        "run",
        "weather.py"
      ]
    }
  }
}
```

### MCP Inspector

```bash
npx @modelcontextprotocol/inspector uv run weather.py
```

## Tools

| Tool | Signature | Returns | Notes |
| --- | --- | --- | --- |
| `search_locations` | `(query, count=5, country_code="")` | `LocationSearchResults` | Geocodes a name and returns matching coordinates. |
| `get_forecast` | `(latitude, longitude, location_label="Requested Coordinates")` | `Forecast` | Current conditions plus five daily periods. |
| `get_city_weather` | `(city, country_code="KE")` | `Forecast` | Backward-compatible city lookup; default country is Kenya. |
| `get_air_quality` | `(city, country_code="")` | `AirQualityReport` | PM10, PM2.5, dust, UV, European AQI, plus 24-hour hourly values. |
| `get_marine_forecast` | `(city, country_code="")` | `MarineForecast` | Wave height/direction/period, swell, sea temperature, five-day daily maxima. |
| `get_historical_weather` | `(city, start_date, end_date, country_code="")` | `HistoricalWeatherSummary` | `YYYY-MM-DD` dates; mean temperatures, total rainfall, peak wind, daily records. |
| `compare_cities_weather` | `(cities)` | `CityComparisonReport` | Two to six cities fetched concurrently with `asyncio.gather`. |

`get_marine_forecast` raises an actionable `ToolError` when Open-Meteo returns null wave data for
an inland city. `get_historical_weather` validates both date format and chronological order.

## Resources

| URI | MIME type | Description |
| --- | --- | --- |
| `weather://africa/hubs` | `application/json` | Static JSON reference for major African weather, travel, and coastal hubs. |
| `weather://kenya/cities` | `text/plain` | Backward-compatible Kenyan coordinate reference. |
| `weather://city/{city}` | `application/json` | Live JSON forecast for a Kenyan city. |
| `weather://air-quality/{city}` | `application/json` | Live JSON air quality, dust, and UV report. |
| `weather://marine/{city}` | `application/json` | Live JSON marine and coastal report. |

## Prompts

| Prompt | Arguments | Description |
| --- | --- | --- |
| `africa_weather_briefing` | `city="Nairobi"`, `country_code="KE"` | Title: **Africa Weather & Travel Briefing**. Combines forecast, air quality, dust, UV, and travel advice. |
| `coastal_marine_safety_briefing` | `city="Mombasa"`, `country_code="KE"` | Title: **Coastal & Marine Safety Briefing**. Covers waves, swell, weather, and small-craft safety. |

## Development

All tests mock Open-Meteo; they make zero live network calls. `respx` is used with the
`httpx2.alias_httpx()` compatibility shim, so the tests exercise the same `httpx2` client as
production.

```bash
uv sync
uv run ruff check .
uv run pytest -v
```

CI runs the same commands on pushes and pull requests to `main` through
`.github/workflows/ci.yml`.

### Project layout

```text
src/weather_mcp_africa/
├── __init__.py
├── cache.py       # async-safe TTLCache wrapper with per-key stampede protection
├── client.py      # shared httpx2 client, semaphore, retries, cache integration
├── constants.py   # API URLs, WMO codes, TTLs, annotations, hub data
├── models.py      # Pydantic input/output schemas
└── server.py      # MCPServer, lifespan, tools, resources, prompts, CLI
tests/
├── conftest.py
├── test_cache_and_server.py
└── test_tools.py
weather.py         # compatibility shim for `uv run weather.py`
```

## Data source and attribution

Weather, air quality, marine, and historical data are provided by
[Open-Meteo](https://open-meteo.com/). Open-Meteo data is licensed under
[Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).
This project is not affiliated with Open-Meteo. If you redistribute data obtained through this
server, retain the Open-Meteo attribution and CC BY 4.0 notice.
