import { useQuery, useMutation } from "@tanstack/react-query";
import api from "./client";

/* ------------------------------------------------------------------ */
/*  Generic response shape from all /api/v1/metadata/* endpoints       */
/* ------------------------------------------------------------------ */

interface MetadataResponse<T> {
  items: T[];
  count: number;
}

/* ------------------------------------------------------------------ */
/*  Item types (mirror backend Pydantic schemas)                       */
/* ------------------------------------------------------------------ */

export interface OrgItem {
  name: string;
  display_name: string;
  is_enabled: boolean;
}

export interface ProviderVdcItem {
  name: string;
  is_enabled: boolean;
  cpu_allocated_mhz: number | null;
  memory_allocated_mb: number | null;
}

export interface VdcItem {
  name: string;
  org_name: string;
  allocation_model: string | null;
  is_enabled: boolean;
}

export interface StorageProfileItem {
  name: string;
  limit_mb: number | null;
  used_mb: number | null;
  is_default: boolean;
}

export interface EdgeGatewayItem {
  name: string;
  org_name: string;
  vdc_name: string;
  gateway_type: string | null;
}

export interface NetworkPoolItem {
  name: string;
  id: string;
  poolType: string;
  description: string | null;
}

export interface ExternalNetworkItem {
  name: string;
  description: string | null;
}

/* ------------------------------------------------------------------ */
/*  Shared query config — 5 min staleTime to match backend cache TTL  */
/* ------------------------------------------------------------------ */

const METADATA_STALE = 5 * 60 * 1000;

/* ------------------------------------------------------------------ */
/*  Hooks                                                              */
/* ------------------------------------------------------------------ */

export function useOrganizations() {
  return useQuery({
    queryKey: ["metadata", "organizations"],
    queryFn: async () => {
      const { data } = await api.get<MetadataResponse<OrgItem>>(
        "/api/v1/metadata/organizations"
      );
      return data.items;
    },
    staleTime: METADATA_STALE,
  });
}

export function useProviderVdcs() {
  return useQuery({
    queryKey: ["metadata", "provider-vdcs"],
    queryFn: async () => {
      const { data } = await api.get<MetadataResponse<ProviderVdcItem>>(
        "/api/v1/metadata/provider-vdcs"
      );
      return data.items;
    },
    staleTime: METADATA_STALE,
  });
}

export function useVdcs(org?: string) {
  return useQuery({
    queryKey: ["metadata", "vdcs", org],
    queryFn: async () => {
      const { data } = await api.get<MetadataResponse<VdcItem>>(
        "/api/v1/metadata/vdcs",
        { params: org ? { org } : {} }
      );
      return data.items;
    },
    staleTime: METADATA_STALE,
    enabled: !!org,
  });
}

export function useStorageProfiles(pvdc?: string) {
  return useQuery({
    queryKey: ["metadata", "storage-profiles", pvdc],
    queryFn: async () => {
      const { data } = await api.get<MetadataResponse<StorageProfileItem>>(
        "/api/v1/metadata/storage-profiles",
        { params: pvdc ? { pvdc } : {} }
      );
      return data.items;
    },
    staleTime: METADATA_STALE,
    enabled: !!pvdc,
  });
}

export function useNetworkPools(pvdc?: string) {
  return useQuery({
    queryKey: ["metadata", "network-pools", pvdc],
    queryFn: async () => {
      const { data } = await api.get<MetadataResponse<NetworkPoolItem>>(
        "/api/v1/metadata/network-pools",
        { params: pvdc ? { pvdc } : {} }
      );
      return data.items;
    },
    staleTime: METADATA_STALE,
    enabled: !!pvdc,
  });
}

export function useEdgeGateways(org?: string, vdc?: string) {
  return useQuery({
    queryKey: ["metadata", "edge-gateways", org, vdc],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (org) params.org = org;
      if (vdc) params.vdc = vdc;
      const { data } = await api.get<MetadataResponse<EdgeGatewayItem>>(
        "/api/v1/metadata/edge-gateways",
        { params }
      );
      return data.items;
    },
    staleTime: METADATA_STALE,
    enabled: !!org,
  });
}

export function useExternalNetworks() {
  return useQuery({
    queryKey: ["metadata", "external-networks"],
    queryFn: async () => {
      const { data } = await api.get<MetadataResponse<ExternalNetworkItem>>(
        "/api/v1/metadata/external-networks"
      );
      return data.items;
    },
    staleTime: METADATA_STALE,
  });
}

/* ------------------------------------------------------------------ */
/*  Terraform execution mutations                                      */
/* ------------------------------------------------------------------ */

interface PlanResponse {
  operation_id: string;
}

interface ApplyResponse {
  operation_id: string;
}

interface DestroyResponse {
  operation_id: string;
}

export function usePlan() {
  return useMutation({
    mutationFn: async (config: Record<string, unknown>) => {
      const { data } = await api.post<PlanResponse>(
        "/api/v1/terraform/plan",
        { config }
      );
      return data;
    },
  });
}

export function useApply() {
  return useMutation({
    mutationFn: async (operationId: string) => {
      const { data } = await api.post<ApplyResponse>(
        "/api/v1/terraform/apply",
        { operation_id: operationId }
      );
      return data;
    },
  });
}

export function useDestroy() {
  return useMutation({
    mutationFn: async (operationId: string) => {
      const { data } = await api.post<DestroyResponse>(
        "/api/v1/terraform/destroy",
        { operation_id: operationId }
      );
      return data;
    },
  });
}
