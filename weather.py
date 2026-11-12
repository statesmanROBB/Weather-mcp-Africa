"""Compatibility shim so `uv run weather.py` keeps working after the package refactor."""

from __future__ import annotations

from weather_mcp_africa.server import main, mcp

__all__ = ["main", "mcp"]


if __name__ == "__main__":
    main()
