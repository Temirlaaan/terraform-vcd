import { Play, Rocket, Loader2, AlertCircle } from "lucide-react";
import { cn } from "@/utils/cn";
import { useConfigStore } from "@/store/useConfigStore";
import { useMigrationPlan, useMigrationApply } from "@/api/migrationApi";

interface MigrationActionBarProps {
  hcl: string;
  targetOrg: string;
  targetEdgeId: string;
}

export function MigrationActionBar({
  hcl,
  targetOrg,
  targetEdgeId,
}: MigrationActionBarProps) {
  const planStatus = useConfigStore((s) => s.planStatus);
  const planError = useConfigStore((s) => s.planError);
  const currentOperationId = useConfigStore((s) => s.currentOperationId);
  const setOperation = useConfigStore((s) => s.setOperation);
  const openTerminal = useConfigStore((s) => s.openTerminal);

  const planMutation = useMigrationPlan();
  const applyMutation = useMigrationApply();

  const canPlan =
    hcl.length > 0 &&
    planStatus !== "planning" &&
    planStatus !== "applying";
  const canApply =
    planStatus === "planned" &&
    currentOperationId !== null &&
    !applyMutation.isPending;

  const handlePlan = () => {
    setOperation(null, "planning");
    openTerminal();

    planMutation.mutate(
      { hcl, target_org: targetOrg, target_edge_id: targetEdgeId },
      {
        onSuccess: (data) => {
          setOperation(data.operation_id, "planning");
          openTerminal();
        },
        onError: (err) => {
          const resp = (err as { response?: { data?: { detail?: unknown } } })
            .response?.data;
          let message: string;
          if (resp?.detail) {
            message =
              typeof resp.detail === "string"
                ? resp.detail
                : JSON.stringify(resp.detail);
          } else {
            message = (err as Error).message;
          }
          setOperation(null, "error", message);
        },
      }
    );
  };

  const handleApply = () => {
    if (!currentOperationId) return;
    setOperation(currentOperationId, "applying");
    openTerminal();

    applyMutation.mutate(currentOperationId, {
      onSuccess: (data) => {
        setOperation(data.operation_id, "applying");
        openTerminal();
      },
      onError: (err) => {
        const message =
          (err as { response?: { data?: { detail?: string } } }).response?.data
            ?.detail ?? (err as Error).message;
        setOperation(currentOperationId, "error", message);
      },
    });
  };

  return (
    <div className="flex-none border-b border-clr-border px-4 py-3 space-y-2">
      {/* Error banner */}
      {planError && (
        <div className="flex items-start gap-2 rounded-sm bg-red-50 border border-clr-danger/30 px-3 py-2">
          <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
          <p className="text-xs text-clr-danger break-all">{planError}</p>
        </div>
      )}

      {/* Buttons */}
      <div className="flex gap-2">
        <button
          onClick={handlePlan}
          disabled={!canPlan}
          className={cn(
            "flex-1 flex items-center justify-center gap-2 rounded-sm px-4 py-2 text-sm font-medium transition-colors",
            "focus:ring-2 focus:ring-clr-action/50 focus:outline-none",
            canPlan
              ? "bg-clr-action hover:bg-clr-action-hover text-white"
              : "bg-clr-light-gray text-clr-placeholder cursor-not-allowed"
          )}
        >
          {planStatus === "planning" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          {planStatus === "planning" ? "Planning..." : "Plan"}
        </button>

        <button
          onClick={handleApply}
          disabled={!canApply}
          className={cn(
            "flex-1 flex items-center justify-center gap-2 rounded-sm px-4 py-2 text-sm font-medium transition-colors",
            "focus:ring-2 focus:ring-clr-success/50 focus:outline-none",
            canApply
              ? "bg-clr-success hover:bg-[#568f1c] text-white"
              : "bg-clr-light-gray text-clr-placeholder cursor-not-allowed"
          )}
        >
          {planStatus === "applying" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Rocket className="h-4 w-4" />
          )}
          {planStatus === "applying" ? "Applying..." : "Apply"}
        </button>
      </div>

      {/* Status hints */}
      {planStatus === "planned" && (
        <p className="text-[11px] text-clr-success text-center">
          Plan succeeded — review output, then apply.
        </p>
      )}
      {planStatus === "applied" && (
        <p className="text-[11px] text-clr-success text-center">
          Apply completed successfully.
        </p>
      )}
    </div>
  );
}
