"""Async-safe TTL cache utilities built on top of cachetools."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

from cachetools import TTLCache

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AsyncTTLCache(Generic[T]):
    """A small async-safe wrapper around ``cachetools.TTLCache``.

    The cache protects its internal mapping with an ``asyncio.Lock`` and uses a
    per-key lock to prevent a cache stampede when several concurrent requests
    miss the same key.
    """

    def __init__(self, *, maxsize: int, ttl: int, name: str = "cache") -> None:
        if maxsize <= 0:
            raise ValueError("maxsize must be greater than zero")
        if ttl <= 0:
            raise ValueError("ttl must be greater than zero")
        self._cache: TTLCache[str, T] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = asyncio.Lock()
        self._key_locks: dict[str, asyncio.Lock] = {}
        self._name = name

    @property
    def name(self) -> str:
        """Human-readable cache name used in logs."""
        return self._name

    async def get(self, key: str) -> T | None:
        """Return a cached value, logging whether the lookup hit or missed."""
        async with self._lock:
            hit = key in self._cache
            value = self._cache.get(key)
        logger.debug("%s cache %s: %s", self._name, "hit" if hit else "miss", key)
        return value

    async def set(self, key: str, value: T) -> None:
        """Store a value until its TTL expires."""
        async with self._lock:
            self._cache[key] = value

    async def clear(self) -> None:
        """Drop every cached value."""
        async with self._lock:
            self._cache.clear()

    async def _lock_for_key(self, key: str) -> asyncio.Lock:
        async with self._lock:
            return self._key_locks.setdefault(key, asyncio.Lock())

    async def get_or_set(self, key: str, factory: Callable[[], Awaitable[T]]) -> tuple[T, bool]:
        """Return a cached value or call ``factory`` once and cache its result.

        Returns:
            A tuple of ``(value, cache_hit)``.
        """
        cached = await self.get(key)
        if cached is not None:
            return cached, True

        key_lock = await self._lock_for_key(key)
        try:
            async with key_lock:
                cached = await self.get(key)
                if cached is not None:
                    return cached, True
                value = await factory()
                await self.set(key, value)
                return value, False
        finally:
            async with self._lock:
                if self._key_locks.get(key) is key_lock:
                    del self._key_locks[key]
