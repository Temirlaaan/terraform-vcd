import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "./client";

export interface DriftReportSummary {
  id: string;
  deployment_id: string;
  ran_at: string;
  has_changes: boolean | null;
  additions_count: number;
  modifications_count: number;
  deletions_count: number;
  auto_resolved: boolean;
  resolution: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  error: string | null;
  version_id: string | null;
  version_num: number | null;
}

export interface DriftReportDetail extends DriftReportSummary {
  additions: unknown[];
  modifications: unknown[];
  deletions: unknown[];
}

const KEY = "drift";

export function useDriftReports(deploymentId: string | undefined) {
  return useQuery<DriftReportSummary[]>({
    queryKey: [KEY, deploymentId, "list"],
    queryFn: async () => {
      const { data } = await api.get<DriftReportSummary[]>(
        `/api/v1/deployments/${deploymentId}/drift-reports`,
      );
      return data;
    },
    enabled: !!deploymentId,
    staleTime: 10_000,
  });
}

export function useDriftReport(reportId: string | undefined) {
  return useQuery<DriftReportDetail>({
    queryKey: [KEY, "report", reportId],
    queryFn: async () => {
      const { data } = await api.get<DriftReportDetail>(
        `/api/v1/drift-reports/${reportId}`,
      );
      return data;
    },
    enabled: !!reportId,
  });
}

export function useTriggerDriftCheck(deploymentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post<{
        deployment_id: string;
        triggered: boolean;
        message: string;
      }>(`/api/v1/deployments/${deploymentId}/drift-check`);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [KEY, deploymentId] });
      qc.invalidateQueries({ queryKey: ["deployments", deploymentId] });
      qc.invalidateQueries({ queryKey: ["deployments", deploymentId, "versions"] });
    },
  });
}

export function useReviewDriftReport(deploymentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      reportId,
      resolution,
    }: {
      reportId: string;
      resolution: "accepted" | "rolled_back" | "ignored";
    }) => {
      const { data } = await api.post<DriftReportSummary>(
        `/api/v1/drift-reports/${reportId}/review`,
        { resolution },
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [KEY, deploymentId] });
      qc.invalidateQueries({ queryKey: ["deployments", deploymentId] });
    },
  });
}
