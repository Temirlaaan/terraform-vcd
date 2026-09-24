import { useQuery } from "@tanstack/react-query";
import api from "./client";

interface MetadataItem {
  id: string;
  name: string;
  /** Set on edges owned by a data center group rather than the VDC. */
  vdc_group?: string | null;
}

/** An edge shared through a data center group says so in the picker. */
export function edgeLabel(e: MetadataItem): string {
  return e.vdc_group ? `${e.name}  (DCG: ${e.vdc_group})` : e.name;
}

interface MetadataResponse {
  items: MetadataItem[];
  count: number;
}

const METADATA_STALE = 5 * 60 * 1000;

export function useOrgs() {
  return useQuery({
    queryKey: ["metadata", "orgs"],
    queryFn: async () => {
      const { data } = await api.get<MetadataResponse>(
        "/api/v1/metadata/orgs"
      );
      return data.items;
    },
    staleTime: METADATA_STALE,
  });
}

export function useVdcsByOrg(orgId: string | undefined) {
  return useQuery({
    queryKey: ["metadata", "vdcs-by-org", orgId],
    queryFn: async () => {
      const { data } = await api.get<MetadataResponse>(
        `/api/v1/metadata/orgs/${orgId}/vdcs`
      );
      return data.items;
    },
    staleTime: METADATA_STALE,
    enabled: !!orgId,
  });
}

export function useEdgeGatewaysByVdc(vdcId: string | undefined) {
  return useQuery({
    queryKey: ["metadata", "edge-gateways-by-vdc", vdcId],
    queryFn: async () => {
      const { data } = await api.get<MetadataResponse>(
        `/api/v1/metadata/vdcs/${vdcId}/edge-gateways`
      );
      return data.items;
    },
    staleTime: METADATA_STALE,
    enabled: !!vdcId,
  });
}

export function useEdgeClustersByVdc(vdcId: string | undefined) {
  return useQuery({
    queryKey: ["metadata", "edge-clusters-by-vdc", vdcId],
    queryFn: async () => {
      const { data } = await api.get<MetadataResponse>(
        `/api/v1/metadata/vdcs/${vdcId}/edge-clusters`
      );
      return data.items;
    },
    staleTime: METADATA_STALE,
    enabled: !!vdcId,
  });
}
