"""Redis-backed cache with a simple decorator for async functions."""

import functools
import json
from typing import Callable

from redis.asyncio import Redis

from app.config import settings

_DEFAULT_TTL = 300  # 5 minutes


def _redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def cache_get(key: str) -> str | None:
    redis = _redis()
    try:
        return await redis.get(key)
    finally:
        await redis.aclose()


async def cache_set(key: str, value: str, ttl: int = _DEFAULT_TTL) -> None:
    redis = _redis()
    try:
        await redis.set(key, value, ex=ttl)
    finally:
        await redis.aclose()


def cached(prefix: str, ttl: int = _DEFAULT_TTL) -> Callable:
    """Decorator that caches the JSON-serialisable return value in Redis.

    The cache key is built from ``prefix`` + all positional and keyword
    arguments so that ``get_vdcs(org="acme")`` and ``get_vdcs(org="corp")``
    are cached independently.

    Usage::

        @cached(prefix="vcd:orgs", ttl=300)
        async def get_organizations() -> list[dict]:
            ...
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            # Build a deterministic key from the arguments.
            parts = [prefix]
            parts.extend(str(a) for a in args)
            parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            key = ":".join(parts)

            # Try cache first.
            hit = await cache_get(key)
            if hit is not None:
                return json.loads(hit)

            # Cache miss — call the real function.
            result = await fn(*args, **kwargs)
            await cache_set(key, json.dumps(result, default=str), ttl=ttl)
            return result

        return wrapper

    return decorator
