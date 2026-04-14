import { useState } from "react";
import { Loader2 } from "lucide-react";
import { FormInput, FormCheckbox } from "@/components/shared";
import type { MigrationRequest } from "@/api/migrationApi";

interface MigrationFormProps {
  onSubmit: (data: MigrationRequest) => void;
  isLoading: boolean;
}

export function MigrationForm({ onSubmit, isLoading }: MigrationFormProps) {
  const [host, setHost] = useState("");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [edgeUuid, setEdgeUuid] = useState("");
  const [targetOrg, setTargetOrg] = useState("");
  const [targetVdc, setTargetVdc] = useState("");
  const [targetEdgeId, setTargetEdgeId] = useState("");
  const [verifySsl, setVerifySsl] = useState(false);

  const canSubmit =
    host && user && password && edgeUuid && targetOrg && targetVdc && targetEdgeId;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || isLoading) return;
    onSubmit({
      host,
      user,
      password,
      edge_uuid: edgeUuid,
      target_org: targetOrg,
      target_vdc: targetVdc,
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
        <FormInput
          label="Username"
          value={user}
          onChange={setUser}
          placeholder="admin@system"
        />
        <label className="block space-y-1">
          <span className="text-xs font-medium text-clr-text-secondary">Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            className="w-full rounded-sm bg-white border border-clr-border px-2.5 py-1.5 text-sm text-clr-text placeholder:text-clr-placeholder focus:border-clr-action focus:outline-none transition-colors"
          />
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
        <FormInput
          label="Organization"
          value={targetOrg}
          onChange={setTargetOrg}
          placeholder="my-org"
        />
        <FormInput
          label="VDC"
          value={targetVdc}
          onChange={setTargetVdc}
          placeholder="my-vdc"
        />
        <FormInput
          label="Edge Gateway ID"
          value={targetEdgeId}
          onChange={setTargetEdgeId}
          placeholder="urn:vcloud:gateway:xxxxxxxx-..."
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
