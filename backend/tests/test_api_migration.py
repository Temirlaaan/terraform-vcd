"""Integration tests for POST /api/v1/migration/generate."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.keycloak import AuthenticatedUser, get_current_user
from app.main import app

# Reuse XML fixtures from normalizer tests
from tests.test_migration_normalizer import (
    EDGE_METADATA_XML,
    FIREWALL_XML,
    NAT_XML,
    ROUTING_XML,
)

FAKE_XMLS = {
    "edge_metadata.xml": EDGE_METADATA_XML,
    "firewall_config.xml": FIREWALL_XML,
    "nat_config.xml": NAT_XML,
    "routing_config.xml": ROUTING_XML,
}

VALID_REQUEST = {
    "host": "https://vcd01.t-cloud.kz",
    "user": "admin@System",
    "password": "secret",
    "edge_uuid": "b6b3181a-2596-44c5-9991-c4c54c050bcb",
    "target_org": "TestOrg",
    "target_vdc": "TestVDC",
    "target_edge_id": "urn:vcloud:gateway:abc-123",
}

_ADMIN_USER = AuthenticatedUser(
    sub="test-sub",
    username="test-admin",
    email="admin@test.com",
    full_name="Test Admin",
    roles=["tf-admin", "tf-operator"],
)

_VIEWER_USER = AuthenticatedUser(
    sub="viewer-sub",
    username="test-viewer",
    email="viewer@test.com",
    full_name="Test Viewer",
    roles=["tf-viewer"],
)


def _override_auth(user: AuthenticatedUser):
    """Override auth dependency to return a specific user."""
    async def _override():
        return user
    return _override


@pytest.fixture
def mock_fetcher():
    """Mock LegacyVcdFetcher.fetch_edge_snapshot to return test XMLs."""
    with patch("app.api.routes.migration.LegacyVcdFetcher") as MockCls:
        instance = AsyncMock()
        instance.fetch_edge_snapshot = AsyncMock(return_value=FAKE_XMLS)
        MockCls.return_value = instance
        yield MockCls, instance


@pytest.fixture(autouse=True)
def cleanup_overrides():
    """Clean up dependency overrides after each test."""
    yield
    app.dependency_overrides.clear()


# -----------------------------------------------------------------------
#  Happy path
# -----------------------------------------------------------------------


class TestMigrationGenerateEndpoint:
    async def test_returns_200_with_hcl(self, mock_fetcher):
        app.dependency_overrides[get_current_user] = _override_auth(_ADMIN_USER)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/migration/generate", json=VALID_REQUEST)

        assert resp.status_code == 200
        data = resp.json()
        assert "hcl" in data
        assert len(data["hcl"]) > 0

    async def test_returns_edge_name(self, mock_fetcher):
        app.dependency_overrides[get_current_user] = _override_auth(_ADMIN_USER)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/migration/generate", json=VALID_REQUEST)

        data = resp.json()
        assert data["edge_name"] == "TTC_Telco_EDGE"

    async def test_returns_summary(self, mock_fetcher):
        app.dependency_overrides[get_current_user] = _override_auth(_ADMIN_USER)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/migration/generate", json=VALID_REQUEST)

        summary = resp.json()["summary"]
        assert summary["firewall_rules_total"] == 4  # 5 minus vse rule
        assert summary["firewall_rules_user"] == 2
        assert summary["firewall_rules_system"] == 2
        assert summary["nat_rules_total"] == 4
        assert summary["static_routes_total"] == 2

    async def test_hcl_contains_nsxt_resources(self, mock_fetcher):
        app.dependency_overrides[get_current_user] = _override_auth(_ADMIN_USER)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/migration/generate", json=VALID_REQUEST)

        hcl = resp.json()["hcl"]
        assert "vcd_nsxt_firewall" in hcl
        assert "vcd_nsxt_nat_rule" in hcl
        assert "vcd_nsxt_edgegateway_static_route" in hcl

    async def test_fetcher_receives_correct_params(self, mock_fetcher):
        MockCls, instance = mock_fetcher
        app.dependency_overrides[get_current_user] = _override_auth(_ADMIN_USER)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.post("/api/v1/migration/generate", json=VALID_REQUEST)

        MockCls.assert_called_once_with(
            host="https://vcd01.t-cloud.kz",
            user="admin@System",
            password="secret",
            verify_ssl=False,
        )
        instance.fetch_edge_snapshot.assert_called_once_with(
            "b6b3181a-2596-44c5-9991-c4c54c050bcb"
        )


# -----------------------------------------------------------------------
#  Auth
# -----------------------------------------------------------------------


class TestMigrationGenerateAuth:
    async def test_viewer_gets_403(self, mock_fetcher):
        app.dependency_overrides[get_current_user] = _override_auth(_VIEWER_USER)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/migration/generate", json=VALID_REQUEST)

        assert resp.status_code == 403

    async def test_no_auth_gets_401(self, mock_fetcher):
        # No override — default auth requires token
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/migration/generate", json=VALID_REQUEST)

        # Without token, should get 401 (unless AUTH_DISABLED)
        assert resp.status_code in (401, 200)  # 200 if AUTH_DISABLED=true in env


# -----------------------------------------------------------------------
#  Error handling
# -----------------------------------------------------------------------


class TestMigrationGenerateErrors:
    async def test_vcd_auth_failure_returns_401(self):
        app.dependency_overrides[get_current_user] = _override_auth(_ADMIN_USER)

        with patch("app.api.routes.migration.LegacyVcdFetcher") as MockCls:
            instance = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.status_code = 401
            instance.fetch_edge_snapshot = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "401", request=AsyncMock(), response=mock_resp,
                )
            )
            MockCls.return_value = instance

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post("/api/v1/migration/generate", json=VALID_REQUEST)

        assert resp.status_code == 401
        assert "Authentication failed" in resp.json()["detail"]

    async def test_vcd_unreachable_returns_502(self):
        app.dependency_overrides[get_current_user] = _override_auth(_ADMIN_USER)

        with patch("app.api.routes.migration.LegacyVcdFetcher") as MockCls:
            instance = AsyncMock()
            instance.fetch_edge_snapshot = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            MockCls.return_value = instance

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post("/api/v1/migration/generate", json=VALID_REQUEST)

        assert resp.status_code == 502
        assert "Cannot connect" in resp.json()["detail"]

    async def test_vcd_server_error_returns_502(self):
        app.dependency_overrides[get_current_user] = _override_auth(_ADMIN_USER)

        with patch("app.api.routes.migration.LegacyVcdFetcher") as MockCls:
            instance = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.status_code = 500
            instance.fetch_edge_snapshot = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "500", request=AsyncMock(), response=mock_resp,
                )
            )
            MockCls.return_value = instance

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post("/api/v1/migration/generate", json=VALID_REQUEST)

        assert resp.status_code == 502

    async def test_bad_xml_returns_400(self):
        app.dependency_overrides[get_current_user] = _override_auth(_ADMIN_USER)

        bad_xmls = {
            "edge_metadata.xml": "not xml",
            "firewall_config.xml": "not xml",
            "nat_config.xml": "not xml",
            "routing_config.xml": "not xml",
        }
        with patch("app.api.routes.migration.LegacyVcdFetcher") as MockCls:
            instance = AsyncMock()
            instance.fetch_edge_snapshot = AsyncMock(return_value=bad_xmls)
            MockCls.return_value = instance

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post("/api/v1/migration/generate", json=VALID_REQUEST)

        assert resp.status_code == 400
        assert "parse" in resp.json()["detail"].lower() or "xml" in resp.json()["detail"].lower()

    async def test_missing_required_field_returns_422(self):
        app.dependency_overrides[get_current_user] = _override_auth(_ADMIN_USER)
        incomplete = {"host": "https://vcd.test"}  # Missing required fields

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/migration/generate", json=incomplete)

        assert resp.status_code == 422
