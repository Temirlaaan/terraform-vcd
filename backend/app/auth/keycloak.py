"""Keycloak JWT validation for FastAPI.

Validates ``Authorization: Bearer <token>`` against the Keycloak JWKS
endpoint and extracts user identity + AD-mapped realm roles.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  JWKS cache (in-memory, refreshed on key miss or after TTL)
# ---------------------------------------------------------------------------

_jwks_cache: dict[str, Any] | None = None
_jwks_fetched_at: float = 0.0
_JWKS_REFRESH_INTERVAL = 3600  # Re-fetch at least every hour


async def _fetch_jwks() -> dict[str, Any]:
    """Download the Keycloak realm JWKS."""
    url = (
        f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
        "/protocol/openid-connect/certs"
    )
    async with httpx.AsyncClient(verify=settings.verify_ssl) as client:
        resp = await client.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()


async def _get_jwks() -> dict[str, Any]:
    global _jwks_cache, _jwks_fetched_at
    if _jwks_cache is None or (time.monotonic() - _jwks_fetched_at > _JWKS_REFRESH_INTERVAL):
        return await _refresh_jwks()
    return _jwks_cache


async def _refresh_jwks() -> dict[str, Any]:
    global _jwks_cache, _jwks_fetched_at
    _jwks_cache = await _fetch_jwks()
    _jwks_fetched_at = time.monotonic()
    return _jwks_cache


# ---------------------------------------------------------------------------
#  User model
# ---------------------------------------------------------------------------


@dataclass
class AuthenticatedUser:
    """Parsed identity from a validated Keycloak JWT."""

    sub: str  # Keycloak subject (user UUID)
    username: str
    email: str = ""
    full_name: str = ""
    roles: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
#  Token verification
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=True)


def _extract_roles(payload: dict[str, Any]) -> list[str]:
    """Pull realm-level roles from the token claims.

    Keycloak stores realm roles under ``realm_access.roles``.
    AD-mapped groups typically appear there after role-mapping is configured.
    """
    realm_access = payload.get("realm_access", {})
    return realm_access.get("roles", [])


async def _decode_token(token: str) -> dict[str, Any]:
    """Validate and decode a Keycloak-issued JWT."""
    jwks = await _get_jwks()

    # Extract the key id from the token header
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token header: {exc}",
        )

    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing 'kid' header",
        )

    # Find the matching key
    rsa_key: dict[str, Any] | None = None
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            rsa_key = key
            break

    # If key not found, refresh JWKS (key rotation) and retry once
    if rsa_key is None:
        jwks = await _refresh_jwks()
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                rsa_key = key
                break

    if rsa_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to find matching signing key",
        )

    issuer = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"

    try:
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"verify_at_hash": False, "verify_aud": False},
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {exc}",
        )

    # Accept either "account" (default PUBLIC client behaviour) or the client id
    # (confidential clients with an Audience mapper).
    aud = payload.get("aud")
    aud_list = aud if isinstance(aud, list) else [aud] if aud else []
    accepted = {"account", settings.keycloak_client_id}
    if not (set(aud_list) & accepted):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token audience: {aud}",
        )

    return payload


# ---------------------------------------------------------------------------
#  FastAPI dependencies
# ---------------------------------------------------------------------------


_ANONYMOUS_USER = AuthenticatedUser(
    sub="anonymous",
    username="anonymous",
    email="anonymous@local",
    full_name="Anonymous (auth disabled)",
    roles=["tf-admin", "tf-operator", "tf-viewer"],
)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        HTTPBearer(auto_error=False)
    ),
) -> AuthenticatedUser:
    """FastAPI dependency — validates JWT and returns the authenticated user.

    When ``AUTH_DISABLED=true`` is set, returns an anonymous admin user
    without requiring a token (for local testing only).
    """
    if settings.auth_disabled:
        logger.warning("AUTH_DISABLED is set — returning anonymous admin user")
        return _ANONYMOUS_USER

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization token",
        )

    payload = await _decode_token(credentials.credentials)

    return AuthenticatedUser(
        sub=payload.get("sub", ""),
        username=payload.get("preferred_username", ""),
        email=payload.get("email", ""),
        full_name=payload.get("name", ""),
        roles=_extract_roles(payload),
    )


async def validate_ws_token(token: str) -> AuthenticatedUser:
    """Validate a token passed as a WebSocket query parameter.

    Browsers cannot send Authorization headers on WebSocket connections,
    so the frontend passes the token via ``?token=<jwt>``.
    """
    if settings.auth_disabled:
        return _ANONYMOUS_USER

    payload = await _decode_token(token)

    return AuthenticatedUser(
        sub=payload.get("sub", ""),
        username=payload.get("preferred_username", ""),
        email=payload.get("email", ""),
        full_name=payload.get("name", ""),
        roles=_extract_roles(payload),
    )
