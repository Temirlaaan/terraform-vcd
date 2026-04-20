"""Tests for deployments CRUD endpoints.

Uses FastAPI dependency overrides to mock the auth user and an
in-memory list to fake the DB layer — the production SQLAlchemy
async session is swapped out with an async stub.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.keycloak import AuthenticatedUser, get_current_user
from app.database import get_db
from app.main import app
from app.models.deployment import Deployment

_ADMIN_USER = AuthenticatedUser(
    sub="admin-sub",
    username="alice",
    email="alice@test.com",
    full_name="Alice Admin",
    roles=["tf-admin"],
)

_NO_ROLE_USER = AuthenticatedUser(
    sub="noroles-sub",
    username="bob",
    email="bob@test.com",
    full_name="Bob NoRoles",
    roles=[],
)


def _override_user(user: AuthenticatedUser):
    async def _dep():
        return user

    return _dep


def _valid_body(**overrides: Any) -> dict[str, Any]:
    body = {
        "name": "migration-2026-04-20",
        "description": "TTC telco edge migration",
        "source_host": "https://vcd-legacy.t-cloud.kz",
        "source_edge_uuid": "b6b3181a-2596-44c5-9991-c4c54c050bcb",
        "source_edge_name": "TTC_Telco_EDGE",
        "verify_ssl": False,
        "target_org": "TTCTelco",
        "target_vdc": "TTCTelcoVDC",
        "target_vdc_id": "urn:vcloud:vdc:abc-123",
        "target_edge_id": "urn:vcloud:gateway:def-456",
        "hcl": "resource \"vcd_nsxt_firewall\" \"fw\" {}",
        "summary": {
            "firewall_rules_total": 5,
            "firewall_rules_user": 4,
            "firewall_rules_system": 1,
            "nat_rules_total": 4,
            "app_port_profiles_total": 3,
            "app_port_profiles_system": 1,
            "app_port_profiles_custom": 2,
            "static_routes_total": 2,
        },
    }
    body.update(overrides)
    return body


def _make_deployment(**overrides: Any) -> Deployment:
    """Build a Deployment instance with sane defaults (not persisted)."""
    defaults = _valid_body()
    now = datetime.now(timezone.utc)
    d = Deployment(
        id=overrides.get("id", uuid.uuid4()),
        name=overrides.get("name", defaults["name"]),
        kind=overrides.get("kind", "migration"),
        description=overrides.get("description", defaults["description"]),
        source_host=overrides.get("source_host", defaults["source_host"]),
        source_edge_uuid=overrides.get("source_edge_uuid", defaults["source_edge_uuid"]),
        source_edge_name=overrides.get("source_edge_name", defaults["source_edge_name"]),
        verify_ssl=overrides.get("verify_ssl", defaults["verify_ssl"]),
        target_org=overrides.get("target_org", defaults["target_org"]),
        target_vdc=overrides.get("target_vdc", defaults["target_vdc"]),
        target_vdc_id=overrides.get("target_vdc_id", defaults["target_vdc_id"]),
        target_edge_id=overrides.get("target_edge_id", defaults["target_edge_id"]),
        hcl=overrides.get("hcl", defaults["hcl"]),
        summary=overrides.get("summary", defaults["summary"]),
        created_by=overrides.get("created_by", "alice"),
    )
    d.created_at = overrides.get("created_at", now)
    d.updated_at = overrides.get("updated_at", now)
    return d


class _FakeDB:
    """Minimal async-compatible fake of SQLAlchemy's AsyncSession.

    Supports add + commit + refresh for POST, and scalar_one_or_none/
    scalars().all() for GET/LIST.  The backing store is a plain list.
    """

    def __init__(self, items: list[Deployment] | None = None) -> None:
        self.items: list[Deployment] = list(items or [])
        self._last_added: Deployment | None = None
        self._last_filter_edge_id: str | None = None
        self._pending_delete: Deployment | None = None

    def add(self, obj: Deployment) -> None:
        self.items.append(obj)
        self._last_added = obj

    async def delete(self, obj: Deployment) -> None:
        self._pending_delete = obj

    async def commit(self) -> None:
        if self._pending_delete is not None:
            self.items = [d for d in self.items if d.id != self._pending_delete.id]
            self._pending_delete = None

    async def refresh(self, obj: Deployment) -> None:
        if obj.created_at is None:
            obj.created_at = datetime.now(timezone.utc)
        if obj.updated_at is None:
            obj.updated_at = datetime.now(timezone.utc)
        if obj.id is None:
            obj.id = uuid.uuid4()
        if obj.kind is None:
            obj.kind = "migration"

    async def execute(self, stmt):  # noqa: ANN001
        text = str(stmt).lower()
        result = MagicMock()

        if "count" in text:
            filtered = list(self.items)
            if self._last_filter_edge_id:
                filtered = [
                    d for d in filtered
                    if d.target_edge_id == self._last_filter_edge_id
                ]
            result.scalar_one = MagicMock(return_value=len(filtered))
            return result

        # SELECT — try to extract target_edge_id filter from bind params
        filtered = list(self.items)
        try:
            params = stmt.compile().params  # type: ignore[attr-defined]
        except Exception:
            params = {}

        for key, val in params.items():
            if "target_edge_id" in key and isinstance(val, str):
                filtered = [d for d in filtered if d.target_edge_id == val]
                self._last_filter_edge_id = val
                break
            if "id" in key and isinstance(val, uuid.UUID):
                filtered = [d for d in filtered if d.id == val]

        # Order by created_at DESC if the query references created_at
        if "order by" in text and "created_at" in text:
            filtered = sorted(
                filtered, key=lambda d: d.created_at, reverse=True
            )

        scalars = MagicMock()
        scalars.all = MagicMock(return_value=filtered)
        result.scalars = MagicMock(return_value=scalars)
        result.scalar_one_or_none = MagicMock(
            return_value=filtered[0] if filtered else None
        )
        return result


@pytest.fixture
def fake_db():
    return _FakeDB()


@pytest.fixture
def override_db(fake_db):
    async def _dep():
        yield fake_db

    app.dependency_overrides[get_db] = _dep
    yield fake_db
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
#  POST /deployments
# ---------------------------------------------------------------------------


class TestCreateDeployment:
    async def test_returns_201(self, override_db):
        app.dependency_overrides[get_current_user] = _override_user(_ADMIN_USER)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/deployments", json=_valid_body())

        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "migration-2026-04-20"
        assert data["created_by"] == "alice"
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_ignores_created_by_from_body(self, override_db):
        app.dependency_overrides[get_current_user] = _override_user(_ADMIN_USER)
        body = _valid_body()
        body["created_by"] = "evil-user"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/deployments", json=body)

        assert resp.status_code == 201
        assert resp.json()["created_by"] == "alice"

    async def test_empty_name_returns_422(self, override_db):
        app.dependency_overrides[get_current_user] = _override_user(_ADMIN_USER)
        body = _valid_body(name="")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/deployments", json=body)
        assert resp.status_code == 422

    async def test_missing_hcl_returns_422(self, override_db):
        app.dependency_overrides[get_current_user] = _override_user(_ADMIN_USER)
        body = _valid_body()
        del body["hcl"]
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.post("/api/v1/deployments", json=body)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
#  GET /deployments (list)
# ---------------------------------------------------------------------------


class TestListDeployments:
    async def test_returns_items_sorted_desc(self, override_db):
        app.dependency_overrides[get_current_user] = _override_user(_ADMIN_USER)
        old = _make_deployment(
            name="old",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        new = _make_deployment(
            name="new",
            created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        override_db.items = [old, new]

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.get("/api/v1/deployments")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert [i["name"] for i in data["items"]] == ["new", "old"]

    async def test_filter_by_target_edge_id(self, override_db):
        app.dependency_overrides[get_current_user] = _override_user(_ADMIN_USER)
        matching = _make_deployment(
            name="match", target_edge_id="urn:gw:AAA",
        )
        not_matching = _make_deployment(
            name="other", target_edge_id="urn:gw:BBB",
        )
        override_db.items = [matching, not_matching]

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.get(
                "/api/v1/deployments",
                params={"target_edge_id": "urn:gw:AAA"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "match"

    async def test_empty_list(self, override_db):
        app.dependency_overrides[get_current_user] = _override_user(_ADMIN_USER)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.get("/api/v1/deployments")

        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}


# ---------------------------------------------------------------------------
#  GET /deployments/{id}
# ---------------------------------------------------------------------------


class TestGetDeployment:
    async def test_returns_deployment(self, override_db):
        app.dependency_overrides[get_current_user] = _override_user(_ADMIN_USER)
        d = _make_deployment()
        override_db.items = [d]

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.get(f"/api/v1/deployments/{d.id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(d.id)
        assert data["hcl"] == d.hcl

    async def test_nonexistent_returns_404(self, override_db):
        app.dependency_overrides[get_current_user] = _override_user(_ADMIN_USER)
        fake_id = uuid.uuid4()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.get(f"/api/v1/deployments/{fake_id}")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
#  PATCH /deployments/{id}
# ---------------------------------------------------------------------------


class TestPatchDeployment:
    async def test_updates_name_only(self, override_db):
        app.dependency_overrides[get_current_user] = _override_user(_ADMIN_USER)
        d = _make_deployment(name="old-name", description="old desc")
        original_hcl = d.hcl
        override_db.items = [d]

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.patch(
                f"/api/v1/deployments/{d.id}",
                json={"name": "new-name"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "new-name"
        assert data["description"] == "old desc"
        assert data["hcl"] == original_hcl

    async def test_nonexistent_returns_404(self, override_db):
        app.dependency_overrides[get_current_user] = _override_user(_ADMIN_USER)
        fake_id = uuid.uuid4()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.patch(
                f"/api/v1/deployments/{fake_id}",
                json={"name": "anything"},
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
#  DELETE /deployments/{id}
# ---------------------------------------------------------------------------


class TestDeleteDeployment:
    async def test_returns_204_then_404(self, override_db):
        app.dependency_overrides[get_current_user] = _override_user(_ADMIN_USER)
        d = _make_deployment()
        override_db.items = [d]

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.delete(f"/api/v1/deployments/{d.id}")
            assert resp.status_code == 204

            resp = await client.get(f"/api/v1/deployments/{d.id}")
            assert resp.status_code == 404

    async def test_nonexistent_returns_404(self, override_db):
        app.dependency_overrides[get_current_user] = _override_user(_ADMIN_USER)
        fake_id = uuid.uuid4()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.delete(f"/api/v1/deployments/{fake_id}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
#  Auth
# ---------------------------------------------------------------------------


class TestDeploymentsAuth:
    async def test_no_role_gets_403(self, override_db):
        app.dependency_overrides[get_current_user] = _override_user(_NO_ROLE_USER)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.get("/api/v1/deployments")

        assert resp.status_code == 403
        assert "Insufficient permissions" in resp.json()["detail"]
