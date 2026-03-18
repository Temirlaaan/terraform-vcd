import {
  Building2,
  HardDrive,
  Network,
  Wifi,
  Box,
  Monitor,
  ChevronRight,
  RotateCcw,
  Play,
  Rocket,
  Trash2,
  Loader2,
  AlertCircle,
} from "lucide-react";
import { useState, useMemo } from "react";
import { cn } from "@/utils/cn";
import { useConfigStore } from "@/store/useConfigStore";
import { FormInput, FormNumberInput, FormCheckbox, FormSelect } from "./shared";
import type { SelectOption } from "./shared";
import {
  useProviderVdcs,
  useStorageProfiles,
  useNetworkPools,
  usePlan,
  useApply,
  useDestroy,
} from "@/api/hooks";

/* ------------------------------------------------------------------ */
/*  Accordion Section                                                 */
/* ------------------------------------------------------------------ */

function Section({
  title,
  icon: Icon,
  badge,
  defaultOpen = false,
  disabled = false,
  children,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string;
  defaultOpen?: boolean;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  if (disabled) {
    return (
      <div className="border-b border-clr-border opacity-50">
        <div className="flex w-full items-center gap-2.5 px-4 py-3 text-xs font-semibold tracking-wide uppercase text-clr-placeholder cursor-not-allowed">
          <ChevronRight className="h-3.5 w-3.5" />
          <Icon className="h-4 w-4" />
          {title}
          <span className="ml-auto text-[10px] font-normal italic text-clr-placeholder">
            Coming soon
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="border-b border-clr-border">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2.5 px-4 py-3 text-xs font-semibold tracking-wide uppercase text-clr-text-secondary hover:text-clr-text transition-colors"
      >
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 transition-transform",
            open && "rotate-90"
          )}
        />
        <Icon className="h-4 w-4" />
        {title}
        {badge && (
          <span className="ml-auto text-[10px] font-medium text-clr-action bg-[#0079b8]/10 border border-[#0079b8]/20 rounded px-1.5 py-0.5">
            {badge}
          </span>
        )}
      </button>
      {open && <div className="px-4 pb-4 space-y-3">{children}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Organization Section                                              */
/* ------------------------------------------------------------------ */

function OrgSection() {
  const org = useConfigStore((s) => s.org);
  const setOrg = useConfigStore((s) => s.setOrg);

  return (
    <Section
      title="Organization"
      icon={Building2}
      defaultOpen
      badge={org.name ? "1" : undefined}
    >
      <FormInput
        label="Organization Name"
        value={org.name}
        onChange={(v) => setOrg({ name: v })}
        placeholder="Enter new organization name..."
      />
      <FormInput
        label="Full Name"
        value={org.full_name}
        onChange={(v) => setOrg({ full_name: v })}
        placeholder="e.g. Acme Corporation"
      />
      <FormInput
        label="Description"
        value={org.description}
        onChange={(v) => setOrg({ description: v })}
        placeholder="Optional description"
      />
    </Section>
  );
}

/* ------------------------------------------------------------------ */
/*  VDC Section                                                       */
/* ------------------------------------------------------------------ */

function VdcSection() {
  const vdc = useConfigStore((s) => s.vdc);
  const setVdc = useConfigStore((s) => s.setVdc);
  const updateStorageProfile = useConfigStore((s) => s.updateStorageProfile);
  const addStorageProfile = useConfigStore((s) => s.addStorageProfile);
  const removeStorageProfile = useConfigStore((s) => s.removeStorageProfile);

  const { data: pvdcs, isLoading: pvdcsLoading } = useProviderVdcs();
  const { data: storageProfiles } = useStorageProfiles(
    vdc.provider_vdc_name || undefined
  );
  const { data: networkPools, isLoading: npLoading } = useNetworkPools(
    vdc.provider_vdc_name || undefined
  );

  const pvdcOptions = useMemo<SelectOption[]>(
    () =>
      (pvdcs ?? [])
        .filter((p) => p.is_enabled)
        .map((p) => ({ label: p.name, value: p.name })),
    [pvdcs]
  );

  const allocationOptions: SelectOption[] = [
    { label: "AllocationVApp", value: "AllocationVApp" },
    { label: "AllocationPool", value: "AllocationPool" },
    { label: "ReservationPool", value: "ReservationPool" },
    { label: "Flex", value: "Flex" },
  ];

  const npOptions = useMemo<SelectOption[]>(
    () =>
      (networkPools ?? []).map((np) => ({
        label: np.name,
        value: np.name,
      })),
    [networkPools]
  );

  const spOptions = useMemo<SelectOption[]>(
    () =>
      (storageProfiles ?? []).map((sp) => ({
        label: sp.name,
        value: sp.name,
      })),
    [storageProfiles]
  );

  const isFlex = vdc.allocation_model === "Flex";

  return (
    <Section
      title="Virtual Data Center"
      icon={HardDrive}
      badge={vdc.name ? "1" : undefined}
    >
      <FormInput
        label="VDC Name"
        value={vdc.name}
        onChange={(v) => setVdc({ name: v })}
        placeholder="e.g. prod-vdc-01"
      />
      {!pvdcsLoading && pvdcOptions.length === 0 ? (
        <FormInput
          label="Provider VDC"
          value={vdc.provider_vdc_name}
          onChange={(v) => setVdc({ provider_vdc_name: v })}
          placeholder="Enter provider VDC name..."
        />
      ) : (
        <FormSelect
          label="Provider VDC"
          value={vdc.provider_vdc_name}
          onChange={(v) => setVdc({ provider_vdc_name: v })}
          options={pvdcOptions}
          placeholder="Select provider VDC..."
          isLoading={pvdcsLoading}
        />
      )}
      <FormSelect
        label="Allocation Model"
        value={vdc.allocation_model}
        onChange={(v) => setVdc({ allocation_model: v })}
        options={allocationOptions}
        placeholder="Select allocation model..."
      />

      {/* Compute */}
      <p className="text-[10px] font-semibold uppercase tracking-wider text-clr-text-secondary pt-2">
        Compute
      </p>
      <div className="grid grid-cols-2 gap-2">
        <FormNumberInput
          label="CPU Allocated (GHz)"
          value={Math.round((vdc.cpu_allocated / 1000) * 100) / 100}
          onChange={(v) => setVdc({ cpu_allocated: Math.round(v * 1000) })}
          min={0}
          step={0.1}
        />
        <FormNumberInput
          label="CPU Limit (GHz)"
          value={Math.round((vdc.cpu_limit / 1000) * 100) / 100}
          onChange={(v) => setVdc({ cpu_limit: Math.round(v * 1000) })}
          min={0}
          step={0.1}
        />
        <FormNumberInput
          label="Memory Allocated (GB)"
          value={Math.round((vdc.memory_allocated / 1024) * 100) / 100}
          onChange={(v) => setVdc({ memory_allocated: Math.round(v * 1024) })}
          min={0}
          step={0.5}
        />
        <FormNumberInput
          label="Memory Limit (GB)"
          value={Math.round((vdc.memory_limit / 1024) * 100) / 100}
          onChange={(v) => setVdc({ memory_limit: Math.round(v * 1024) })}
          min={0}
          step={0.5}
        />
      </div>

      {/* Network */}
      <p className="text-[10px] font-semibold uppercase tracking-wider text-clr-text-secondary pt-2">
        Network
      </p>
      {!npLoading && npOptions.length === 0 ? (
        <FormInput
          label="Network Pool Name"
          value={vdc.network_pool_name}
          onChange={(v) => setVdc({ network_pool_name: v })}
          placeholder="e.g. ALM-GENEVE-LAG"
        />
      ) : (
        <FormSelect
          label="Network Pool Name"
          value={vdc.network_pool_name}
          onChange={(v) => setVdc({ network_pool_name: v })}
          options={npOptions}
          placeholder="Select network pool..."
          isLoading={npLoading}
        />
      )}

      {/* Storage Profiles */}
      <p className="text-[10px] font-semibold uppercase tracking-wider text-clr-text-secondary pt-2">
        Storage Profiles
      </p>
      {vdc.storage_profiles.map((sp, i) => (
        <div
          key={i}
          className="rounded-sm border border-clr-border bg-white p-2 space-y-2"
        >
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-medium text-clr-text-secondary">
              Profile {i + 1}
            </span>
            {vdc.storage_profiles.length > 1 && (
              <button
                onClick={() => removeStorageProfile(i)}
                className="text-[10px] text-clr-danger hover:text-clr-danger/80"
              >
                Remove
              </button>
            )}
          </div>
          {spOptions.length > 0 ? (
            <FormSelect
              label="Name"
              value={sp.name}
              onChange={(v) => updateStorageProfile(i, { name: v })}
              options={spOptions}
              placeholder="Select storage profile..."
            />
          ) : (
            <FormInput
              label="Name"
              value={sp.name}
              onChange={(v) => updateStorageProfile(i, { name: v })}
              placeholder="e.g. alm-fas8300-ssd-01"
            />
          )}
          <FormNumberInput
            label="Limit (GB)"
            value={Math.round((sp.limit / 1024) * 100) / 100}
            onChange={(v) => updateStorageProfile(i, { limit: Math.round(v * 1024) })}
            min={0}
            step={1}
          />
          <div className="flex gap-4">
            <FormCheckbox
              label="Default"
              checked={sp.default}
              onChange={(v) => updateStorageProfile(i, { default: v })}
            />
            <FormCheckbox
              label="Enabled"
              checked={sp.enabled}
              onChange={(v) => updateStorageProfile(i, { enabled: v })}
            />
          </div>
        </div>
      ))}
      <button
        onClick={addStorageProfile}
        className="w-full rounded-sm border border-dashed border-clr-border py-1.5 text-[11px] text-clr-text-secondary hover:text-clr-text hover:border-clr-placeholder transition-colors"
      >
        + Add Storage Profile
      </button>

      {/* Flex Options */}
      {isFlex && (
        <>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-clr-text-secondary pt-2">
            Flex Options
          </p>
          <FormCheckbox
            label="Elasticity"
            checked={vdc.elasticity}
            onChange={(v) => setVdc({ elasticity: v })}
          />
          <FormCheckbox
            label="Include VM Memory Overhead"
            checked={vdc.include_vm_memory_overhead}
            onChange={(v) => setVdc({ include_vm_memory_overhead: v })}
          />
          <FormNumberInput
            label="Memory Guaranteed (%)"
            value={vdc.memory_guaranteed ?? 20}
            onChange={(v) => setVdc({ memory_guaranteed: Math.min(100, Math.max(0, v)) })}
            min={0}
            step={1}
          />
        </>
      )}

      {/* Options */}
      <p className="text-[10px] font-semibold uppercase tracking-wider text-clr-text-secondary pt-2">
        Options
      </p>
      <FormCheckbox
        label="Enable Thin Provisioning"
        checked={vdc.enable_thin_provisioning}
        onChange={(v) => setVdc({ enable_thin_provisioning: v })}
      />
      <FormCheckbox
        label="Enable Fast Provisioning"
        checked={vdc.enable_fast_provisioning}
        onChange={(v) => setVdc({ enable_fast_provisioning: v })}
      />
      <FormCheckbox
        label="Delete Force"
        checked={vdc.delete_force}
        onChange={(v) => setVdc({ delete_force: v })}
      />
      <FormCheckbox
        label="Delete Recursive"
        checked={vdc.delete_recursive}
        onChange={(v) => setVdc({ delete_recursive: v })}
      />

      <FormInput
        label="Description"
        value={vdc.description}
        onChange={(v) => setVdc({ description: v })}
        placeholder="Optional description"
      />
    </Section>
  );
}

// NOTE: EdgeSection, NetworkSection, VappSection, VmSection are temporarily
// disabled (Coming soon). Re-enable by uncommenting and replacing the
// disabled <Section> placeholders in the Sidebar component below.

/* ------------------------------------------------------------------ */
/*  Action Bar (Plan / Apply buttons)                                 */
/* ------------------------------------------------------------------ */

function ActionBar() {
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

/* ------------------------------------------------------------------ */
/*  Sidebar (root)                                                    */
/* ------------------------------------------------------------------ */

export function Sidebar() {
  const resetAll = useConfigStore((s) => s.resetAll);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-clr-border">
        <h2 className="text-clr-text font-semibold tracking-tight text-sm">
          Configuration
        </h2>
        <button
          onClick={resetAll}
          className="text-clr-placeholder hover:text-clr-text transition-colors"
          title="Reset all fields"
        >
          <RotateCcw className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Accordion sections */}
      <div className="flex-1 overflow-y-auto">
        <OrgSection />
        <VdcSection />
        <Section title="Edge Gateway" icon={Network} disabled>{null}</Section>
        <Section title="Routed Network" icon={Wifi} disabled>{null}</Section>
        <Section title="vApp" icon={Box} disabled>{null}</Section>
        <Section title="Virtual Machine" icon={Monitor} disabled>{null}</Section>
      </div>

      {/* Plan / Apply buttons */}
      <ActionBar />
    </div>
  );
}
