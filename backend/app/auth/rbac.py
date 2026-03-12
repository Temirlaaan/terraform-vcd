"""Role-based access control helpers.

Keycloak realm roles (mapped from Active Directory groups):
  - ``tf-admin``    — full access (plan, apply, destroy, manage templates)
  - ``tf-operator`` — plan and apply
  - ``tf-viewer``   — read-only (metadata, operation history)
"""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, status

from app.auth.keycloak import AuthenticatedUser, get_current_user


def require_roles(*allowed: str) -> Callable:
    """Return a FastAPI dependency that checks the user has at least one of
    the *allowed* realm roles.

    Usage::

        @router.post("/plan")
        async def plan(user: AuthenticatedUser = Depends(require_roles("tf-admin", "tf-operator"))):
            ...
    """

    async def _check(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if not any(role in user.roles for role in allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Insufficient permissions. Required role(s): {', '.join(allowed)}"
                ),
            )
        return user

    return _check
