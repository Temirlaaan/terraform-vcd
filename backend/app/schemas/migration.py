"""Pydantic schemas for the edge migration API."""

import uuid

from pydantic import BaseModel, Field


class MigrationRequest(BaseModel):
    """Request body for POST /api/v1/migration/generate."""

    host: str = Field(..., min_length=1, description="Legacy VCD host URL (e.g. https://vcd01.t-cloud.kz)")
    api_token: str = Field(..., min_length=1, description="VCD API access token (generated via VCD UI)")
    edge_uuid: str = Field(..., min_length=1, description="NSX-V edge gateway UUID")
    target_org: str = Field(..., min_length=1, description="Target organization name in VCD 10.6")
    target_vdc: str = Field(..., min_length=1, description="Target VDC name")
    target_edge_id: str = Field(..., min_length=1, description="Target NSX-T edge gateway URN")
    verify_ssl: bool = Field(False, description="Verify SSL certificate of legacy VCD")


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


class MigrationPlanResponse(BaseModel):
    """Response body for POST /api/v1/migration/plan."""

    operation_id: uuid.UUID


class MigrationApplyRequest(BaseModel):
    """Request body for POST /api/v1/migration/apply."""

    operation_id: uuid.UUID = Field(..., description="Plan operation ID to apply")
