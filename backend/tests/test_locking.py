"""Tests for app.core.locking — Redis distributed locks with mocked Redis."""

import pytest
from unittest.mock import AsyncMock, patch

from app.core.locking import (
    _lock_key,
    acquire_org_lock,
    release_org_lock,
    get_org_lock_holder,
)


# -----------------------------------------------------------------------
#  _lock_key — normalisation
# -----------------------------------------------------------------------


class TestLockKey:
    def test_simple_name(self):
        assert _lock_key("acme") == "tf:lock:org:acme"

    def test_spaces_slugified(self):
        assert _lock_key("My Org") == "tf:lock:org:my_org"

    def test_special_chars_slugified(self):
        assert _lock_key("Org (prod)") == "tf:lock:org:org_prod"

    def test_different_formats_same_key(self):
        """Two representations of the same org must get the same lock."""
        assert _lock_key("My Org") == _lock_key("my-org")


# -----------------------------------------------------------------------
#  acquire_org_lock
# -----------------------------------------------------------------------


class TestAcquireOrgLock:
    @pytest.mark.asyncio
    async def test_acquire_success(self, patch_redis):
        patch_redis.set = AsyncMock(return_value=True)
        result = await acquire_org_lock("Acme", "op-1")
        assert result is True
        patch_redis.set.assert_called_once()
        # Verify key is slugified
        call_args = patch_redis.set.call_args
        assert call_args[0][0] == "tf:lock:org:acme"
        assert call_args[0][1] == "op-1"

    @pytest.mark.asyncio
    async def test_acquire_already_locked(self, patch_redis):
        patch_redis.set = AsyncMock(return_value=None)
        result = await acquire_org_lock("Acme", "op-2")
        assert result is False

    @pytest.mark.asyncio
    async def test_acquire_uses_nx_and_ex(self, patch_redis):
        patch_redis.set = AsyncMock(return_value=True)
        await acquire_org_lock("Acme", "op-1", ttl=300)
        call_kwargs = patch_redis.set.call_args[1]
        assert call_kwargs["nx"] is True
        assert call_kwargs["ex"] == 300

    @pytest.mark.asyncio
    async def test_acquire_closes_redis(self, patch_redis):
        patch_redis.set = AsyncMock(return_value=True)
        await acquire_org_lock("Acme", "op-1")
        patch_redis.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_acquire_closes_redis_on_error(self, patch_redis):
        patch_redis.set = AsyncMock(side_effect=ConnectionError("boom"))
        with pytest.raises(ConnectionError):
            await acquire_org_lock("Acme", "op-1")
        patch_redis.aclose.assert_called_once()


# -----------------------------------------------------------------------
#  release_org_lock
# -----------------------------------------------------------------------


class TestReleaseOrgLock:
    @pytest.mark.asyncio
    async def test_release_success(self, patch_redis):
        patch_redis.eval = AsyncMock(return_value=1)
        result = await release_org_lock("Acme", "op-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_release_not_owner(self, patch_redis):
        patch_redis.eval = AsyncMock(return_value=0)
        result = await release_org_lock("Acme", "op-wrong")
        assert result is False

    @pytest.mark.asyncio
    async def test_release_uses_lua_script(self, patch_redis):
        patch_redis.eval = AsyncMock(return_value=1)
        await release_org_lock("Acme", "op-1")
        call_args = patch_redis.eval.call_args[0]
        # First arg is the Lua script
        assert "GET" in call_args[0]
        assert "DEL" in call_args[0]
        # Key is slugified
        assert call_args[2] == "tf:lock:org:acme"
        # Value is the operation_id
        assert call_args[3] == "op-1"

    @pytest.mark.asyncio
    async def test_release_closes_redis(self, patch_redis):
        patch_redis.eval = AsyncMock(return_value=1)
        await release_org_lock("Acme", "op-1")
        patch_redis.aclose.assert_called_once()


# -----------------------------------------------------------------------
#  get_org_lock_holder
# -----------------------------------------------------------------------


class TestGetOrgLockHolder:
    @pytest.mark.asyncio
    async def test_returns_holder(self, patch_redis):
        patch_redis.get = AsyncMock(return_value="op-42")
        result = await get_org_lock_holder("Acme")
        assert result == "op-42"

    @pytest.mark.asyncio
    async def test_returns_none_when_unlocked(self, patch_redis):
        patch_redis.get = AsyncMock(return_value=None)
        result = await get_org_lock_holder("Acme")
        assert result is None

    @pytest.mark.asyncio
    async def test_uses_slugified_key(self, patch_redis):
        patch_redis.get = AsyncMock(return_value=None)
        await get_org_lock_holder("My Org (prod)")
        patch_redis.get.assert_called_once_with("tf:lock:org:my_org_prod")

    @pytest.mark.asyncio
    async def test_closes_redis(self, patch_redis):
        patch_redis.get = AsyncMock(return_value=None)
        await get_org_lock_holder("Acme")
        patch_redis.aclose.assert_called_once()
