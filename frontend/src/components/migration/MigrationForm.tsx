import { useState } from "react";
import { Loader2 } from "lucide-react";
import { FormInput, FormCheckbox, FormSelect } from "@/components/shared";
import type { MigrationRequest } from "@/api/migrationApi";
import {
  useOrgs,
  useVdcsByOrg,
  useEdgeGatewaysByVdc,
} from "@/api/metadataApi";

interface MigrationFormProps {
  onSubmit: (data: MigrationRequest) => void;
  isLoading: boolean;
}

export function MigrationForm({ onSubmit, isLoading }: MigrationFormProps) {
  // Legacy VCD fields
  const [host, setHost] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [edgeUuid, setEdgeUuid] = useState("");

  // Target selection — store both id and name where needed
  const [selectedOrgId, setSelectedOrgId] = useState("");
  const [selectedOrgName, setSelectedOrgName] = useState("");
  const [selectedVdcId, setSelectedVdcId] = useState("");
  const [selectedVdcName, setSelectedVdcName] = useState("");
  const [targetEdgeId, setTargetEdgeId] = useState("");

  const [verifySsl, setVerifySsl] = useState(false);

  // Cascading queries
  const orgsQuery = useOrgs();
  const vdcsQuery = useVdcsByOrg(selectedOrgId || undefined);
  const edgesQuery = useEdgeGatewaysByVdc(selectedVdcId || undefined);

  const orgOptions = (orgsQuery.data ?? []).map((o) => ({
    label: o.name,
    value: o.id,
  }));
  const vdcOptions = (vdcsQuery.data ?? []).map((v) => ({
    label: v.name,
    value: v.id,
  }));
  const edgeOptions = (edgesQuery.data ?? []).map((e) => ({
    label: e.name,
    value: e.id,
  }));

  const handleOrgChange = (orgId: string) => {
    const org = orgsQuery.data?.find((o) => o.id === orgId);
    setSelectedOrgId(orgId);
    setSelectedOrgName(org?.name ?? "");
    // Reset dependent selections
    setSelectedVdcId("");
    setSelectedVdcName("");
    setTargetEdgeId("");
  };

  const handleVdcChange = (vdcId: string) => {
    const vdc = vdcsQuery.data?.find((v) => v.id === vdcId);
    setSelectedVdcId(vdcId);
    setSelectedVdcName(vdc?.name ?? "");
    // Reset dependent selection
    setTargetEdgeId("");
  };

  const hasLegacyConfig = host && apiToken && edgeUuid;
  const hasTargetSelection = selectedOrgName && selectedVdcName && targetEdgeId;
  const canSubmit = hasLegacyConfig && hasTargetSelection;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || isLoading) return;
    onSubmit({
      host,
      api_token: apiToken,
      edge_uuid: edgeUuid,
      target_org: selectedOrgName,
      target_vdc: selectedVdcName,
      target_edge_id: targetEdgeId,
      verify_ssl: verifySsl,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5 p-4">
      {/* Legacy VCD Connection */}
      <fieldset className="space-y-3">
        <legend className="text-xs font-semibold text-clr-text uppercase tracking-wide">
          Legacy VCD Connection
        </legend>
        <FormInput
          label="Host URL"
          value={host}
          onChange={setHost}
          placeholder="https://vcd-legacy.example.com"
        />
        <label className="block space-y-1">
          <span className="text-xs font-medium text-clr-text-secondary">API Token</span>
          <input
            type="password"
            value={apiToken}
            onChange={(e) => setApiToken(e.target.value)}
            placeholder="••••••••"
            autoComplete="off"
            className="w-full rounded-sm bg-white border border-clr-border px-2.5 py-1.5 text-sm text-clr-text placeholder:text-clr-placeholder focus:border-clr-action focus:outline-none transition-colors"
          />
          <span className="text-[10px] text-clr-text-secondary leading-tight block">
            Generate via VCD UI: Administration → Access Control → Users → Generate API Access Token
          </span>
        </label>
        <FormInput
          label="Edge Gateway UUID"
          value={edgeUuid}
          onChange={setEdgeUuid}
          placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        />
      </fieldset>

      {/* Target VCD 10.6 */}
      <fieldset className="space-y-3">
        <legend className="text-xs font-semibold text-clr-text uppercase tracking-wide">
          Target (VCD 10.6)
        </legend>
        <FormSelect
          label="Organization"
          value={selectedOrgId}
          onChange={handleOrgChange}
          options={orgOptions}
          isLoading={orgsQuery.isLoading}
          placeholder="Select organization..."
        />
        <FormSelect
          label="VDC"
          value={selectedVdcId}
          onChange={handleVdcChange}
          options={vdcOptions}
          isLoading={vdcsQuery.isLoading}
          disabled={!selectedOrgId}
          placeholder={selectedOrgId ? "Select VDC..." : "Select organization first"}
        />
        <FormSelect
          label="Edge Gateway"
          value={targetEdgeId}
          onChange={setTargetEdgeId}
          options={edgeOptions}
          isLoading={edgesQuery.isLoading}
          disabled={!selectedVdcId}
          placeholder={selectedVdcId ? "Select edge gateway..." : "Select VDC first"}
        />
      </fieldset>

      {/* Options */}
      <fieldset className="space-y-3">
        <legend className="text-xs font-semibold text-clr-text uppercase tracking-wide">
          Options
        </legend>
        <FormCheckbox
          label="Verify SSL certificate"
          checked={verifySsl}
          onChange={setVerifySsl}
        />
      </fieldset>

      {/* Submit */}
      <button
        type="submit"
        disabled={!canSubmit || isLoading}
        className="flex items-center justify-center gap-2 w-full rounded-sm bg-clr-action text-white text-sm font-medium py-2 px-4 hover:bg-clr-action-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
        {isLoading ? "Generating..." : "Generate HCL"}
      </button>
    </form>
  );
}
