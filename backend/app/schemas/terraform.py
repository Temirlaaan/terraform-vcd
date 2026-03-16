import ipaddress
import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.operation import OperationStatus, OperationType

# Regex for safe resource names — letters, digits, spaces, hyphens, underscores, parens.
# Uses literal space (not \s) to block newlines, tabs, and other whitespace.
# Blocks path traversal characters (slashes, dots) and shell metacharacters.
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9 \-_()]{1,255}$")


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
    elasticity: bool = False
    include_vm_memory_overhead: bool = True
    description: str | None = None

    @field_validator("name")
    @classmethod
    def validate_vdc_name(cls, v: str) -> str:
        return _validate_safe_name(v, "vdc.name")


def _validate_ip(value: str, field_name: str) -> str:
    """Validate that a string is a valid IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(value)
    except ValueError:
        raise ValueError(f"{field_name} must be a valid IP address, got '{value}'")
    return value


class EdgeSubnetConfig(BaseModel):
    gateway: str = Field(..., min_length=1)
    prefix_length: int = Field(default=24, ge=0, le=128)
    primary_ip: str = Field(..., min_length=1)
    start_address: str | None = None
    end_address: str | None = None

    @field_validator("gateway")
    @classmethod
    def validate_gateway(cls, v: str) -> str:
        return _validate_ip(v, "subnet.gateway")

    @field_validator("primary_ip")
    @classmethod
    def validate_primary_ip(cls, v: str) -> str:
        return _validate_ip(v, "subnet.primary_ip")

    @field_validator("start_address")
    @classmethod
    def validate_start_address(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_ip(v, "subnet.start_address")

    @field_validator("end_address")
    @classmethod
    def validate_end_address(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_ip(v, "subnet.end_address")

    @model_validator(mode="after")
    def validate_ip_pool_pair(self) -> "EdgeSubnetConfig":
        """Both start_address and end_address must be provided together."""
        has_start = self.start_address is not None
        has_end = self.end_address is not None
        if has_start != has_end:
            raise ValueError(
                "start_address and end_address must both be provided or both omitted"
            )
        return self


class EdgeGatewayConfig(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    external_network_name: str = Field(..., min_length=1)
    subnet: EdgeSubnetConfig
    dedicate_external_network: bool = False
    description: str | None = None

    @field_validator("name")
    @classmethod
    def validate_edge_name(cls, v: str) -> str:
        return _validate_safe_name(v, "edge.name")


class NetworkStaticPoolConfig(BaseModel):
    """IP pool range for a routed network."""
    start_address: str = Field(..., min_length=1)
    end_address: str = Field(..., min_length=1)

    @field_validator("start_address")
    @classmethod
    def validate_start_address(cls, v: str) -> str:
        return _validate_ip(v, "static_ip_pool.start_address")

    @field_validator("end_address")
    @classmethod
    def validate_end_address(cls, v: str) -> str:
        return _validate_ip(v, "static_ip_pool.end_address")


class RoutedNetworkConfig(BaseModel):
    """Configuration for vcd_network_routed_v2 resource."""
    name: str = Field(..., min_length=1, max_length=255)
    gateway: str = Field(..., min_length=1)
    prefix_length: int = Field(default=24, ge=0, le=128)
    dns1: str | None = None
    dns2: str | None = None
    static_ip_pool: NetworkStaticPoolConfig | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def validate_network_name(cls, v: str) -> str:
        return _validate_safe_name(v, "network.name")

    @field_validator("gateway")
    @classmethod
    def validate_gateway(cls, v: str) -> str:
        return _validate_ip(v, "network.gateway")

    @field_validator("dns1")
    @classmethod
    def validate_dns1(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_ip(v, "network.dns1")

    @field_validator("dns2")
    @classmethod
    def validate_dns2(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_ip(v, "network.dns2")


class VappConfig(BaseModel):
    """Configuration for vcd_vapp resource."""
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    power_on: bool = False

    @field_validator("name")
    @classmethod
    def validate_vapp_name(cls, v: str) -> str:
        return _validate_safe_name(v, "vapp.name")


class VmNetworkConfig(BaseModel):
    """Network adapter configuration for vcd_vapp_vm."""
    type: str = "org"
    name: str = Field(..., min_length=1, max_length=255)
    ip_allocation_mode: str = "POOL"
    ip: str | None = None

    @field_validator("name")
    @classmethod
    def validate_network_name(cls, v: str) -> str:
        return _validate_safe_name(v, "vm.network.name")

    @field_validator("ip_allocation_mode")
    @classmethod
    def validate_ip_allocation_mode(cls, v: str) -> str:
        allowed = {"POOL", "DHCP", "MANUAL"}
        if v not in allowed:
            raise ValueError(
                f"ip_allocation_mode must be one of {allowed}, got '{v}'"
            )
        return v

    @field_validator("ip")
    @classmethod
    def validate_ip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_ip(v, "vm.network.ip")

    @model_validator(mode="after")
    def validate_manual_requires_ip(self) -> "VmNetworkConfig":
        """ip is required when ip_allocation_mode is MANUAL."""
        if self.ip_allocation_mode == "MANUAL" and self.ip is None:
            raise ValueError("ip is required when ip_allocation_mode is MANUAL")
        return self


class VappVmConfig(BaseModel):
    """Configuration for vcd_vapp_vm resource."""
    name: str = Field(..., min_length=1, max_length=255)
    computer_name: str = Field(..., min_length=1, max_length=63)
    catalog_name: str = Field(..., min_length=1, max_length=255)
    template_name: str = Field(..., min_length=1, max_length=255)
    memory: int = Field(default=1024, ge=256)
    cpus: int = Field(default=1, ge=1)
    cpu_cores: int = Field(default=1, ge=1)
    storage_profile: str | None = None
    network: VmNetworkConfig | None = None
    power_on: bool = True
    description: str | None = None

    @field_validator("name")
    @classmethod
    def validate_vm_name(cls, v: str) -> str:
        return _validate_safe_name(v, "vm.name")

    @field_validator("computer_name")
    @classmethod
    def validate_computer_name(cls, v: str) -> str:
        return _validate_safe_name(v, "vm.computer_name")

    @field_validator("catalog_name")
    @classmethod
    def validate_catalog_name(cls, v: str) -> str:
        return _validate_safe_name(v, "vm.catalog_name")

    @field_validator("template_name")
    @classmethod
    def validate_template_name(cls, v: str) -> str:
        return _validate_safe_name(v, "vm.template_name")


class TerraformConfig(BaseModel):
    """Typed configuration matching the Jinja2 template expectations."""
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    backend: BackendConfig = Field(default_factory=BackendConfig)
    org: OrgConfig | None = None
    vdc: VdcConfig | None = None
    edge: EdgeGatewayConfig | None = None
    network: RoutedNetworkConfig | None = None
    vapp: VappConfig | None = None
    vm: VappVmConfig | None = None

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
        if self.edge is not None:
            d["edge"] = self.edge.model_dump(exclude_none=True)
        if self.network is not None:
            d["network"] = self.network.model_dump(exclude_none=True)
        if self.vapp is not None:
            d["vapp"] = self.vapp.model_dump(exclude_none=True)
        if self.vm is not None:
            d["vm"] = self.vm.model_dump(exclude_none=True)
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
