/**
 * API client + types for the manual deployment editor.
 *
 * Mirrors `app.schemas.deployment_spec` on the backend. Kept separate
 * from `deploymentsApi.ts` because it is editor-specific and the rule
 * shapes are much larger than the deployment CRUD surface.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "./client";
import type { Deployment } from "./deploymentsApi";

export interface TargetSpec {
  org: string;
  vdc: string;
  vdc_id: string;
  edge_id: string;
  edge_name?: string | null;
}

export interface IpSetSpec {
  name: string;
  description: string;
  ip_addresses: string[];
}

export type AppPortProtocol = "TCP" | "UDP" | "ICMPv4" | "ICMPv6";

export interface AppPortEntry {
  protocol: AppPortProtocol;
  ports: string[];
}

export type AppPortProfileScope = "TENANT" | "PROVIDER" | "SYSTEM";

export interface AppPortProfileSpec {
  name: string;
  description: string;
  scope: AppPortProfileScope;
  app_ports: AppPortEntry[];
}

export type FirewallAction = "ALLOW" | "DROP" | "REJECT";
export type FirewallDirection = "IN" | "OUT" | "IN_OUT";
export type FirewallIpProtocol = "IPV4" | "IPV6" | "IPV4_IPV6";

export interface FirewallRuleSpec {
  name: string;
  action: FirewallAction;
  direction: FirewallDirection;
  ip_protocol: FirewallIpProtocol;
  enabled: boolean;
  logging: boolean;
  source_ip_set_names: string[];
  destination_ip_set_names: string[];
  app_port_profile_names: string[];
}

export type NatRuleType =
  | "DNAT"
  | "SNAT"
  | "REFLEXIVE"
  | "NO_DNAT"
  | "NO_SNAT";

export type NatFirewallMatch =
  | "MATCH_INTERNAL_ADDRESS"
  | "MATCH_EXTERNAL_ADDRESS"
  | "BYPASS";

export interface NatRuleSpec {
  name: string;
  rule_type: NatRuleType;
  description: string;
  external_address: string;
  internal_address: string;
  dnat_external_port: string;
  snat_destination_address: string;
  app_port_profile_name: string | null;
  enabled: boolean;
  logging: boolean;
  priority: number;
  firewall_match: NatFirewallMatch;
}

export interface NextHopSpec {
  ip_address: string;
  admin_distance: number;
}

export interface StaticRouteSpec {
  name: string;
  description: string;
  network_cidr: string;
  next_hops: NextHopSpec[];
}

export interface DeploymentSpec {
  target: TargetSpec;
  ip_sets: IpSetSpec[];
  app_port_profiles: AppPortProfileSpec[];
  firewall_rules: FirewallRuleSpec[];
  nat_rules: NatRuleSpec[];
  static_routes: StaticRouteSpec[];
}

export interface EditorData {
  deployment_id: string;
  kind: string;
  has_state: boolean;
  spec: DeploymentSpec;
}

export function emptySpec(target: TargetSpec): DeploymentSpec {
  return {
    target,
    ip_sets: [],
    app_port_profiles: [],
    firewall_rules: [],
    nat_rules: [],
    static_routes: [],
  };
}

export function useEditorData(id: string | undefined) {
  return useQuery<EditorData>({
    queryKey: ["deployment", id, "editor-data"],
    queryFn: async () => {
      const { data } = await api.get<EditorData>(
        `/api/v1/deployments/${id}/editor-data`
      );
      return data;
    },
    enabled: !!id,
    staleTime: 0,
  });
}

export interface DeploymentManualCreateBody {
  name: string;
  description?: string | null;
  spec: DeploymentSpec;
}

export function useCreateManualDeployment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: DeploymentManualCreateBody) => {
      const { data } = await api.post<Deployment>(
        "/api/v1/deployments/manual",
        body
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["deployments"] });
    },
  });
}

export function useUpdateDeploymentSpec(id: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (spec: DeploymentSpec) => {
      const { data } = await api.put<Deployment>(
        `/api/v1/deployments/${id}/spec`,
        { spec }
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["deployments"] });
      if (id) {
        qc.invalidateQueries({ queryKey: ["deployment", id] });
        qc.invalidateQueries({
          queryKey: ["deployment", id, "editor-data"],
        });
      }
    },
  });
}
