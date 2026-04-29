"""Short-lived Redis handle for legacy-VCD API tokens (H3-FE).

The legacy-VCD migration flow needs a System-Administrator scoped refresh
token. Storing that token in browser ``sessionStorage`` puts a high-power
credential one XSS or compromised npm transitive dependency away from
exfiltration.

This module replaces direct token storage with a backend-scoped opaque
handle (UUID v4) backed by Redis with a hard TTL. The browser only ever
holds the handle; the real token never leaves the backend after it is
submitted once at the start of a migration session.

Lifecycle:
  1. FE prompts admin for legacy-VCD ``host`` + ``api_token``.
  2. FE calls ``POST /api/v1/migration/auth-handle`` once.
  3. Backend stores ``(host, token)`` under a UUID, returns the UUID.
  4. FE stashes the UUID in sessionStorage, sends it in subsequent
     migration calls in place of ``api_token``.
  5. Backend resolves UUID -> (host, token), uses token for VCD fetch.
  6. After ``HANDLE_TTL_SECONDS`` Redis evicts the key. FE prompts again.

Trade-offs:
  - Handle in browser is still bearer-equivalent within its scope, but
    the scope is short-lived (10 minutes default), backend-controlled,
    revocable by ``invalidate``, and useless without our backend.
  - One round-trip extra per migration session vs prior direct flow.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis

from app.config import settings

logger = logging.getLogger(__name__)


HANDLE_TTL_SECONDS = 600  # 10 minutes
_REDIS_KEY_PREFIX = "vcd_handle:"


@dataclass(frozen=True)
class VcdHandlePayload:
    host: str
    api_token: str


def _redis_key(handle: str) -> str:
    return f"{_REDIS_KEY_PREFIX}{handle}"


async def store(host: str, api_token: str) -> str:
    """Persist ``(host, api_token)`` under a fresh handle. Return the handle."""
    handle = str(uuid.uuid4())
    payload = json.dumps({"host": host, "api_token": api_token})
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.set(_redis_key(handle), payload, ex=HANDLE_TTL_SECONDS)
    finally:
        await redis.aclose()
    return handle


async def resolve(handle: str) -> VcdHandlePayload | None:
    """Return the stored payload, or ``None`` if missing / expired."""
    if not handle:
        return None
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        raw = await redis.get(_redis_key(handle))
    finally:
        await redis.aclose()
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("vcd_handle: malformed payload for handle=%s", handle)
        return None
    return VcdHandlePayload(host=data.get("host", ""), api_token=data.get("api_token", ""))


async def invalidate(handle: str) -> None:
    """Drop a handle early (e.g. on logout or explicit admin revoke)."""
    if not handle:
        return
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.delete(_redis_key(handle))
    finally:
        await redis.aclose()
