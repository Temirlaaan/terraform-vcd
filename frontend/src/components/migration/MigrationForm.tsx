import { Loader2 } from "lucide-react";
import { FormInput, FormCheckbox, FormSelect } from "@/components/shared";
import type { MigrationRequest } from "@/api/migrationApi";
import {
  useOrgs,
  useVdcsByOrg,
  useEdgeGatewaysByVdc,
} from "@/api/metadataApi";
import { useMigrationStore } from "@/store/useMigrationStore";

interface MigrationFormProps {
  onSubmit: (data: MigrationRequest) => void;
  isLoading: boolean;
}

export function MigrationForm({ onSubmit, isLoading }: MigrationFormProps) {
  const form = useMigrationStore((s) => s.form);
  const apiToken = useMigrationStore((s) => s.apiToken);
  const setFormField = useMigrationStore((s) => s.setFormField);
  const setApiToken = useMigrationStore((s) => s.setApiToken);

  const orgsQuery = useOrgs();
  const vdcsQuery = useVdcsByOrg(form.orgId || undefined);
  const edgesQuery = useEdgeGatewaysByVdc(form.vdcId || undefined);

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
    setFormField("orgId", orgId);
    setFormField("orgName", org?.name ?? "");
    setFormField("vdcId", "");
    setFormField("vdcName", "");
    setFormField("edgeGatewayId", "");
    setFormField("edgeGatewayName", "");
  };

  const handleVdcChange = (vdcId: string) => {
    const vdc = vdcsQuery.data?.find((v) => v.id === vdcId);
    setFormField("vdcId", vdcId);
    setFormField("vdcName", vdc?.name ?? "");
    setFormField("edgeGatewayId", "");
    setFormField("edgeGatewayName", "");
  };

  const hasLegacyConfig = form.host && apiToken && form.edgeUuid;
  const hasTargetSelection =
    form.orgName && form.vdcName && form.edgeGatewayId;
  const canSubmit = hasLegacyConfig && hasTargetSelection;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || isLoading) return;
    onSubmit({
      host: form.host,
      api_token: apiToken,
      edge_uuid: form.edgeUuid,
      target_org: form.orgName,
      target_vdc: form.vdcName,
      target_vdc_id: form.vdcId,
      target_edge_id: form.edgeGatewayId,
      verify_ssl: form.verifySsl,
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
          value={form.host}
          onChange={(v) => setFormField("host", v)}
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
          value={form.edgeUuid}
          onChange={(v) => setFormField("edgeUuid", v)}
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
          value={form.orgId}
          onChange={handleOrgChange}
          options={orgOptions}
          isLoading={orgsQuery.isLoading}
          placeholder="Select organization..."
        />
        <FormSelect
          label="VDC"
          value={form.vdcId}
          onChange={handleVdcChange}
          options={vdcOptions}
          isLoading={vdcsQuery.isLoading}
          disabled={!form.orgId}
          placeholder={form.orgId ? "Select VDC..." : "Select organization first"}
        />
        <FormSelect
          label="Edge Gateway"
          value={form.edgeGatewayId}
          onChange={(v) => {
            setFormField("edgeGatewayId", v);
            const picked = edgesQuery.data?.find((e) => e.id === v);
            setFormField("edgeGatewayName", picked?.name ?? "");
          }}
          options={edgeOptions}
          isLoading={edgesQuery.isLoading}
          disabled={!form.vdcId}
          placeholder={form.vdcId ? "Select edge gateway..." : "Select VDC first"}
        />
      </fieldset>

      {/* Options */}
      <fieldset className="space-y-3">
        <legend className="text-xs font-semibold text-clr-text uppercase tracking-wide">
          Options
        </legend>
        <FormCheckbox
          label="Verify SSL certificate"
          checked={form.verifySsl}
          onChange={(v) => setFormField("verifySsl", v)}
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
