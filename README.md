# Africa & Kenya Weather MCP Server

An asynchronous **Model Context Protocol (MCP)** server built in Python that connects AI agents and desktop hosts (such as Claude Desktop, MCP Inspector, and custom Python clients) to live global and African meteorological data via **Open-Meteo** over **STDIO JSON-RPC 2.0** transport.

---

## Architecture

```text
┌───────────────────────────┐       STDIO (JSON-RPC 2.0)       ┌──────────────────────────┐
│         MCP Host          │ ◄──────────────────────────────► │   weather.py (MCPServer) │
│ (Claude Desktop / Agent)  │   stdin: requests/notifications  │   - Async httpx2 client  │
└───────────────────────────┘   stdout: structured responses   │   - Pydantic validation  │
                                                               └────────────┬─────────────┘
                                                                            │ HTTPS (REST/JSON)
                                                                            ▼
                                                               ┌──────────────────────────┐
                                                               │     Open-Meteo API       │
                                                               │ (Forecast & Geocoding)   │
                                                               └──────────────────────────┘
```

### Engineering Highlights
* **Zero-Key African & Global Coverage:** Integrates Open-Meteo's Forecast and Geocoding APIs with WMO weather code interpretation—supporting Kenyan towns and cities (`Juja`, `Nairobi`, `Mombasa`, `Kisumu`) and all African countries with zero API key setup.
* **Non-Blocking Async I/O:** Uses `httpx2.AsyncClient` inside Python's `asyncio` event loop so external HTTP requests never block JSON-RPC message handling.
* **Strict STDIO Protocol Hygiene:** Keeps `stdout` strictly isolated for JSON-RPC frames (no `print()` calls in server execution paths).
* **Typed Output Validation (`outputSchema`):** Defines Pydantic `BaseModel` return schemas (`Forecast`, `CurrentConditions`, `DailyPeriod`) so hosts validate responses automatically.
* **Safe Host Hints (`ToolAnnotations`):** Declares `read_only_hint=True` and `idempotent_hint=True` so MCP hosts can safely auto-approve read-only weather lookups.

---

## MCP Capabilities

### 1. Tools (`@mcp.tool`)
* **`get_city_weather(city: str, country_code: str = "KE") -> Forecast`**: Resolves a city or town name (e.g., `"Juja"`, `"Nairobi"`, `"Lagos"`, `"Cairo"`) to geographic coordinates via Open-Meteo Geocoding and returns live conditions plus a 5-day forecast.
* **`get_forecast(latitude: float, longitude: float, location_label: str) -> Forecast`**: Queries live temperature (°C), relative humidity, wind speed (km/h), and 5-day precipitation probabilities for any coordinate pair.

### 2. Resources (`@mcp.resource`)
* **`weather://kenya/cities`** (`text/plain`): Static reference guide listing coordinates for major Kenyan cities and towns.
* **`weather://city/{city}`** (`application/json`): Dynamic URI template returning live structured JSON weather telemetry for a requested Kenyan city.

### 3. Prompts (`@mcp.prompt`)
* **`Kenya & East Africa Weather Briefing`**: Reusable prompt template that instructs the host LLM to fetch city weather, evaluate rain/thunderstorm risks, and generate a travel safety summary.

---

## Quickstart (Linux / `uv`)

### 1. Clone & Sync Environment
```bash
git clone https://github.com/statesmanROBB/weather-mcp-africa.git
cd weather-mcp-africa
uv sync
```

### 2. Test with MCP Inspector
```bash
npx @modelcontextprotocol/inspector uv run weather.py
```

### 3. Claude for Desktop Configuration (`~/.config/Claude/claude_desktop_config.json`)
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