import { useMutation, useQuery } from "@tanstack/react-query";
import api from "./client";

/* ------------------------------------------------------------------ */
/*  Cloud-to-cloud migration: NSX-T edge on one VCD → NSX-T on another */
/* ------------------------------------------------------------------ */

export type CloudId = "primary" | "secondary";

export interface CloudInfo {
  id: CloudId;
  label: string;
  url: string;
  configured: boolean;
}

interface MetadataItem {
  id: string;
  name: string;
  vdc_group?: string | null;
}

interface MetadataResponse {
  items: MetadataItem[];
  count: number;
}

const METADATA_STALE = 5 * 60 * 1000;

export function useClouds() {
  return useQuery({
    queryKey: ["cloud-migration", "clouds"],
    queryFn: async () => {
      const { data } = await api.get<{ items: CloudInfo[] }>(
        "/api/v1/cloud-migration/clouds",
      );
      return data.items;
    },
    staleTime: METADATA_STALE,
  });
}

/* Metadata, but scoped to a chosen cloud. The backend keys its Redis
   cache per cloud, and so must the query cache — otherwise switching
   clouds would show the previous one's orgs. */

export function useCloudOrgs(cloud: CloudId | "") {
  return useQuery({
    queryKey: ["metadata", cloud, "orgs"],
    queryFn: async () => {
      const { data } = await api.get<MetadataResponse>(
        `/api/v1/metadata/orgs?cloud=${cloud}`,
      );
      return data.items;
    },
    staleTime: METADATA_STALE,
    enabled: !!cloud,
  });
}

export function useCloudVdcs(cloud: CloudId | "", orgId: string | undefined) {
  return useQuery({
    queryKey: ["metadata", cloud, "vdcs", orgId],
    queryFn: async () => {
      const { data } = await api.get<MetadataResponse>(
        `/api/v1/metadata/orgs/${orgId}/vdcs?cloud=${cloud}`,
      );
      return data.items;
    },
    staleTime: METADATA_STALE,
    enabled: !!cloud && !!orgId,
  });
}

export function useCloudEdges(cloud: CloudId | "", vdcId: string | undefined) {
  return useQuery({
    queryKey: ["metadata", cloud, "edges", vdcId],
    queryFn: async () => {
      const { data } = await api.get<MetadataResponse>(
        `/api/v1/metadata/vdcs/${vdcId}/edge-gateways?cloud=${cloud}`,
      );
      return data.items;
    },
    staleTime: METADATA_STALE,
    enabled: !!cloud && !!vdcId,
  });
}

export interface PreviewRequest {
  source_cloud: CloudId;
  source_org: string;
  source_vdc: string;
  source_vdc_id: string;
  source_edge_id: string;
  source_edge_name?: string;

  target_cloud: CloudId;
  target_org: string;
  target_vdc: string;
  target_vdc_id: string;
  target_edge_id: string;
  target_edge_name?: string;

  /** Old address -> new address, applied to NAT rules and IP sets. */
  ip_mapping?: Record<string, string>;
}

export interface AddressUse {
  address: string;
  kind: "external" | "ip_set" | "internal" | "route";
  occurrences: number;
  used_by: string[];
}

export interface PreviewResponse {
  hcl: string;
  summary: Record<string, number>;
  warnings: string[];
  spec: unknown;
  addresses: AddressUse[];
}

export function useCloudMigrationPreview() {
  return useMutation({
    mutationFn: async (body: PreviewRequest) => {
      const { data } = await api.post<PreviewResponse>(
        "/api/v1/cloud-migration/preview",
        body,
      );
      return data;
    },
  });
}

/* ------------------------------------------------------------------ */
/*  Terraform against the destination cloud                            */
/* ------------------------------------------------------------------ */

export interface PlanRequest {
  target_cloud: CloudId;
  target_org: string;
  target_vdc: string;
  target_edge_id: string;
  target_edge_name?: string;
  hcl: string;
}

export interface ApplyRequest {
  target_cloud: CloudId;
  target_org: string;
  plan_operation_id: string;
}

interface OperationStarted {
  operation_id: string;
}

export function useCloudMigrationPlan() {
  return useMutation({
    mutationFn: async (body: PlanRequest) => {
      const { data } = await api.post<OperationStarted>(
        "/api/v1/cloud-migration/plan",
        body,
      );
      return data;
    },
  });
}

export function useCloudMigrationApply() {
  return useMutation({
    mutationFn: async (body: ApplyRequest) => {
      const { data } = await api.post<OperationStarted>(
        "/api/v1/cloud-migration/apply",
        body,
      );
      return data;
    },
  });
}
