import { create } from "zustand";
import type {
  OrgConfig,
  VdcConfig,
  EdgeConfig,
  EdgeSubnet,
  NetworkConfig,
  VappConfig,
  VappVmConfig,
  VmNetworkConfig,
  StorageProfile,
  ProviderConfig,
  BackendConfig,
} from "@/types/terraform";

/* ------------------------------------------------------------------ */
/*  Defaults                                                          */
/* ------------------------------------------------------------------ */

const defaultOrg: OrgConfig = {
  name: "",
  full_name: "",
  description: "",
  is_enabled: true,
  delete_force: false,
  delete_recursive: false,
};

const defaultStorageProfile: StorageProfile = {
  name: "",
  limit: 0,
  default: true,
  enabled: true,
};

const defaultVdc: VdcConfig = {
  name: "",
  provider_vdc_name: "",
  allocation_model: "AllocationVApp",
  network_pool_name: "",
  cpu_allocated: 0,
  cpu_limit: 0,
  memory_allocated: 0,
  memory_limit: 0,
  storage_profiles: [{ ...defaultStorageProfile }],
  enable_thin_provisioning: true,
  enable_fast_provisioning: false,
  elasticity: false,
  include_vm_memory_overhead: true,
  memory_guaranteed: 20,
  delete_force: true,
  delete_recursive: true,
  description: "",
};

const defaultSubnet: EdgeSubnet = {
  gateway: "",
  prefix_length: 24,
  primary_ip: "",
};

const defaultEdge: EdgeConfig = {
  name: "",
  external_network_name: "",
  subnet: { ...defaultSubnet },
  dedicate_external_network: false,
};

const defaultNetwork: NetworkConfig = {
  name: "",
  gateway: "",
  prefix_length: 24,
};

const defaultVapp: VappConfig = {
  name: "",
  power_on: false,
};

const defaultVmNetwork: VmNetworkConfig = {
  type: "org",
  name: "",
  ip_allocation_mode: "POOL",
};

const defaultVm: VappVmConfig = {
  name: "",
  computer_name: "",
  catalog_name: "",
  template_name: "",
  memory: 1024,
  cpus: 1,
  cpu_cores: 1,
  power_on: true,
};

const defaultProvider: ProviderConfig = {
  org: "System",
  allow_unverified_ssl: true,
};

const defaultBackend: BackendConfig = {
  bucket: "terraform-state",
  endpoint: "http://minio:9000",
  region: "us-east-1",
};

/* ------------------------------------------------------------------ */
/*  Store                                                             */
/* ------------------------------------------------------------------ */

export type PlanStatus = "idle" | "planning" | "planned" | "applying" | "applied" | "error";

interface ConfigState {
  /* Data */
  provider: ProviderConfig;
  backend: BackendConfig;
  org: OrgConfig;
  vdc: VdcConfig;
  edge: EdgeConfig;
  network: NetworkConfig;
  vapp: VappConfig;
  vm: VappVmConfig;

  /* Execution */
  currentOperationId: string | null;
  planStatus: PlanStatus;
  planError: string | null;

  /* UI */
  terminalOpen: boolean;

  /* Actions */
  setOrg: (patch: Partial<OrgConfig>) => void;
  setVdc: (patch: Partial<VdcConfig>) => void;
  setEdge: (patch: Partial<EdgeConfig>) => void;
  setEdgeSubnet: (patch: Partial<EdgeSubnet>) => void;
  setNetwork: (patch: Partial<NetworkConfig>) => void;
  setVapp: (patch: Partial<VappConfig>) => void;
  setVm: (patch: Partial<VappVmConfig>) => void;
  setVmNetwork: (patch: Partial<VmNetworkConfig>) => void;
  setProvider: (patch: Partial<ProviderConfig>) => void;
  setBackend: (patch: Partial<BackendConfig>) => void;
  addStorageProfile: () => void;
  removeStorageProfile: (index: number) => void;
  updateStorageProfile: (index: number, patch: Partial<StorageProfile>) => void;
  setOperation: (id: string | null, status: PlanStatus, error?: string | null) => void;
  toggleTerminal: () => void;
  openTerminal: () => void;
  resetAll: () => void;
}

export const useConfigStore = create<ConfigState>((set) => ({
  provider: { ...defaultProvider },
  backend: { ...defaultBackend },
  org: { ...defaultOrg },
  vdc: { ...defaultVdc },
  edge: { ...defaultEdge, subnet: { ...defaultSubnet } },
  network: { ...defaultNetwork },
  vapp: { ...defaultVapp },
  vm: { ...defaultVm },
  currentOperationId: null,
  planStatus: "idle",
  planError: null,
  terminalOpen: false,

  setOrg: (patch) =>
    set((s) => ({ org: { ...s.org, ...patch } })),

  setVdc: (patch) =>
    set((s) => ({ vdc: { ...s.vdc, ...patch } })),

  setEdge: (patch) =>
    set((s) => ({ edge: { ...s.edge, ...patch } })),

  setEdgeSubnet: (patch) =>
    set((s) => ({
      edge: { ...s.edge, subnet: { ...s.edge.subnet, ...patch } },
    })),

  setNetwork: (patch) =>
    set((s) => ({ network: { ...s.network, ...patch } })),

  setVapp: (patch) =>
    set((s) => ({ vapp: { ...s.vapp, ...patch } })),

  setVm: (patch) =>
    set((s) => ({ vm: { ...s.vm, ...patch } })),

  setVmNetwork: (patch) =>
    set((s) => ({
      vm: {
        ...s.vm,
        network: { ...(s.vm.network ?? { ...defaultVmNetwork }), ...patch },
      },
    })),

  setProvider: (patch) =>
    set((s) => ({ provider: { ...s.provider, ...patch } })),

  setBackend: (patch) =>
    set((s) => ({ backend: { ...s.backend, ...patch } })),

  addStorageProfile: () =>
    set((s) => ({
      vdc: {
        ...s.vdc,
        storage_profiles: [
          ...s.vdc.storage_profiles,
          { ...defaultStorageProfile, default: false },
        ],
      },
    })),

  removeStorageProfile: (index) =>
    set((s) => ({
      vdc: {
        ...s.vdc,
        storage_profiles: s.vdc.storage_profiles.filter((_, i) => i !== index),
      },
    })),

  updateStorageProfile: (index, patch) =>
    set((s) => ({
      vdc: {
        ...s.vdc,
        storage_profiles: s.vdc.storage_profiles.map((sp, i) =>
          i === index ? { ...sp, ...patch } : sp
        ),
      },
    })),

  setOperation: (id, status, error = null) =>
    set({ currentOperationId: id, planStatus: status, planError: error }),

  toggleTerminal: () =>
    set((s) => ({ terminalOpen: !s.terminalOpen })),

  openTerminal: () =>
    set({ terminalOpen: true }),

  resetAll: () =>
    set({
      provider: { ...defaultProvider },
      backend: { ...defaultBackend },
      org: { ...defaultOrg },
      vdc: { ...defaultVdc },
      edge: { ...defaultEdge, subnet: { ...defaultSubnet } },
      network: { ...defaultNetwork },
      vapp: { ...defaultVapp },
      vm: { ...defaultVm },
      currentOperationId: null,
      planStatus: "idle",
      planError: null,
    }),
}));
