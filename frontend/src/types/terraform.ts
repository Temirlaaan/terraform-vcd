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
  elasticity: boolean;
  include_vm_memory_overhead: boolean;
  memory_guaranteed?: number;
  delete_force: boolean;
  delete_recursive: boolean;
  description: string;
}

export interface EdgeSubnet {
  gateway: string;
  prefix_length: number;
  primary_ip: string;
  start_address?: string;
  end_address?: string;
}

export interface EdgeConfig {
  name: string;
  external_network_name: string;
  subnet: EdgeSubnet;
  dedicate_external_network: boolean;
  description?: string;
}

export interface NetworkStaticPool {
  start_address: string;
  end_address: string;
}

export interface NetworkConfig {
  name: string;
  gateway: string;
  prefix_length: number;
  dns1?: string;
  dns2?: string;
  static_ip_pool?: NetworkStaticPool;
  description?: string;
}

export interface VappConfig {
  name: string;
  description?: string;
  power_on: boolean;
}

export interface VmNetworkConfig {
  type: string;
  name: string;
  ip_allocation_mode: string;
  ip?: string;
}

export interface VappVmConfig {
  name: string;
  computer_name: string;
  catalog_name: string;
  template_name: string;
  memory: number;
  cpus: number;
  cpu_cores: number;
  storage_profile?: string;
  network?: VmNetworkConfig;
  power_on: boolean;
  description?: string;
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
  vapp: VappConfig;
  vm: VappVmConfig;
}
