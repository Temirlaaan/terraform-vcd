import {
  Building2,
  HardDrive,
  Network,
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
import { FormInput, FormSelect } from "./shared";
import type { SelectOption } from "./shared";
import {
  useOrganizations,
  useProviderVdcs,
  useStorageProfiles,
  useExternalNetworks,
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
  children,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

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
      <FormSelect
        label="Organization"
        value={org.name}
        onChange={handleOrgSelect}
        options={orgOptions}
        placeholder="Select organization..."
        isLoading={orgsLoading}
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

  const { data: pvdcs, isLoading: pvdcsLoading } = useProviderVdcs();
  const { data: storageProfiles, isLoading: spLoading } = useStorageProfiles(
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

  // Show available storage profiles as hint text
  const spHint =
    storageProfiles && storageProfiles.length > 0
      ? `${storageProfiles.length} profiles available`
      : undefined;

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
      <FormSelect
        label="Provider VDC"
        value={vdc.provider_vdc_name}
        onChange={(v) => setVdc({ provider_vdc_name: v })}
        options={pvdcOptions}
        placeholder="Select provider VDC..."
        isLoading={pvdcsLoading}
      />
      <FormSelect
        label="Allocation Model"
        value={vdc.allocation_model}
        onChange={(v) => setVdc({ allocation_model: v })}
        options={allocationOptions}
        placeholder="Select allocation model..."
      />
      {spHint && (
        <p className="text-[11px] text-slate-500">
          <span className="text-blue-400">{spHint}</span>
          {spLoading && " (loading...)"}
        </p>
      )}
      <FormInput
        label="Description"
        value={vdc.description}
        onChange={(v) => setVdc({ description: v })}
        placeholder="Optional description"
      />
    </Section>
  );
}

/* ------------------------------------------------------------------ */
/*  Edge Gateway Section                                              */
/* ------------------------------------------------------------------ */

function EdgeSection() {
  const edge = useConfigStore((s) => s.edge);
  const setEdge = useConfigStore((s) => s.setEdge);
  const setEdgeSubnet = useConfigStore((s) => s.setEdgeSubnet);

  const { data: extNets, isLoading: extNetsLoading } = useExternalNetworks();

  const extNetOptions = useMemo<SelectOption[]>(
    () =>
      (extNets ?? []).map((n: { name: string }) => ({
        label: n.name,
        value: n.name,
      })),
    [extNets]
  );

  return (
    <Section
      title="Edge Gateway"
      icon={Network}
      badge={edge.name ? "1" : undefined}
    >
      <FormInput
        label="Edge Name"
        value={edge.name}
        onChange={(v) => setEdge({ name: v })}
        placeholder="e.g. edge-gw-01"
      />
      <FormSelect
        label="External Network"
        value={edge.external_network_name}
        onChange={(v) => setEdge({ external_network_name: v })}
        options={extNetOptions}
        placeholder="Select external network..."
        isLoading={extNetsLoading}
      />
      <FormInput
        label="Gateway IP"
        value={edge.subnet.gateway}
        onChange={(v) => setEdgeSubnet({ gateway: v })}
        placeholder="e.g. 10.0.0.1"
      />
      <FormInput
        label="Primary IP"
        value={edge.subnet.primary_ip}
        onChange={(v) => setEdgeSubnet({ primary_ip: v })}
        placeholder="e.g. 10.0.0.1"
      />
      <FormInput
        label="Prefix Length"
        value={String(edge.subnet.prefix_length)}
        onChange={(v) => setEdgeSubnet({ prefix_length: parseInt(v, 10) || 0 })}
        placeholder="e.g. 24"
      />
      <FormInput
        label="Description"
        value={edge.description ?? ""}
        onChange={(v) => setEdge({ description: v || undefined })}
        placeholder="Optional description"
      />
    </Section>
  );
}

/* ------------------------------------------------------------------ */
/*  Action Bar (Plan / Apply buttons)                                 */
/* ------------------------------------------------------------------ */

function ActionBar() {
  const org = useConfigStore((s) => s.org);
  const vdc = useConfigStore((s) => s.vdc);
  const edge = useConfigStore((s) => s.edge);
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
    const config = { provider, backend, org, vdc, edge };
    setOperation(null, "planning");
    openTerminal();

    planMutation.mutate(config, {
      onSuccess: (data) => {
        setOperation(data.operation_id, "planned");
        openTerminal();
      },
      onError: (err) => {
        const message =
          (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
          (err as Error).message;
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
        <EdgeSection />
      </div>

      {/* Plan / Apply buttons */}
      <ActionBar />
    </div>
  );
}
