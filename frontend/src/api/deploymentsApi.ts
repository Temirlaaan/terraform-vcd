import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "./client";
import type { MigrationSummary } from "./migrationApi";

export interface DeploymentListItem {
  id: string;
  name: string;
  kind: string;
  description: string | null;
  source_edge_name: string;
  target_org: string;
  target_vdc: string;
  target_edge_name?: string | null;
  summary: MigrationSummary;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface Deployment extends DeploymentListItem {
  source_host: string;
  source_edge_uuid: string;
  verify_ssl: boolean;
  target_vdc_id: string;
  target_edge_id: string;
  hcl: string;
  needs_review?: boolean;
  last_drift_check?: string | null;
}

export interface DeploymentList {
  items: DeploymentListItem[];
  total: number;
}

export interface DeploymentCreate {
  name: string;
  description?: string | null;
  source_host: string;
  source_edge_uuid: string;
  source_edge_name: string;
  verify_ssl: boolean;
  target_org: string;
  target_vdc: string;
  target_vdc_id: string;
  target_edge_id: string;
  target_edge_name?: string | null;
  hcl: string;
  summary: MigrationSummary;
}

export interface DeploymentUpdate {
  name?: string;
  description?: string | null;
}

export interface TargetCheckResponse {
  ip_sets_count: number;
  nat_rules_count: number;
  firewall_rules_count: number;
  static_routes_count: number;
}

const LIST_KEY = "deployments";

export function useDeployments(targetEdgeId?: string) {
  return useQuery<DeploymentList>({
    queryKey: [LIST_KEY, { target_edge_id: targetEdgeId ?? null }],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (targetEdgeId) params.target_edge_id = targetEdgeId;
      const { data } = await api.get<DeploymentList>("/api/v1/deployments", {
        params,
      });
      return data;
    },
  });
}

export function useDeployment(id: string | undefined) {
  return useQuery<Deployment>({
    queryKey: [LIST_KEY, id],
    queryFn: async () => {
      const { data } = await api.get<Deployment>(`/api/v1/deployments/${id}`);
      return data;
    },
    enabled: !!id,
  });
}

export function useCreateDeployment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: DeploymentCreate) => {
      const { data } = await api.post<Deployment>(
        "/api/v1/deployments",
        body,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [LIST_KEY] });
    },
  });
}

export function useUpdateDeployment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      patch,
    }: {
      id: string;
      patch: DeploymentUpdate;
    }) => {
      const { data } = await api.patch<Deployment>(
        `/api/v1/deployments/${id}`,
        patch,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [LIST_KEY] });
    },
  });
}

export function useDeleteDeployment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/api/v1/deployments/${id}`);
      return id;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [LIST_KEY] });
    },
  });
}

export function useTargetCheck() {
  return useMutation({
    mutationFn: async (targetEdgeId: string) => {
      const { data } = await api.get<TargetCheckResponse>(
        "/api/v1/migration/target-check",
        { params: { edge_id: targetEdgeId } },
      );
      return data;
    },
  });
}

/* ------------------------------------------------------------------ */
/*  Phase 3 — Version history                                         */
/*  Phase 5 — Rollback                                                */
/*  HCL editor (live deployment edit)                                 */
/* ------------------------------------------------------------------ */

export interface DeploymentVersion {
  version_num: number;
  source: string;
  label: string | null;
  is_pinned: boolean;
  state_hash: string;
  hcl_key: string;
  state_key: string;
  created_at: string;
  created_by: string;
}

export interface VersionList {
  items: DeploymentVersion[];
  total: number;
}

export function useDeploymentVersions(id: string | undefined) {
  return useQuery<VersionList>({
    queryKey: [LIST_KEY, id, "versions"],
    queryFn: async () => {
      const { data } = await api.get<VersionList>(
        `/api/v1/deployments/${id}/versions`,
      );
      return data;
    },
    enabled: !!id,
    staleTime: 10_000,
  });
}

export interface OperationIdResponse {
  operation_id: string;
}

export function useRollbackPrepare(deploymentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (version_num: number) => {
      const { data } = await api.post<OperationIdResponse>(
        `/api/v1/deployments/${deploymentId}/rollback/prepare`,
        { version_num },
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [LIST_KEY, deploymentId, "versions"] });
    },
  });
}

export function useRollbackConfirm(deploymentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (prepareOpId: string) => {
      const { data } = await api.post<OperationIdResponse>(
        `/api/v1/deployments/${deploymentId}/rollback/${prepareOpId}/confirm`,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [LIST_KEY, deploymentId, "versions"] });
    },
  });
}

export function usePinVersion(deploymentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      versionNum,
      pinned,
    }: {
      versionNum: number;
      pinned: boolean;
    }) => {
      const action = pinned ? "pin" : "unpin";
      const { data } = await api.post<DeploymentVersion>(
        `/api/v1/deployments/${deploymentId}/versions/${versionNum}/${action}`,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [LIST_KEY, deploymentId, "versions"] });
    },
  });
}

export function useDeploymentHcl(id: string | undefined) {
  return useQuery<string>({
    queryKey: [LIST_KEY, id, "hcl"],
    queryFn: async () => {
      const { data } = await api.get<string>(
        `/api/v1/deployments/${id}/hcl`,
        { transformResponse: (d) => d },
      );
      return data;
    },
    enabled: !!id,
  });
}

export function useDeploymentPlan(deploymentId: string) {
  return useMutation({
    mutationFn: async (hcl: string) => {
      const { data } = await api.post<OperationIdResponse>(
        `/api/v1/deployments/${deploymentId}/plan`,
        { hcl },
      );
      return data;
    },
  });
}

export function useDeploymentApply(deploymentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (operation_id: string) => {
      const { data } = await api.post<OperationIdResponse>(
        `/api/v1/deployments/${deploymentId}/apply`,
        { operation_id },
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [LIST_KEY, deploymentId, "versions"] });
      qc.invalidateQueries({ queryKey: [LIST_KEY, deploymentId, "hcl"] });
    },
  });
}

export function useVersionHcl(
  deploymentId: string | undefined,
  versionNum: number | undefined,
) {
  return useQuery<string>({
    queryKey: [LIST_KEY, deploymentId, "version-hcl", versionNum],
    queryFn: async () => {
      const { data } = await api.get<string>(
        `/api/v1/deployments/${deploymentId}/versions/${versionNum}/hcl`,
        { transformResponse: (d) => d },
      );
      return data;
    },
    enabled: !!deploymentId && versionNum !== undefined,
    staleTime: 5 * 60 * 1000,
  });
}

export function useVersionState(
  deploymentId: string | undefined,
  versionNum: number | undefined,
  enabled: boolean = true,
) {
  return useQuery<unknown>({
    queryKey: [LIST_KEY, deploymentId, "version-state", versionNum],
    queryFn: async () => {
      const { data } = await api.get<unknown>(
        `/api/v1/deployments/${deploymentId}/versions/${versionNum}/state`,
      );
      return data;
    },
    enabled: !!deploymentId && versionNum !== undefined && enabled,
    staleTime: 5 * 60 * 1000,
  });
}
