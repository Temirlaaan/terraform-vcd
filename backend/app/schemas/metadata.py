from pydantic import BaseModel


class OrgItem(BaseModel):
    name: str
    display_name: str
    is_enabled: bool


class ProviderVdcItem(BaseModel):
    name: str
    is_enabled: bool
    cpu_allocated_mhz: int | None = None
    memory_allocated_mb: int | None = None


class VdcItem(BaseModel):
    name: str
    org_name: str
    allocation_model: str | None = None
    is_enabled: bool


class StorageProfileItem(BaseModel):
    name: str
    limit_mb: int | None = None
    used_mb: int | None = None
    is_default: bool = False


class EdgeGatewayItem(BaseModel):
    name: str
    org_name: str
    vdc_name: str
    gateway_type: str | None = None


class ExternalNetworkItem(BaseModel):
    name: str
    description: str | None = None
    subnets: list[str] = []


class MetadataListResponse(BaseModel):
    items: list[dict]
    count: int
