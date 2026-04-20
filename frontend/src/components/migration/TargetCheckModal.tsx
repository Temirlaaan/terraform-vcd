import { useEffect } from "react";
import {
  X,
  Loader2,
  AlertCircle,
  ShieldCheck,
  AlertTriangle,
  ArrowRight,
} from "lucide-react";
import { isAxiosError } from "axios";
import {
  useTargetCheck,
  type TargetCheckResponse,
} from "@/api/deploymentsApi";

interface TargetCheckModalProps {
  targetEdgeId: string;
  onCancel: () => void;
  onConfirm: () => void;
}

function getErrorMessage(error: unknown): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return "Failed to check the target edge gateway.";
}

function sum(data: TargetCheckResponse): number {
  return (
    data.ip_sets_count +
    data.nat_rules_count +
    data.firewall_rules_count +
    data.static_routes_count
  );
}

export function TargetCheckModal({
  targetEdgeId,
  onCancel,
  onConfirm,
}: TargetCheckModalProps) {
  const check = useTargetCheck();

  useEffect(() => {
    check.mutate(targetEdgeId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetEdgeId]);

  const data = check.data;
  const nonEmpty = data ? sum(data) > 0 : false;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-sm bg-white border border-clr-border shadow-lg">
        <div className="flex items-center justify-between px-4 py-3 border-b border-clr-border">
          <h3 className="text-sm font-semibold text-clr-text">
            Target edge gateway check
          </h3>
          <button
            onClick={onCancel}
            className="text-clr-placeholder hover:text-clr-text"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-4 space-y-3">
          <p className="text-xs text-clr-text-secondary">
            Inspecting existing configuration on the target NSX-T edge before
            running <strong>Plan</strong>.
          </p>

          {check.isPending && (
            <div className="flex items-center gap-2 rounded-sm border border-clr-border bg-clr-near-white p-3">
              <Loader2 className="h-4 w-4 text-clr-action animate-spin flex-none" />
              <p className="text-xs text-clr-text">
                Fetching counts from the target edge...
              </p>
            </div>
          )}

          {check.isError && (
            <div className="flex items-start gap-2 rounded-sm border border-clr-danger/30 bg-red-50 p-2">
              <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
              <p className="text-xs text-clr-danger break-words">
                {getErrorMessage(check.error)}
              </p>
            </div>
          )}

          {data && (
            <>
              <div
                className={
                  nonEmpty
                    ? "flex items-start gap-2 rounded-sm border border-amber-200 bg-amber-50 p-3"
                    : "flex items-start gap-2 rounded-sm border border-emerald-200 bg-emerald-50 p-3"
                }
              >
                {nonEmpty ? (
                  <AlertTriangle className="h-4 w-4 text-amber-600 flex-none mt-0.5" />
                ) : (
                  <ShieldCheck className="h-4 w-4 text-emerald-600 flex-none mt-0.5" />
                )}
                <p
                  className={
                    nonEmpty
                      ? "text-xs text-amber-800 leading-relaxed"
                      : "text-xs text-emerald-800 leading-relaxed"
                  }
                >
                  {nonEmpty
                    ? "Target edge already has configuration. Plan will add new resources alongside existing ones — review carefully before applying."
                    : "Target edge is clean. Safe to proceed."}
                </p>
              </div>

              <dl className="grid grid-cols-2 gap-2 text-xs">
                <div className="flex items-center justify-between rounded-sm border border-clr-border bg-white px-2.5 py-1.5">
                  <dt className="text-clr-text-secondary">IP sets</dt>
                  <dd className="font-semibold text-clr-text">
                    {data.ip_sets_count}
                  </dd>
                </div>
                <div className="flex items-center justify-between rounded-sm border border-clr-border bg-white px-2.5 py-1.5">
                  <dt className="text-clr-text-secondary">NAT rules</dt>
                  <dd className="font-semibold text-clr-text">
                    {data.nat_rules_count}
                  </dd>
                </div>
                <div className="flex items-center justify-between rounded-sm border border-clr-border bg-white px-2.5 py-1.5">
                  <dt className="text-clr-text-secondary">Firewall rules</dt>
                  <dd className="font-semibold text-clr-text">
                    {data.firewall_rules_count}
                  </dd>
                </div>
                <div className="flex items-center justify-between rounded-sm border border-clr-border bg-white px-2.5 py-1.5">
                  <dt className="text-clr-text-secondary">Static routes</dt>
                  <dd className="font-semibold text-clr-text">
                    {data.static_routes_count}
                  </dd>
                </div>
              </dl>
            </>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-clr-border bg-clr-near-white">
          <button
            onClick={onCancel}
            className="rounded-sm px-3 py-1.5 text-xs text-clr-text-secondary hover:text-clr-text"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={check.isPending || check.isError}
            className="flex items-center gap-1.5 rounded-sm bg-clr-action text-white text-xs font-medium px-3 py-1.5 hover:bg-clr-action-hover disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Proceed to Plan
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
