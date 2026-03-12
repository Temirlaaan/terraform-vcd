from pydantic import BaseModel


class OrgItem(BaseModel):
    name: str
    display_name: str
    id: str = ""
    is_enabled: bool


class ProviderVdcItem(BaseModel):
    name: str
    id: str = ""
    is_enabled: bool


class VdcItem(BaseModel):
    name: str
    id: str = ""
    org_name: str
    allocation_model: str | None = None
    is_enabled: bool


class StorageProfileItem(BaseModel):
    name: str
    id: str = ""
    is_enabled: bool = True


class EdgeGatewayItem(BaseModel):
    name: str
    id: str = ""
    vdc_name: str
    gateway_type: str | None = None


class ExternalNetworkItem(BaseModel):
    name: str
    id: str = ""
    description: str | None = None


class MetadataListResponse(BaseModel):
    items: list[dict]
    count: int
