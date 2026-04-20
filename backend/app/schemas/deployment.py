"""Pydantic schemas for saved deployments."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.terraform import _validate_safe_name


class DeploymentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    source_host: str = Field(..., min_length=1)
    source_edge_uuid: str = Field(..., min_length=1)
    source_edge_name: str = Field(..., min_length=1)
    verify_ssl: bool = False
    target_org: str = Field(..., min_length=1)
    target_vdc: str = Field(..., min_length=1)
    target_vdc_id: str = Field(..., min_length=1)
    target_edge_id: str = Field(..., min_length=1)
    hcl: str = Field(..., min_length=1)
    summary: dict[str, Any]

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_safe_name(v, "name")


class DeploymentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_safe_name(v, "name")


class DeploymentOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    description: str | None
    source_host: str
    source_edge_uuid: str
    source_edge_name: str
    verify_ssl: bool
    target_org: str
    target_vdc: str
    target_vdc_id: str
    target_edge_id: str
    hcl: str
    summary: dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeploymentListItem(BaseModel):
    """Lightweight item for list views (no HCL body — can be megabytes)."""

    id: uuid.UUID
    name: str
    kind: str
    description: str | None
    source_edge_name: str
    target_org: str
    target_vdc: str
    summary: dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeploymentList(BaseModel):
    items: list[DeploymentListItem]
    total: int
