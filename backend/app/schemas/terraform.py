import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.operation import OperationStatus, OperationType


# --- Terraform Execution Schemas ---


class TerraformGenerateRequest(BaseModel):
    config: dict[str, Any] = Field(..., description="Full form state JSON from frontend")


class TerraformGenerateResponse(BaseModel):
    hcl: str = Field(..., description="Rendered HCL code")


class TerraformPlanRequest(BaseModel):
    config: dict[str, Any] = Field(..., description="Full form state JSON from frontend")


class TerraformPlanResponse(BaseModel):
    operation_id: uuid.UUID


class TerraformApplyRequest(BaseModel):
    operation_id: uuid.UUID


class TerraformDestroyRequest(BaseModel):
    target_org: str
    target_vdc: str | None = None


# --- Operation Schemas ---


class OperationOut(BaseModel):
    id: uuid.UUID
    type: OperationType
    status: OperationStatus
    user_id: str
    username: str
    target_org: str
    started_at: datetime
    completed_at: datetime | None = None
    plan_output: str | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}


class OperationList(BaseModel):
    items: list[OperationOut]
    total: int


# --- Template Schemas ---


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    config_json: dict[str, Any]


class TemplateUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    config_json: dict[str, Any] | None = None


class TemplateOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    config_json: dict[str, Any]
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}
