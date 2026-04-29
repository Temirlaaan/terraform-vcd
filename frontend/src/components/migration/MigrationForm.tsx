import { useState } from "react";
import { Loader2, ShieldCheck } from "lucide-react";
import { FormInput, FormCheckbox, FormSelect } from "@/components/shared";
import {
  type MigrationRequest,
  useAuthHandle,
} from "@/api/migrationApi";
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
  const apiHandle = useMigrationStore((s) => s.apiHandle);
  const setFormField = useMigrationStore((s) => s.setFormField);
  const setApiHandle = useMigrationStore((s) => s.setApiHandle);

  // H3-FE: raw token only lives in this component's local state, never
  // persisted. Once exchanged for an opaque handle the input clears.
  const [tokenInput, setTokenInput] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const authHandleMut = useAuthHandle();

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

  const hasAuth = Boolean(apiHandle) || Boolean(tokenInput);
  const hasLegacyConfig = form.host && hasAuth && form.edgeUuid;
  const hasTargetSelection =
    form.orgName && form.vdcName && form.edgeGatewayId;
  const canSubmit = hasLegacyConfig && hasTargetSelection;

  const exchangeTokenForHandle = async (): Promise<string | null> => {
    setAuthError(null);
    try {
      const res = await authHandleMut.mutateAsync({
        host: form.host,
        api_token: tokenInput,
      });
      setApiHandle(res.handle);
      setTokenInput("");
      return res.handle;
    } catch (e: any) {
      setAuthError(
        e?.response?.data?.detail ?? e?.message ?? "Failed to register token",
      );
      return null;
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || isLoading) return;

    let handle = apiHandle;
    if (!handle) {
      const fresh = await exchangeTokenForHandle();
      if (!fresh) return;
      handle = fresh;
    }

    onSubmit({
      handle,
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
          <span className="text-xs font-medium text-clr-text-secondary flex items-center justify-between">
            API Token
            {apiHandle && (
              <span className="inline-flex items-center gap-1 text-[10px] font-medium text-emerald-700">
                <ShieldCheck className="h-3 w-3" />
                Token registered (10 min)
              </span>
            )}
          </span>
          <input
            type="password"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder={apiHandle ? "Token registered — leave blank to reuse" : "••••••••"}
            autoComplete="off"
            className="w-full rounded-sm bg-white border border-clr-border px-2.5 py-1.5 text-sm text-clr-text placeholder:text-clr-placeholder focus:border-clr-action focus:outline-none transition-colors"
          />
          <span className="text-[10px] text-clr-text-secondary leading-tight block">
            Token is exchanged for a 10-minute backend handle on submit and
            never stored in the browser. Generate via VCD UI: Administration
            → Access Control → Users → Generate API Access Token.
          </span>
          {apiHandle && (
            <button
              type="button"
              onClick={() => {
                setApiHandle("");
                setTokenInput("");
              }}
              className="text-[10px] text-clr-action hover:underline"
            >
              Forget registered token
            </button>
          )}
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

      {authError && (
        <div className="rounded-sm border border-clr-danger/30 bg-red-50 p-2 text-xs text-clr-danger">
          {authError}
        </div>
      )}

      {/* Submit */}
      <button
        type="submit"
        disabled={!canSubmit || isLoading || authHandleMut.isPending}
        className="flex items-center justify-center gap-2 w-full rounded-sm bg-clr-action text-white text-sm font-medium py-2 px-4 hover:bg-clr-action-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {(isLoading || authHandleMut.isPending) && <Loader2 className="h-4 w-4 animate-spin" />}
        {authHandleMut.isPending
          ? "Registering token..."
          : isLoading
            ? "Generating..."
            : "Generate HCL"}
      </button>
    </form>
  );
}
