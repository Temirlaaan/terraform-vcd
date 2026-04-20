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
