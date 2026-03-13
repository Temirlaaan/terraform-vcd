from redis.asyncio import Redis

from app.config import settings
from app.core.hcl_generator import _slug

# Default lock TTL — auto-releases if the holder crashes.
_DEFAULT_LOCK_TTL_SECONDS = 600  # 10 minutes
_LOCK_PREFIX = "tf:lock:org:"


def _redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def _lock_key(org_name: str) -> str:
    """Build a normalised Redis lock key for an organisation.

    Uses _slug() so the key matches the workspace directory name and
    prevents two differently-formatted org names from getting separate locks.
    """
    return f"{_LOCK_PREFIX}{_slug(org_name)}"


async def acquire_org_lock(
    org_name: str,
    operation_id: str,
    ttl: int = _DEFAULT_LOCK_TTL_SECONDS,
) -> bool:
    """Try to acquire a per-Organisation lock in Redis.

    Returns True if the lock was acquired, False if another operation
    already holds it.

    The lock value is the ``operation_id`` so we can inspect who holds it.
    """
    redis = _redis()
    try:
        acquired = await redis.set(
            _lock_key(org_name),
            operation_id,
            nx=True,
            ex=ttl,
        )
        return acquired is not None
    finally:
        await redis.aclose()


async def release_org_lock(org_name: str, operation_id: str) -> bool:
    """Release the lock only if we still own it (compare-and-delete).

    Returns True if the lock was released, False if it was already gone
    or owned by another operation.
    """
    script = """
    if redis.call("GET", KEYS[1]) == ARGV[1] then
        return redis.call("DEL", KEYS[1])
    else
        return 0
    end
    """
    redis = _redis()
    try:
        result = await redis.eval(script, 1, _lock_key(org_name), operation_id)
        return result == 1
    finally:
        await redis.aclose()


async def get_org_lock_holder(org_name: str) -> str | None:
    """Return the operation_id that currently holds the lock, or None."""
    redis = _redis()
    try:
        return await redis.get(_lock_key(org_name))
    finally:
        await redis.aclose()
