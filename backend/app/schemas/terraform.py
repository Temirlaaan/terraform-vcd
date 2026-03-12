import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.operation import OperationStatus, OperationType

# Regex for safe resource names — letters, digits, spaces, hyphens, underscores, parens.
# Blocks path traversal characters (slashes, dots) and shell metacharacters.
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9\s\-_()]{1,255}$")


def _validate_safe_name(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    if not _SAFE_NAME_RE.match(value):
        raise ValueError(
            f"{field_name} contains invalid characters. "
            "Only letters, digits, spaces, hyphens, underscores, and parentheses are allowed."
        )
    return value


# --- Typed config sub-models ---


class ProviderConfig(BaseModel):
    org: str = "System"
    allow_unverified_ssl: bool = True


class BackendConfig(BaseModel):
    bucket: str = "terraform-state"
    key: str | None = None
    region: str = "us-east-1"
    endpoint: str = "http://minio:9000"


class OrgConfig(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    full_name: str | None = None
    description: str | None = None
    is_enabled: bool = True
    delete_force: bool = False
    delete_recursive: bool = False
    metadata: dict[str, str] | None = None

    @field_validator("name")
    @classmethod
    def validate_org_name(cls, v: str) -> str:
        return _validate_safe_name(v, "org.name")


class StorageProfileConfig(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    limit: int = 0
    default: bool = False
    enabled: bool = True


class VdcConfig(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    org_ref: str | None = None
    allocation_model: str = "AllocationVApp"
    network_pool_name: str = ""
    provider_vdc_name: str = Field(..., min_length=1)
    cpu_allocated: int = Field(default=0, ge=0)
    cpu_limit: int = Field(default=0, ge=0)
    memory_allocated: int = Field(default=0, ge=0)
    memory_limit: int = Field(default=0, ge=0)
    storage_profiles: list[StorageProfileConfig] = Field(default_factory=list)
    enabled: bool = True
    enable_thin_provisioning: bool = True
    enable_fast_provisioning: bool = False
    delete_force: bool = False
    delete_recursive: bool = False
    description: str | None = None

    @field_validator("name")
    @classmethod
    def validate_vdc_name(cls, v: str) -> str:
        return _validate_safe_name(v, "vdc.name")


class TerraformConfig(BaseModel):
    """Typed configuration matching the Jinja2 template expectations."""
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    backend: BackendConfig = Field(default_factory=BackendConfig)
    org: OrgConfig | None = None
    vdc: VdcConfig | None = None

    def to_template_dict(self) -> dict[str, Any]:
        """Convert to dict for Jinja2 rendering, excluding None values."""
        d: dict[str, Any] = {
            "provider": self.provider.model_dump(),
            "backend": self.backend.model_dump(exclude_none=True),
        }
        if self.org is not None:
            d["org"] = self.org.model_dump(exclude_none=True)
        if self.vdc is not None:
            d["vdc"] = self.vdc.model_dump(exclude_none=True)
        return d


# --- Terraform Execution Schemas ---


class TerraformGenerateRequest(BaseModel):
    config: TerraformConfig = Field(..., description="Typed form state from frontend")


class TerraformGenerateResponse(BaseModel):
    hcl: str = Field(..., description="Rendered HCL code")


class TerraformPlanRequest(BaseModel):
    config: TerraformConfig = Field(..., description="Typed form state from frontend")


class TerraformPlanResponse(BaseModel):
    operation_id: uuid.UUID


class TerraformApplyRequest(BaseModel):
    operation_id: uuid.UUID


class TerraformDestroyRequest(BaseModel):
    target_org: str
    target_vdc: str | None = None

    @field_validator("target_org")
    @classmethod
    def validate_target_org(cls, v: str) -> str:
        return _validate_safe_name(v, "target_org")


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
