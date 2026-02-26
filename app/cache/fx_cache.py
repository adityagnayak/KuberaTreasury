"""
NexusTreasury — Redis FX Rate Cache Wrapper (Upstash-compatible)
Falls back to an in-memory thread-safe dict when Redis is unavailable.
"""

from __future__ import annotations

import threading
from decimal import Decimal
from typing import Optional


class InMemoryRedis:
    """Thread-safe in-memory fallback that mirrors the Redis API."""

    def __init__(self) -> None:
        self._store: dict = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            return self._store.get(key)

    def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        with self._lock:
            self._store[key] = value

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def exists(self, key: str) -> bool:
        with self._lock:
            return key in self._store

    def hset(self, name: str, key: str, value: str) -> None:
        with self._lock:
            if name not in self._store:
                self._store[name] = {}
            self._store[name][key] = value

    def hget(self, name: str, key: str) -> Optional[str]:
        with self._lock:
            return self._store.get(name, {}).get(key)

    def hgetall(self, name: str) -> dict:
        with self._lock:
            return dict(self._store.get(name, {}))

    def flush(self) -> None:
        with self._lock:
            self._store.clear()


def build_redis_client(redis_url: Optional[str] = None):
    """
    Build a Redis client from the given URL.
    Returns an InMemoryRedis if the URL is absent or redis is not installed.

    For production with Upstash: set REDIS_URL=rediss://...@...upstash.io:6379
    """
    if not redis_url or redis_url == "redis://localhost:6379/0":
        return InMemoryRedis()

    try:
        import redis as redis_lib  # type: ignore
        client = redis_lib.from_url(redis_url, decode_responses=True)
        client.ping()   # verify connectivity
        return client
    except Exception:
        return InMemoryRedis()


# Module-level singleton — shared across all requests
_redis_instance: Optional[object] = None


def get_redis_client():
    """
    FastAPI dependency: returns the shared Redis client.
    Initialises on first call using REDIS_URL from settings.
    """
    global _redis_instance
    if _redis_instance is None:
        from app.config import get_settings
        settings = get_settings()
        _redis_instance = build_redis_client(settings.REDIS_URL)
    return _redis_instance


class FXRateCacheRedis:
    """
    Decimal-safe FX rate cache backed by Redis (or InMemoryRedis fallback).
    Key format: hash "fx_rates" → field "{FROM}:{TO}" → str(rate)
    """

    HASH_KEY = "fx_rates"

    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client or get_redis_client()

    def set_rate(self, from_ccy: str, to_ccy: str, rate: Decimal) -> None:
        if not isinstance(rate, Decimal):
            raise TypeError(f"FX rate must be Decimal, got {type(rate)}")
        self._redis.hset(self.HASH_KEY, f"{from_ccy}:{to_ccy}", str(rate))
        if rate != Decimal("0"):
            self._redis.hset(
                self.HASH_KEY, f"{to_ccy}:{from_ccy}", str(Decimal("1") / rate)
            )

    def get_rate(self, from_ccy: str, to_ccy: str) -> Decimal:
        if from_ccy == to_ccy:
            return Decimal("1")
        raw = self._redis.hget(self.HASH_KEY, f"{from_ccy}:{to_ccy}")
        if raw is None:
            raise ValueError(f"FX rate not found: {from_ccy} -> {to_ccy}")
        return Decimal(raw)

    def convert(self, amount: Decimal, from_ccy: str, to_ccy: str) -> Decimal:
        if not isinstance(amount, Decimal):
            raise TypeError(f"Amount must be Decimal, got {type(amount)}")
        return amount * self.get_rate(from_ccy, to_ccy)

    def flush(self) -> None:
        self._redis.delete(self.HASH_KEY)
