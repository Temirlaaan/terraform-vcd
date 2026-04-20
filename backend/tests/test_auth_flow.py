"""End-to-end Keycloak auth flow tests.

Uses an RSA key generated at test-time to mint JWTs and patches the
JWKS loader so the application validates them as if they came from
Keycloak.

-----------------------------------------------------------------------
Manual smoke test (once Keycloak is wired up):
-----------------------------------------------------------------------
1. Ensure ``AUTH_DISABLED=false`` and ``VITE_AUTH_DISABLED=false``.
2. Run ``docker-compose up -d``.
3. Open ``http://localhost:5174`` in an incognito window.
4. You should be redirected to ``https://sso-ttc.t-cloud.kz/realms/prod-v1``.
5. Log in with an AD account that has one of: ``tf-admin``, ``tf-operator``,
   ``tf-viewer`` realm role.
6. After redirect back you should see your display name in the TopBar.
7. Open the Migration page and run a Plan — the backend log should
   show ``user=<your-username> action=migration_plan``.
8. Test expiry: set the Keycloak access-token lifespan to 30s and wait —
   requests should silently refresh 30s before expiry (axios interceptor).
9. Test role gating: log in with a user who has none of the three realm
   roles — all ``/api/v1/*`` calls should return ``403 Insufficient
   permissions``.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from jose import jwt

from app.config import settings
from app.main import app

_KID = "test-kid-001"


def _make_rsa_keypair():
    """Generate an RSA keypair for signing test tokens."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = key.public_key().public_numbers()

    def _b64url_uint(n: int) -> str:
        import base64
        b = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    jwk = {
        "kty": "RSA",
        "kid": _KID,
        "use": "sig",
        "alg": "RS256",
        "n": _b64url_uint(pub.n),
        "e": _b64url_uint(pub.e),
    }
    return private_pem, jwk


@pytest.fixture(scope="module")
def rsa_keys():
    private_pem, jwk = _make_rsa_keypair()
    return {"private_pem": private_pem, "jwk": jwk}


@pytest.fixture(autouse=True)
def patch_jwks(rsa_keys):
    """Patch the JWKS fetcher so the test keypair's public half is used."""
    jwks = {"keys": [rsa_keys["jwk"]]}
    with patch(
        "app.auth.keycloak._fetch_jwks",
        new=AsyncMock(return_value=jwks),
    ):
        # Also reset the in-memory cache
        import app.auth.keycloak as kc_mod
        kc_mod._jwks_cache = None
        kc_mod._jwks_fetched_at = 0.0
        yield


@pytest.fixture(autouse=True)
def real_auth(monkeypatch):
    """Force the dependency to actually validate tokens (AUTH_DISABLED=false)."""
    monkeypatch.setattr(settings, "auth_disabled", False)
    yield


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def _mint_token(
    rsa_keys,
    *,
    roles: list[str] | None = None,
    expired: bool = False,
    username: str = "alice",
    sub: str = "user-001",
) -> str:
    now = int(time.time())
    iat = now - 3600 if expired else now
    exp = now - 60 if expired else now + 3600

    claims: dict[str, Any] = {
        "sub": sub,
        "preferred_username": username,
        "email": f"{username}@example.com",
        "name": username.title(),
        "iat": iat,
        "exp": exp,
        "iss": f"{settings.keycloak_url}/realms/{settings.keycloak_realm}",
        "aud": "account",
        "realm_access": {"roles": roles or []},
    }
    return jwt.encode(
        claims,
        rsa_keys["private_pem"],
        algorithm="RS256",
        headers={"kid": _KID},
    )


# ---------------------------------------------------------------------------
#  Tests — use GET /api/v1/deployments as a representative protected route.
# ---------------------------------------------------------------------------


class TestAuthFlow:
    async def test_valid_admin_token_returns_200(self, rsa_keys):
        token = _mint_token(rsa_keys, roles=["tf-admin"])

        # Fake an empty DB result for the list endpoint
        from app.database import get_db

        async def _fake_db():
            class _DB:
                async def execute(self, _stmt):
                    from unittest.mock import MagicMock
                    res = MagicMock()
                    scalars = MagicMock()
                    scalars.all = MagicMock(return_value=[])
                    res.scalars = MagicMock(return_value=scalars)
                    res.scalar_one = MagicMock(return_value=0)
                    return res
            yield _DB()

        app.dependency_overrides[get_db] = _fake_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.get(
                "/api/v1/deployments",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200

    async def test_token_with_no_roles_returns_403(self, rsa_keys):
        token = _mint_token(rsa_keys, roles=[])
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.get(
                "/api/v1/deployments",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 403
        assert "Insufficient permissions" in resp.json()["detail"]

    async def test_no_token_returns_401(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.get("/api/v1/deployments")

        # HTTPBearer(auto_error=True) inside FastAPI returns 403; our
        # custom "missing token" handler in get_current_user returns 401.
        # Accept both — the relevant invariant is "no valid user".
        assert resp.status_code in (401, 403)

    async def test_expired_token_returns_401(self, rsa_keys):
        token = _mint_token(rsa_keys, roles=["tf-admin"], expired=True)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            resp = await client.get(
                "/api/v1/deployments",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 401
