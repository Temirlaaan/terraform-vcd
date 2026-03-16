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
  Loader2,
  AlertCircle,
} from "lucide-react";
import { useState, useMemo } from "react";
import { cn } from "@/utils/cn";
import { useConfigStore } from "@/store/useConfigStore";
import { FormInput, FormNumberInput, FormCheckbox, FormSelect } from "./shared";
import type { SelectOption } from "./shared";
import {
  useOrganizations,
  useProviderVdcs,
  useStorageProfiles,
  useNetworkPools,
  usePlan,
  useApply,
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
      <div className="border-b border-slate-800 opacity-50">
        <div className="flex w-full items-center gap-2.5 px-4 py-3 text-xs font-semibold tracking-wide uppercase text-slate-600 cursor-not-allowed">
          <ChevronRight className="h-3.5 w-3.5" />
          <Icon className="h-4 w-4" />
          {title}
          <span className="ml-auto text-[10px] font-normal italic text-slate-600">
            Coming soon
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="border-b border-slate-800">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2.5 px-4 py-3 text-xs font-semibold tracking-wide uppercase text-slate-400 hover:text-slate-200 transition-colors"
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
          <span className="ml-auto text-[10px] font-medium text-blue-400 bg-blue-500/10 border border-blue-500/20 rounded px-1.5 py-0.5">
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

  const { data: orgs, isLoading: orgsLoading } = useOrganizations();

  const orgOptions = useMemo<SelectOption[]>(
    () =>
      (orgs ?? [])
        .filter((o) => o.is_enabled)
        .map((o) => ({ label: o.display_name || o.name, value: o.name })),
    [orgs]
  );

  const handleOrgSelect = (name: string) => {
    const selected = orgs?.find((o) => o.name === name);
    setOrg({
      name,
      full_name: selected?.display_name ?? name,
    });
  };

  return (
    <Section
      title="Organization"
      icon={Building2}
      defaultOpen
      badge={org.name ? "1" : undefined}
    >
      {!orgsLoading && orgOptions.length === 0 ? (
        <FormInput
          label="Organization"
          value={org.name}
          onChange={(v) => setOrg({ name: v })}
          placeholder="Enter organization name..."
        />
      ) : (
        <FormSelect
          label="Organization"
          value={org.name}
          onChange={handleOrgSelect}
          options={orgOptions}
          placeholder="Select organization..."
          isLoading={orgsLoading}
        />
      )}
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
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 pt-2">
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
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 pt-2">
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
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 pt-2">
        Storage Profiles
      </p>
      {vdc.storage_profiles.map((sp, i) => (
        <div
          key={i}
          className="rounded-md border border-slate-700/50 bg-slate-800/30 p-2 space-y-2"
        >
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-medium text-slate-500">
              Profile {i + 1}
            </span>
            {vdc.storage_profiles.length > 1 && (
              <button
                onClick={() => removeStorageProfile(i)}
                className="text-[10px] text-rose-400 hover:text-rose-300"
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
        className="w-full rounded-md border border-dashed border-slate-700 py-1.5 text-[11px] text-slate-500 hover:text-slate-300 hover:border-slate-500 transition-colors"
      >
        + Add Storage Profile
      </button>

      {/* Flex Options */}
      {isFlex && (
        <>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 pt-2">
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
        </>
      )}

      {/* Options */}
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 pt-2">
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

  const canPlan = org.name.length > 0 && planStatus !== "planning" && planStatus !== "applying";
  const canApply = planStatus === "planned" && currentOperationId !== null && !applyMutation.isPending;

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
        setOperation(data.operation_id, "planned");
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
        setOperation(data.operation_id, "applied");
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
    <div className="flex-none border-t border-slate-800 p-4 space-y-3">
      {/* Error banner */}
      {planError && (
        <div className="flex items-start gap-2 rounded-md bg-rose-500/10 border border-rose-500/20 px-3 py-2">
          <AlertCircle className="h-4 w-4 text-rose-400 flex-none mt-0.5" />
          <p className="text-xs text-rose-300 break-all">{planError}</p>
        </div>
      )}

      {/* Buttons */}
      <div className="flex gap-2">
        <button
          onClick={handlePlan}
          disabled={!canPlan}
          className={cn(
            "flex-1 flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors",
            "focus:ring-2 focus:ring-blue-500/50 focus:outline-none",
            canPlan
              ? "bg-blue-600 hover:bg-blue-500 text-white"
              : "bg-slate-800 text-slate-500 cursor-not-allowed"
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
            "flex-1 flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors",
            "focus:ring-2 focus:ring-emerald-500/50 focus:outline-none",
            canApply
              ? "bg-emerald-600 hover:bg-emerald-500 text-white"
              : "bg-slate-800 text-slate-500 cursor-not-allowed"
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

      {/* Status hint */}
      {planStatus === "planned" && (
        <p className="text-[11px] text-emerald-400 text-center">
          Plan succeeded — review output, then apply.
        </p>
      )}
      {planStatus === "applied" && (
        <p className="text-[11px] text-emerald-400 text-center">
          Apply completed successfully.
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
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <h2 className="text-white font-semibold tracking-tight text-sm">
          Configuration
        </h2>
        <button
          onClick={resetAll}
          className="text-slate-500 hover:text-slate-300 transition-colors"
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
