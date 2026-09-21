import { useMutation } from "@tanstack/react-query";
import api from "./client";
import type { CloudId } from "./cloudMigrationApi";

/* ------------------------------------------------------------------ */
/*  IPsec tunnel migration: legacy NSX-V edge → NSX-T edge             */
/* ------------------------------------------------------------------ */

/** Where tunnels come from and where they are going.
 *  `handle` is preferred: the raw legacy-VCD token then never reaches
 *  browser storage. */
export interface SourceTarget {
  handle?: string;
  host?: string;
  api_token?: string;
  source_edge_uuid: string;
  verify_ssl?: boolean;

  /** Tunnels can land on either configured VCD, not only the primary. */
  target_cloud: CloudId;
  target_org: string;
  target_vdc: string;
  target_vdc_id: string;
  target_edge_id: string;
}

/** One tunnel as the backend describes it.
 *  There is deliberately no pre-shared key here — only whether one could
 *  be read. The key is re-read server-side at plan time. */
export interface IpsecTunnel {
  name: string;
  slug: string | null;
  enabled_on_source: boolean;
  local_ip: string;
  peer_ip: string;
  remote_id: string | null;
  local_networks: string[];
  remote_networks: string[];
  encryption: string | null;
  digest: string | null;
  dh_group: string | null;
  ike_version: string | null;
  pfs: boolean;
  psk_readable: boolean;
  migratable: boolean;
  unsupported: string[];
}

export interface IpsecPreview {
  hcl: string;
  tunnels: IpsecTunnel[];
  total: number;
  migratable: number;
  skipped: number;
  warnings: string[];
}

interface OperationStarted {
  operation_id: string;
}

export function useIpsecPreview() {
  return useMutation({
    mutationFn: async (body: SourceTarget) => {
      const { data } = await api.post<IpsecPreview>(
        "/api/v1/ipsec-migration/preview",
        body,
      );
      return data;
    },
  });
}

export function useIpsecPlan() {
  return useMutation({
    mutationFn: async (body: SourceTarget) => {
      const { data } = await api.post<OperationStarted>(
        "/api/v1/ipsec-migration/plan",
        body,
      );
      return data;
    },
  });
}

export function useIpsecApply() {
  return useMutation({
    mutationFn: async (body: {
      target_cloud: CloudId;
      target_org: string;
      plan_operation_id: string;
    }) => {
      const { data } = await api.post<OperationStarted>(
        "/api/v1/ipsec-migration/apply",
        body,
      );
      return data;
    },
  });
}
