import { useMemo } from "react";
import { HardDrive } from "lucide-react";
import { useConfigStore } from "@/store/useConfigStore";
import { FormInput, FormNumberInput, FormCheckbox, FormSelect } from "../shared";
import type { SelectOption } from "../shared";
import {
  useProviderVdcs,
  useStorageProfiles,
  useNetworkPools,
} from "@/api/hooks";
import { Section } from "./Section";

export function VdcSection() {
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
