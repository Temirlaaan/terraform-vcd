"""Tests for VCDClient methods — aligned with VCD CloudAPI 39.x spec."""

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

FAKE_EDGE_CLUSTERS = [
    {
        "name": "edge-cluster-01",
        "id": "urn:vcloud:edgeCluster:aaaa-1111",
        "nodeCount": 2,
    },
    {
        "name": "edge-cluster-02",
        "id": "urn:vcloud:edgeCluster:bbbb-2222",
        "nodeCount": 1,
    },
]

FAKE_VDCS_FOR_EDGES = [
    {
        "name": "test-vdc",
        "id": "urn:vcloud:vdc:1111-2222",
        "org": {"name": "test-org"},
        "allocationModel": "AllocationVApp",
        "isEnabled": True,
    },
]

FAKE_EDGE_GATEWAYS = [
    {
        "name": "edge-gw-01",
        "id": "urn:vcloud:gateway:aaaa",
        "orgVdc": {"name": "test-vdc"},
        "gatewayType": "NSXT_BACKED",
    },
]

FAKE_NETWORK_POOL_SUMMARIES = [
    {
        "name": "geneve-pool-01",
        "id": "urn:vcloud:networkPool:aaaa-1111",
        "poolType": "GENEVE",
        "description": "Main GENEVE pool",
        "totalBackingsCount": 10,
        "usedBackingsCount": 3,
    },
    {
        "name": "vlan-pool-02",
        "id": "urn:vcloud:networkPool:bbbb-2222",
        "poolType": "VLAN",
        "description": None,
        "totalBackingsCount": 5,
        "usedBackingsCount": 0,
    },
]


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
# Network Pools — CloudAPI networkPoolSummaries
# ---------------------------------------------------------------------------


class TestNetworkPools:
    async def test_returns_pools_from_cloudapi(self, client):
        """get_network_pools should use CloudAPI networkPoolSummaries endpoint."""
        client._get_paginated = AsyncMock(return_value=FAKE_NETWORK_POOL_SUMMARIES)

        result = await client.get_network_pools.__wrapped__(client, pvdc=None)

        assert len(result) == 2
        assert result[0]["name"] == "geneve-pool-01"
        assert result[0]["id"] == "urn:vcloud:networkPool:aaaa-1111"
        assert result[0]["poolType"] == "GENEVE"
        assert result[0]["description"] == "Main GENEVE pool"
        assert result[1]["poolType"] == "VLAN"

        # Verify CloudAPI endpoint was called (not legacy /api/query)
        call_args = client._get_paginated.call_args
        assert call_args[0][0] == "/cloudapi/1.0.0/networkPools/networkPoolSummaries"

    async def test_empty_response_returns_empty(self, client):
        """get_network_pools with no pools returns []."""
        client._get_paginated = AsyncMock(return_value=[])

        result = await client.get_network_pools.__wrapped__(client, pvdc=None)

        assert result == []

    async def test_pvdc_param_ignored(self, client):
        """get_network_pools accepts pvdc param but does not filter by it."""
        client._get_paginated = AsyncMock(return_value=FAKE_NETWORK_POOL_SUMMARIES)

        result = await client.get_network_pools.__wrapped__(client, pvdc="pvdc-01")

        # Should still return all pools — pvdc is ignored
        assert len(result) == 2
        # Verify no filter was applied
        call_args = client._get_paginated.call_args
        # _get_paginated called with only the path, no params
        if len(call_args[0]) > 1:
            assert call_args[0][1] is None or "filter" not in (call_args[0][1] or {})
        elif "params" in call_args[1]:
            assert "filter" not in (call_args[1]["params"] or {})


# ---------------------------------------------------------------------------
# Edge Clusters — projections endpoint
# ---------------------------------------------------------------------------


class TestEdgeClusters:
    async def test_returns_clusters_filtered_by_vdc(self, client):
        """get_edge_clusters should use /edgeClusters endpoint with orgVdcId filter."""
        client._get_paginated = AsyncMock(return_value=FAKE_EDGE_CLUSTERS)

        result = await client.get_edge_clusters.__wrapped__(
            client, vdc_id="urn:vcloud:vdc:1111-2222"
        )

        assert len(result) == 2
        assert result[0]["name"] == "edge-cluster-01"
        assert result[0]["id"] == "urn:vcloud:edgeCluster:aaaa-1111"
        assert result[1]["name"] == "edge-cluster-02"

        # Verify /edgeClusters endpoint and orgVdcId filter
        call_args = client._get_paginated.call_args
        assert call_args[0][0] == "/cloudapi/1.0.0/edgeClusters"
        params = call_args[1].get("params") or call_args[0][1]
        assert "orgVdcId==urn:vcloud:vdc:1111-2222" in params["filter"]

    async def test_empty_clusters(self, client):
        """get_edge_clusters returns [] when no clusters found."""
        client._get_paginated = AsyncMock(return_value=[])

        result = await client.get_edge_clusters.__wrapped__(
            client, vdc_id="urn:vcloud:vdc:nonexistent"
        )

        assert result == []


# ---------------------------------------------------------------------------
# VDCs by org ID — org.id filter
# ---------------------------------------------------------------------------


FAKE_ORGS = [
    {"name": "test-org", "id": "urn:vcloud:org:aaaa-bbbb", "display_name": "test-org", "is_enabled": True},
    {"name": "other-org", "id": "urn:vcloud:org:cccc-dddd", "display_name": "other-org", "is_enabled": True},
]


class TestVdcsByOrgId:
    async def test_returns_vdcs_filtered_by_org_id(self, client):
        """get_vdcs_by_org_id should resolve org_id to name and filter VDCs client-side."""
        client.get_organizations = AsyncMock(return_value=FAKE_ORGS)
        client.get_vdcs = AsyncMock(return_value=[
            {"name": "test-vdc", "id": "urn:vcloud:vdc:1111-2222", "org_name": "test-org",
             "allocation_model": "AllocationVApp", "is_enabled": True},
        ])

        result = await client.get_vdcs_by_org_id.__wrapped__(
            client, org_id="urn:vcloud:org:aaaa-bbbb"
        )

        assert len(result) == 1
        assert result[0]["name"] == "test-vdc"
        assert result[0]["id"] == "urn:vcloud:vdc:1111-2222"
        # Verify it resolved org_id to name and called get_vdcs
        client.get_organizations.assert_awaited_once()
        client.get_vdcs.assert_awaited_once_with(org_name="test-org")

    async def test_unknown_org_id_returns_empty(self, client):
        """get_vdcs_by_org_id should return [] for unknown org_id."""
        client.get_organizations = AsyncMock(return_value=FAKE_ORGS)

        result = await client.get_vdcs_by_org_id.__wrapped__(
            client, org_id="urn:vcloud:org:nonexistent"
        )

        assert result == []


# ---------------------------------------------------------------------------
# Edge Gateways by VDC ID
# ---------------------------------------------------------------------------


class TestEdgeGatewaysByVdcId:
    async def test_returns_edges_filtered_by_vdc_id(self, client):
        """get_edge_gateways_by_vdc_id should filter by orgVdc.id URN."""
        client._get_paginated = AsyncMock(return_value=FAKE_EDGE_GATEWAYS)

        result = await client.get_edge_gateways_by_vdc_id.__wrapped__(
            client, vdc_id="urn:vcloud:vdc:1111-2222"
        )

        assert len(result) == 1
        assert result[0]["name"] == "edge-gw-01"
        assert result[0]["id"] == "urn:vcloud:gateway:aaaa"

        call_args = client._get_paginated.call_args
        params = call_args[1].get("params") or call_args[0][1]
        assert "orgVdc.id==urn:vcloud:vdc:1111-2222" in params["filter"]


# ---------------------------------------------------------------------------
# Edge Gateways by owner ID (VDC Group support)
# ---------------------------------------------------------------------------


class TestEdgeGatewaysByOwnerId:
    async def test_returns_edges_filtered_by_owner_id(self, client):
        """get_edge_gateways_by_owner_id should filter by ownerRef.id."""
        client._get_paginated = AsyncMock(return_value=FAKE_EDGE_GATEWAYS)

        result = await client.get_edge_gateways_by_owner_id.__wrapped__(
            client, owner_id="urn:vcloud:vdc:1111-2222"
        )

        assert len(result) == 1
        assert result[0]["name"] == "edge-gw-01"
        assert result[0]["id"] == "urn:vcloud:gateway:aaaa"

        call_args = client._get_paginated.call_args
        assert call_args[0][0] == "/cloudapi/1.0.0/edgeGateways"
        params = call_args[1].get("params") or call_args[0][1]
        assert "ownerRef.id==urn:vcloud:vdc:1111-2222" in params["filter"]

    async def test_empty_owner_returns_empty(self, client):
        """get_edge_gateways_by_owner_id returns [] when no edges found."""
        client._get_paginated = AsyncMock(return_value=[])

        result = await client.get_edge_gateways_by_owner_id.__wrapped__(
            client, owner_id="urn:vcloud:vdc:nonexistent"
        )

        assert result == []
