"""Pydantic schemas for the edge migration API."""

import uuid
from typing import Any

from pydantic import BaseModel, Field, model_validator


class AuthHandleRequest(BaseModel):
    """Request body for POST /api/v1/migration/auth-handle.

    Browser submits the legacy-VCD host + refresh token once, backend
    issues a short-lived opaque UUID handle (Redis-backed, TTL=600s).
    Subsequent migration calls reference the handle instead of the
    token. H3-FE: keeps a System-Administrator-scoped credential out
    of browser sessionStorage.
    """

    host: str = Field(..., min_length=1)
    api_token: str = Field(..., min_length=1)


class AuthHandleResponse(BaseModel):
    handle: str
    expires_in: int


class MigrationRequest(BaseModel):
    """Request body for POST /api/v1/migration/generate.

    Either ``handle`` (preferred, redeemed against Redis) or ``api_token``
    (legacy direct path, accepted for backwards compatibility) must be
    supplied. ``host`` is taken from the handle when present.
    """

    host: str | None = Field(None, description="Legacy VCD host URL — required when api_token is used; taken from handle otherwise")
    api_token: str | None = Field(None, description="VCD API access token (legacy direct path; prefer handle)")
    handle: str | None = Field(None, description="Opaque Redis handle from POST /migration/auth-handle")
    edge_uuid: str = Field(..., min_length=1, description="NSX-V edge gateway UUID")
    target_org: str = Field(..., min_length=1, description="Target organization name in VCD 10.6")
    target_vdc: str = Field(..., min_length=1, description="Target VDC name")
    target_vdc_id: str = Field(..., min_length=1, description="Target VDC URN")
    target_edge_id: str = Field(..., min_length=1, description="Target NSX-T edge gateway URN")
    verify_ssl: bool = Field(False, description="Verify SSL certificate of legacy VCD")

    @model_validator(mode="after")
    def _check_auth(self) -> "MigrationRequest":
        if not self.handle and not self.api_token:
            raise ValueError("Either 'handle' or 'api_token' must be supplied")
        if self.api_token and not self.host:
            raise ValueError("'host' is required when using 'api_token'")
        return self


class MigrationSummary(BaseModel):
    """Summary counts from the normalized edge snapshot."""

    firewall_rules_total: int
    firewall_rules_user: int
    firewall_rules_system: int
    nat_rules_total: int
    app_port_profiles_total: int
    app_port_profiles_system: int
    app_port_profiles_custom: int
    static_routes_total: int


class MigrationResponse(BaseModel):
    """Response body for POST /api/v1/migration/generate."""

    hcl: str
    edge_name: str
    summary: MigrationSummary


class MigrationPlanRequest(BaseModel):
    """Request body for POST /api/v1/migration/plan."""

    hcl: str = Field(..., min_length=1, description="Pre-generated HCL from the Generate step")
    target_org: str = Field(..., min_length=1, description="Target organization name (for locking)")
    target_edge_id: str = Field(..., min_length=1, description="Target NSX-T edge gateway URN")
    source_edge_name: str | None = Field(
        None, description="Source (legacy NSX-V) edge name, used for auto-created deployment naming"
    )
    target_vdc: str | None = Field(
        None, description="Target VDC name, used for auto-created deployment description"
    )
    target_edge_name: str | None = Field(
        None, description="Target NSX-T edge gateway name, used for auto-created deployment description"
    )
    # Backfill hints for auto-created migration deployment row
    source_host: str | None = Field(
        None, description="Legacy VCD host URL, persisted on auto-created Deployment"
    )
    source_edge_uuid: str | None = Field(
        None, description="Source NSX-V edge UUID, persisted on auto-created Deployment"
    )
    verify_ssl: bool | None = Field(
        None, description="verify_ssl flag, persisted on auto-created Deployment"
    )
    summary: dict[str, Any] | None = Field(
        None, description="Summary counts from /generate, persisted on auto-created Deployment"
    )


class MigrationPlanResponse(BaseModel):
    """Response body for POST /api/v1/migration/plan."""

    operation_id: uuid.UUID


class MigrationApplyRequest(BaseModel):
    """Request body for POST /api/v1/migration/apply."""

    operation_id: uuid.UUID = Field(..., description="Plan operation ID to apply")


class TargetCheckResponse(BaseModel):
    """Response body for GET /api/v1/migration/target-check."""

    ip_sets_count: int
    nat_rules_count: int
    firewall_rules_count: int
    static_routes_count: int
