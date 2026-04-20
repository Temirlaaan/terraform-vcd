"""Integration tests for GET /api/v1/migration/target-check."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.keycloak import AuthenticatedUser, get_current_user
from app.main import app

_EDGE_ID = "urn:vcloud:gateway:abc-123"

_ADMIN_USER = AuthenticatedUser(
    sub="test-sub",
    username="test-admin",
    email="admin@test.com",
    full_name="Test Admin",
    roles=["tf-admin"],
)

_VIEWER_USER = AuthenticatedUser(
    sub="viewer-sub",
    username="test-viewer",
    email="viewer@test.com",
    full_name="Test Viewer",
    roles=["tf-viewer"],
)

_NO_ROLE_USER = AuthenticatedUser(
    sub="no-role-sub",
    username="test-no-role",
    email="no-role@test.com",
    full_name="Test NoRole",
    roles=[],
)


def _override_auth(user: AuthenticatedUser):
    async def _override():
        return user

    return _override


@pytest.fixture(autouse=True)
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def mock_vcd_counts():
    """Patch the vcd_client count methods on the migration router."""
    with (
        patch(
            "app.api.routes.migration.vcd_client.count_ip_sets_on_edge",
            new=AsyncMock(return_value=3),
        ) as ip_sets,
        patch(
            "app.api.routes.migration.vcd_client.count_nat_rules_on_edge",
            new=AsyncMock(return_value=5),
        ) as nat,
        patch(
            "app.api.routes.migration.vcd_client.count_firewall_rules_on_edge",
            new=AsyncMock(return_value=7),
        ) as fw,
        patch(
            "app.api.routes.migration.vcd_client.count_static_routes_on_edge",
            new=AsyncMock(return_value=2),
        ) as routes,
    ):
        yield {
            "ip_sets": ip_sets,
            "nat": nat,
            "fw": fw,
            "routes": routes,
        }


@pytest.mark.asyncio
async def test_target_check_returns_counts(mock_vcd_counts):
    app.dependency_overrides[get_current_user] = _override_auth(_ADMIN_USER)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/v1/migration/target-check",
            params={"edge_id": _EDGE_ID},
        )

    assert resp.status_code == 200
    assert resp.json() == {
        "ip_sets_count": 3,
        "nat_rules_count": 5,
        "firewall_rules_count": 7,
        "static_routes_count": 2,
    }

    mock_vcd_counts["ip_sets"].assert_called_once_with(_EDGE_ID)
    mock_vcd_counts["nat"].assert_called_once_with(_EDGE_ID)
    mock_vcd_counts["fw"].assert_called_once_with(_EDGE_ID)
    mock_vcd_counts["routes"].assert_called_once_with(_EDGE_ID)


@pytest.mark.asyncio
async def test_target_check_viewer_allowed(mock_vcd_counts):
    """tf-viewer should be allowed to run a read-only target check."""
    app.dependency_overrides[get_current_user] = _override_auth(_VIEWER_USER)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/v1/migration/target-check",
            params={"edge_id": _EDGE_ID},
        )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_target_check_forbidden_for_no_role_user(mock_vcd_counts):
    app.dependency_overrides[get_current_user] = _override_auth(_NO_ROLE_USER)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/v1/migration/target-check",
            params={"edge_id": _EDGE_ID},
        )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_target_check_missing_edge_id(mock_vcd_counts):
    app.dependency_overrides[get_current_user] = _override_auth(_ADMIN_USER)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/migration/target-check")

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_target_check_zero_on_errors():
    """When VCD calls fail, the client returns 0 — endpoint still returns 200."""
    app.dependency_overrides[get_current_user] = _override_auth(_ADMIN_USER)

    with (
        patch(
            "app.api.routes.migration.vcd_client.count_ip_sets_on_edge",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.api.routes.migration.vcd_client.count_nat_rules_on_edge",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.api.routes.migration.vcd_client.count_firewall_rules_on_edge",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.api.routes.migration.vcd_client.count_static_routes_on_edge",
            new=AsyncMock(return_value=0),
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/migration/target-check",
                params={"edge_id": _EDGE_ID},
            )

    assert resp.status_code == 200
    assert resp.json() == {
        "ip_sets_count": 0,
        "nat_rules_count": 0,
        "firewall_rules_count": 0,
        "static_routes_count": 0,
    }
