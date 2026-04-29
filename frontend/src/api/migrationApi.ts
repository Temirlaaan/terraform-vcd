import { useMutation } from "@tanstack/react-query";
import api from "./client";

export interface MigrationRequest {
  // host + api_token are accepted for backwards compatibility, but the
  // browser path always uses `handle` (Redis-backed, ~10 min TTL) so
  // the System-Administrator-scoped legacy-VCD token never lives in
  // sessionStorage. H3-FE.
  host?: string;
  api_token?: string;
  handle?: string;
  edge_uuid: string;
  target_org: string;
  target_vdc: string;
  target_vdc_id: string;
  target_edge_id: string;
  verify_ssl: boolean;
}

export interface AuthHandleRequest {
  host: string;
  api_token: string;
}

export interface AuthHandleResponse {
  handle: string;
  expires_in: number;
}

export function useAuthHandle() {
  return useMutation({
    mutationFn: async (req: AuthHandleRequest) => {
      const { data } = await api.post<AuthHandleResponse>(
        "/api/v1/migration/auth-handle",
        req,
      );
      return data;
    },
  });
}

export interface MigrationSummary {
  firewall_rules_total: number;
  firewall_rules_user: number;
  firewall_rules_system: number;
  nat_rules_total: number;
  app_port_profiles_total: number;
  app_port_profiles_system: number;
  app_port_profiles_custom: number;
  static_routes_total: number;
}

export interface MigrationResponse {
  hcl: string;
  edge_name: string;
  summary: MigrationSummary;
}

export function useMigrationGenerate() {
  return useMutation({
    mutationFn: async (req: MigrationRequest) => {
      const { data } = await api.post<MigrationResponse>(
        "/api/v1/migration/generate",
        req
      );
      return data;
    },
  });
}

/* ------------------------------------------------------------------ */
/*  Plan / Apply mutations                                             */
/* ------------------------------------------------------------------ */

interface MigrationPlanRequest {
  hcl: string;
  target_org: string;
  target_edge_id: string;
  source_edge_name?: string;
  target_vdc?: string;
  target_edge_name?: string;
  source_host?: string;
  source_edge_uuid?: string;
  verify_ssl?: boolean;
  summary?: MigrationSummary;
}

interface MigrationOperationResponse {
  operation_id: string;
}

export function useMigrationPlan() {
  return useMutation({
    mutationFn: async (req: MigrationPlanRequest) => {
      const { data } = await api.post<MigrationOperationResponse>(
        "/api/v1/migration/plan",
        req
      );
      return data;
    },
  });
}

export function useMigrationApply() {
  return useMutation({
    mutationFn: async (operationId: string) => {
      const { data } = await api.post<MigrationOperationResponse>(
        "/api/v1/migration/apply",
        { operation_id: operationId }
      );
      return data;
    },
  });
}
