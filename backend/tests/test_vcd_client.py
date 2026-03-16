"""Tests for VCDClient methods — pvdc name→ID resolution and network pools."""

from unittest.mock import AsyncMock, patch

import pytest

from app.integrations.vcd_client import VCDClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_PVDCS = [
    {"name": "pvdc-01", "id": "urn:vcloud:providervdc:aaaa-bbbb", "is_enabled": True},
    {"name": "pvdc-02", "id": "urn:vcloud:providervdc:cccc-dddd", "is_enabled": True},
]

FAKE_STORAGE_POLICIES = [
    {"name": "gold-ssd", "id": "urn:vcloud:vdcstorageProfile:1111", "isEnabled": True},
    {"name": "silver-hdd", "id": "urn:vcloud:vdcstorageProfile:2222", "isEnabled": False},
]

FAKE_NETWORK_POOL_QUERY = {
    "record": [
        {
            "name": "geneve-pool-01",
            "href": "https://vcd.test/api/admin/extension/networkPool/aaaa",
            "networkPoolType": 5,
            "description": "Main GENEVE pool",
        },
    ]
}


@pytest.fixture
def client():
    """Create a VCDClient instance without connecting to VCD."""
    with patch.object(VCDClient, "__init__", lambda self: None):
        c = VCDClient()
        c._base = "https://vcd.test"
        c._api_version = "39.0"
        c._api_token = "fake"
        c._bearer_token = "fake-bearer"
        c._token_expires_at = 9999999999
        return c


# ---------------------------------------------------------------------------
# Storage Profiles — name→ID resolution
# ---------------------------------------------------------------------------


class TestStorageProfiles:
    async def test_resolves_pvdc_name_to_id(self, client):
        """get_storage_profiles should resolve pvdc name to ID for the filter."""
        client.get_provider_vdcs = AsyncMock(return_value=FAKE_PVDCS)
        client._get_paginated = AsyncMock(return_value=FAKE_STORAGE_POLICIES)

        result = await client.get_storage_profiles.__wrapped__(client, pvdc="pvdc-01")

        # Verify _get_paginated was called with the resolved ID, not the name
        call_args = client._get_paginated.call_args
        assert call_args[0][0] == "/cloudapi/1.0.0/pvdcStoragePolicies"
        filter_param = call_args[1].get("params") or call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["params"]
        assert "urn:vcloud:providervdc:aaaa-bbbb" in filter_param["filter"]
        assert "providerVdcRef.id==" in filter_param["filter"]

        assert len(result) == 2
        assert result[0]["name"] == "gold-ssd"

    async def test_unknown_pvdc_returns_empty(self, client):
        """get_storage_profiles should return [] for unknown pvdc name."""
        client.get_provider_vdcs = AsyncMock(return_value=FAKE_PVDCS)

        result = await client.get_storage_profiles.__wrapped__(client, pvdc="nonexistent")

        assert result == []
        # _get_paginated should NOT be called
        assert not hasattr(client, "_get_paginated") or not getattr(
            client._get_paginated, "called", False
        )

    async def test_no_pvdc_fetches_all(self, client):
        """get_storage_profiles without pvdc should fetch all profiles."""
        client._get_paginated = AsyncMock(return_value=FAKE_STORAGE_POLICIES)

        result = await client.get_storage_profiles.__wrapped__(client, pvdc=None)

        call_args = client._get_paginated.call_args
        params = call_args[1].get("params") or (call_args[0][1] if len(call_args[0]) > 1 else {})
        assert "filter" not in params
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Network Pools
# ---------------------------------------------------------------------------


class TestNetworkPools:
    async def test_returns_pools(self, client):
        """get_network_pools should return formatted pool list from query API."""
        client._get = AsyncMock(return_value=FAKE_NETWORK_POOL_QUERY)

        result = await client.get_network_pools.__wrapped__(client, pvdc=None)

        assert len(result) == 1
        assert result[0]["name"] == "geneve-pool-01"
        assert result[0]["poolType"] == "5"
        assert result[0]["description"] == "Main GENEVE pool"

        # Verify query API was called with correct params
        call_args = client._get.call_args
        assert call_args[0][0] == "/api/query"
        params = call_args[1].get("params") or call_args[0][1]
        assert params["type"] == "networkPool"
        assert params["format"] == "records"

    async def test_empty_response_returns_empty(self, client):
        """get_network_pools with no records returns []."""
        client._get = AsyncMock(return_value={"record": []})

        result = await client.get_network_pools.__wrapped__(client, pvdc=None)

        assert result == []

    async def test_no_record_key_returns_empty(self, client):
        """get_network_pools handles response without 'record' key."""
        client._get = AsyncMock(return_value={})

        result = await client.get_network_pools.__wrapped__(client, pvdc=None)

        assert result == []
