"""Shared fixtures for backend tests."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_redis():
    """Return a mock Redis client with common async methods stubbed."""
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    redis.eval = AsyncMock(return_value=1)
    redis.publish = AsyncMock()
    redis.aclose = AsyncMock()
    return redis


@pytest.fixture
def patch_redis(mock_redis):
    """Patch the locking module's _redis() to return the mock."""
    with patch("app.core.locking._redis", return_value=mock_redis):
        yield mock_redis
