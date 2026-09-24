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

        call_args = client._get_paginated.call_args_list[0]
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


# ---------------------------------------------------------------------------
# Edge Gateways owned by a VDC group (DCG)
#
# An edge scoped to a data center group has the group as its owner and no
# orgVdc, so the orgVdc.id filter never returns it. The picker has to find
# the groups the VDC takes part in and ask for their edges too.
# ---------------------------------------------------------------------------

VDC_ID = "urn:vcloud:vdc:1111-2222"
GROUP_ID = "urn:vcloud:vdcGroup:9999"

FAKE_VDC_GROUPS = [
    {
        "id": GROUP_ID,
        "name": "dcg-client",
        "participatingOrgVdcs": [
            {"vdcRef": {"id": VDC_ID, "name": "vdc-a"}},
            {"vdcRef": {"id": "urn:vcloud:vdc:3333", "name": "vdc-b"}},
        ],
    },
    {
        "id": "urn:vcloud:vdcGroup:other",
        "name": "someone-else",
        "participatingOrgVdcs": [{"vdcRef": {"id": "urn:vcloud:vdc:4444"}}],
    },
]


def _router(responses: dict):
    """Answer _get_paginated by path and filter, like VCD would."""

    async def fake(path, params=None, page_size=128):
        key = (path, (params or {}).get("filter"))
        return responses.get(key, [])

    return fake


class TestEdgeGatewaysInVdcGroup:
    async def test_group_edge_is_listed_for_member_vdc(self, client):
        client._get_paginated = _router({
            ("/cloudapi/1.0.0/edgeGateways", f"(orgVdc.id=={VDC_ID})"): [],
            ("/cloudapi/1.0.0/vdcGroups", None): FAKE_VDC_GROUPS,
            ("/cloudapi/1.0.0/edgeGateways", f"(ownerRef.id=={GROUP_ID})"): [
                {"id": "urn:vcloud:gateway:dcg", "name": "edge-dcg"},
            ],
        })

        result = await client.get_edge_gateways_by_vdc_id.__wrapped__(
            client, vdc_id=VDC_ID
        )

        assert [e["id"] for e in result] == ["urn:vcloud:gateway:dcg"]
        assert result[0]["vdc_group"] == "dcg-client"

    async def test_vdc_edges_and_group_edges_together(self, client):
        client._get_paginated = _router({
            ("/cloudapi/1.0.0/edgeGateways", f"(orgVdc.id=={VDC_ID})"): [
                {"id": "urn:vcloud:gateway:own", "name": "edge-own"},
            ],
            ("/cloudapi/1.0.0/vdcGroups", None): FAKE_VDC_GROUPS,
            ("/cloudapi/1.0.0/edgeGateways", f"(ownerRef.id=={GROUP_ID})"): [
                {"id": "urn:vcloud:gateway:dcg", "name": "edge-dcg"},
            ],
        })

        result = await client.get_edge_gateways_by_vdc_id.__wrapped__(
            client, vdc_id=VDC_ID
        )

        by_id = {e["id"]: e for e in result}
        assert set(by_id) == {"urn:vcloud:gateway:own", "urn:vcloud:gateway:dcg"}
        assert by_id["urn:vcloud:gateway:own"]["vdc_group"] is None

    async def test_groups_the_vdc_is_not_in_are_not_queried(self, client):
        calls = []
        inner = _router({("/cloudapi/1.0.0/vdcGroups", None): FAKE_VDC_GROUPS})

        async def spy(path, params=None, page_size=128):
            calls.append((path, (params or {}).get("filter")))
            return await inner(path, params, page_size)

        client._get_paginated = spy

        await client.get_edge_gateways_by_vdc_id.__wrapped__(client, vdc_id=VDC_ID)

        assert (
            "/cloudapi/1.0.0/edgeGateways",
            "(ownerRef.id==urn:vcloud:vdcGroup:other)",
        ) not in calls

    async def test_same_edge_twice_is_listed_once(self, client):
        edge = {"id": "urn:vcloud:gateway:dcg", "name": "edge-dcg"}
        client._get_paginated = _router({
            ("/cloudapi/1.0.0/edgeGateways", f"(orgVdc.id=={VDC_ID})"): [edge],
            ("/cloudapi/1.0.0/vdcGroups", None): FAKE_VDC_GROUPS,
            ("/cloudapi/1.0.0/edgeGateways", f"(ownerRef.id=={GROUP_ID})"): [edge],
        })

        result = await client.get_edge_gateways_by_vdc_id.__wrapped__(
            client, vdc_id=VDC_ID
        )

        assert len(result) == 1

    async def test_vdc_groups_failure_keeps_vdc_edges(self, client):
        async def fake(path, params=None, page_size=128):
            if path == "/cloudapi/1.0.0/vdcGroups":
                raise RuntimeError("403")
            return [{"id": "urn:vcloud:gateway:own", "name": "edge-own"}]

        client._get_paginated = fake

        result = await client.get_edge_gateways_by_vdc_id.__wrapped__(
            client, vdc_id=VDC_ID
        )

        assert [e["id"] for e in result] == ["urn:vcloud:gateway:own"]
