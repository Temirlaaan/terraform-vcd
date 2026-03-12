/** Mirrors the backend Pydantic schemas. */

export interface OrgConfig {
  name: string;
  full_name: string;
  description: string;
  is_enabled: boolean;
  delete_force: boolean;
  delete_recursive: boolean;
}

export interface StorageProfile {
  name: string;
  limit: number;
  default: boolean;
  enabled: boolean;
}

export interface VdcConfig {
  name: string;
  provider_vdc_name: string;
  allocation_model: string;
  network_pool_name: string;
  cpu_allocated: number;
  cpu_limit: number;
  memory_allocated: number;
  memory_limit: number;
  storage_profiles: StorageProfile[];
  enable_thin_provisioning: boolean;
  enable_fast_provisioning: boolean;
  description: string;
}

export interface EdgeConfig {
  name: string;
  external_network: string;
  gateway_ip: string;
}

export interface NetworkConfig {
  name: string;
  gateway: string;
  prefix_length: number;
  dns1: string;
  dns2: string;
  static_ip_pool_start: string;
  static_ip_pool_end: string;
}

export interface ProviderConfig {
  org: string;
  allow_unverified_ssl: boolean;
}

export interface BackendConfig {
  bucket: string;
  endpoint: string;
  region: string;
}

export interface TerraformConfig {
  provider: ProviderConfig;
  backend: BackendConfig;
  org: OrgConfig;
  vdc: VdcConfig;
  edge: EdgeConfig;
  network: NetworkConfig;
}
