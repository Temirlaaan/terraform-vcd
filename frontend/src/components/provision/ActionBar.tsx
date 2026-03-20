import {
  Play,
  Rocket,
  Trash2,
  Loader2,
  AlertCircle,
} from "lucide-react";
import { cn } from "@/utils/cn";
import { useConfigStore } from "@/store/useConfigStore";
import { usePlan, useApply, useDestroy } from "@/api/hooks";

export function ActionBar() {
  const org = useConfigStore((s) => s.org);
  const vdc = useConfigStore((s) => s.vdc);
  const edge = useConfigStore((s) => s.edge);
  const network = useConfigStore((s) => s.network);
  const vapp = useConfigStore((s) => s.vapp);
  const vm = useConfigStore((s) => s.vm);
  const provider = useConfigStore((s) => s.provider);
  const backend = useConfigStore((s) => s.backend);
  const planStatus = useConfigStore((s) => s.planStatus);
  const planError = useConfigStore((s) => s.planError);
  const currentOperationId = useConfigStore((s) => s.currentOperationId);
  const setOperation = useConfigStore((s) => s.setOperation);
  const openTerminal = useConfigStore((s) => s.openTerminal);

  const planMutation = usePlan();
  const applyMutation = useApply();
  const destroyMutation = useDestroy();

  const canPlan = org.name.length > 0 && planStatus !== "planning" && planStatus !== "applying" && planStatus !== "destroying";
  const canApply = planStatus === "planned" && currentOperationId !== null && !applyMutation.isPending;
  const canDestroy = planStatus === "applied" && currentOperationId !== null && !destroyMutation.isPending;

  const handlePlan = () => {
    const config: Record<string, unknown> = { provider, backend };
    if (org.name) config.org = org;
    if (vdc.name && vdc.provider_vdc_name) {
      const filteredVdc = {
        ...vdc,
        storage_profiles: vdc.storage_profiles.filter((sp) => sp.name),
      };
      config.vdc = filteredVdc;
    }
    if (edge.name) config.edge = edge;
    if (network.name) config.network = network;
    if (vapp.name) config.vapp = vapp;
    if (vm.name && vm.catalog_name && vm.template_name) config.vm = vm;
    setOperation(null, "planning");
    openTerminal();

    planMutation.mutate(config, {
      onSuccess: (data) => {
        setOperation(data.operation_id, "planning");
        openTerminal();
      },
      onError: (err) => {
        const resp = (err as { response?: { data?: { detail?: unknown } } }).response?.data;
        let message: string;
        if (resp?.detail) {
          message = typeof resp.detail === "string"
            ? resp.detail
            : JSON.stringify(resp.detail);
        } else {
          message = (err as Error).message;
        }
        setOperation(null, "error", message);
      },
    });
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
          (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
          (err as Error).message;
        setOperation(currentOperationId, "error", message);
      },
    });
  };

  const handleDestroy = () => {
    if (!currentOperationId) return;
    setOperation(currentOperationId, "destroying");
    openTerminal();

    destroyMutation.mutate(currentOperationId, {
      onSuccess: (data) => {
        setOperation(data.operation_id, "destroying");
        openTerminal();
      },
      onError: (err) => {
        const message =
          (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
          (err as Error).message;
        setOperation(currentOperationId, "error", message);
      },
    });
  };

  return (
    <div className="flex-none border-t border-clr-border p-4 space-y-3">
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

      {/* Destroy button — visible only after successful apply */}
      {(planStatus === "applied" || planStatus === "destroying" || planStatus === "destroyed") && (
        <button
          onClick={handleDestroy}
          disabled={!canDestroy}
          className={cn(
            "w-full flex items-center justify-center gap-2 rounded-sm px-4 py-2 text-sm font-medium transition-colors",
            "focus:ring-2 focus:ring-clr-danger/50 focus:outline-none",
            canDestroy
              ? "bg-clr-danger hover:bg-[#a81b00] text-white"
              : "bg-clr-light-gray text-clr-placeholder cursor-not-allowed"
          )}
        >
          {planStatus === "destroying" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Trash2 className="h-4 w-4" />
          )}
          {planStatus === "destroying" ? "Destroying..." : "Destroy"}
        </button>
      )}

      {/* Status hint */}
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
      {planStatus === "destroyed" && (
        <p className="text-[11px] text-clr-danger text-center">
          Destroy completed successfully.
        </p>
      )}
    </div>
  );
}
