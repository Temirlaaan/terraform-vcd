import { useState } from "react";
import { ArrowRight, Loader2, AlertTriangle, Server } from "lucide-react";
import { FormSelect } from "@/components/shared";
import { MigrationHclPreview } from "@/components/migration/MigrationHclPreview";
import {
  AddressRemapTable,
  isValidIpv4,
} from "@/components/migration/AddressRemapTable";
import {
  useClouds,
  useCloudOrgs,
  useCloudVdcs,
  useCloudEdges,
  useCloudMigrationPreview,
  type CloudId,
  type PreviewResponse,
} from "@/api/cloudMigrationApi";

/* ------------------------------------------------------------------ */
/*  One side of the transfer: cloud → org → VDC → edge                 */
/* ------------------------------------------------------------------ */

interface EndpointState {
  cloud: CloudId | "";
  orgId: string;
  orgName: string;
  vdcId: string;
  vdcName: string;
  edgeId: string;
  edgeName: string;
}

const EMPTY: EndpointState = {
  cloud: "",
  orgId: "",
  orgName: "",
  vdcId: "",
  vdcName: "",
  edgeId: "",
  edgeName: "",
};

function isComplete(e: EndpointState): boolean {
  return !!(e.cloud && e.orgName && e.vdcId && e.edgeId);
}

interface EndpointPickerProps {
  title: string;
  subtitle: string;
  state: EndpointState;
  onChange: (next: EndpointState) => void;
  clouds: { id: CloudId; label: string; configured: boolean }[];
  cloudsLoading: boolean;
}

function EndpointPicker({
  title,
  subtitle,
  state,
  onChange,
  clouds,
  cloudsLoading,
}: EndpointPickerProps) {
  const orgs = useCloudOrgs(state.cloud);
  const vdcs = useCloudVdcs(state.cloud, state.orgId || undefined);
  const edges = useCloudEdges(state.cloud, state.vdcId || undefined);

  // Changing a level clears everything below it, so a stale VDC from the
  // previous cloud can never be submitted.
  const setCloud = (v: string) =>
    onChange({ ...EMPTY, cloud: v as CloudId });
  const setOrg = (v: string) =>
    onChange({
      ...state,
      orgId: v,
      orgName: orgs.data?.find((o) => o.id === v)?.name ?? "",
      vdcId: "",
      vdcName: "",
      edgeId: "",
      edgeName: "",
    });
  const setVdc = (v: string) =>
    onChange({
      ...state,
      vdcId: v,
      vdcName: vdcs.data?.find((d) => d.id === v)?.name ?? "",
      edgeId: "",
      edgeName: "",
    });
  const setEdge = (v: string) =>
    onChange({
      ...state,
      edgeId: v,
      edgeName: edges.data?.find((e) => e.id === v)?.name ?? "",
    });

  return (
    <section className="flex-1 min-w-0 rounded-sm border border-clr-border bg-white p-4 space-y-3">
      <header className="flex items-start gap-2">
        <Server className="h-4 w-4 mt-0.5 text-clr-text-secondary shrink-0" />
        <div>
          <h2 className="text-sm font-semibold text-clr-text">{title}</h2>
          <p className="text-xs text-clr-text-secondary">{subtitle}</p>
        </div>
      </header>

      <FormSelect
        label="Cloud"
        value={state.cloud}
        onChange={setCloud}
        isLoading={cloudsLoading}
        options={clouds.map((c) => ({
          label: c.configured ? c.label : `${c.label} — not configured`,
          value: c.configured ? c.id : "",
        }))}
      />
      <FormSelect
        label="Organization"
        value={state.orgId}
        onChange={setOrg}
        isLoading={orgs.isLoading}
        disabled={!state.cloud}
        options={(orgs.data ?? []).map((o) => ({ label: o.name, value: o.id }))}
        error={orgs.isError ? "Could not load organizations" : undefined}
      />
      <FormSelect
        label="VDC"
        value={state.vdcId}
        onChange={setVdc}
        isLoading={vdcs.isLoading}
        disabled={!state.orgId}
        options={(vdcs.data ?? []).map((d) => ({ label: d.name, value: d.id }))}
      />
      <FormSelect
        label="Edge gateway"
        value={state.edgeId}
        onChange={setEdge}
        isLoading={edges.isLoading}
        disabled={!state.vdcId}
        options={(edges.data ?? []).map((e) => ({ label: e.name, value: e.id }))}
      />
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

// Keys come from summary_from_spec() on the backend. Anything not listed
// here is hidden rather than shown as a raw field name.
const SUMMARY_LABELS: Record<string, string> = {
  ip_sets_total: "IP sets",
  firewall_rules_total: "Firewall rules",
  nat_rules_total: "NAT rules",
  app_port_profiles_total: "App port profiles",
  static_routes_total: "Static routes",
};

export function CloudMigrationPage() {
  const cloudsQuery = useClouds();
  const [source, setSource] = useState<EndpointState>(EMPTY);
  const [target, setTarget] = useState<EndpointState>(EMPTY);
  const preview = useCloudMigrationPreview();
  const [ipMapping, setIpMapping] = useState<Record<string, string>>({});

  const clouds = cloudsQuery.data ?? [];
  const sameEdge =
    source.cloud === target.cloud &&
    !!source.edgeId &&
    source.edgeId === target.edgeId;
  const ready = isComplete(source) && isComplete(target) && !sameEdge;

  const result: PreviewResponse | undefined = preview.data;

  const badMapping = Object.values(ipMapping).some((v) => !isValidIpv4(v));

  const handlePreview = () =>
    preview.mutate({
      ip_mapping: ipMapping,
      source_cloud: source.cloud as CloudId,
      source_org: source.orgName,
      source_vdc: source.vdcName,
      source_vdc_id: source.vdcId,
      source_edge_id: source.edgeId,
      source_edge_name: source.edgeName,
      target_cloud: target.cloud as CloudId,
      target_org: target.orgName,
      target_vdc: target.vdcName,
      target_vdc_id: target.vdcId,
      target_edge_id: target.edgeId,
      target_edge_name: target.edgeName,
    });

  return (
    <div className="p-6 max-w-6xl space-y-4">
      <header>
        <h1 className="text-lg font-semibold text-clr-text">
          Cloud-to-cloud migration
        </h1>
        <p className="text-xs text-clr-text-secondary mt-0.5">
          Copy an NSX-T edge gateway's NAT, firewall, IP sets and static routes
          onto an edge in another VCD. Both ends must already be NSX-T backed.
        </p>
      </header>

      <div className="flex flex-col lg:flex-row gap-3 items-stretch">
        <EndpointPicker
          title="Source"
          subtitle="Read configuration from here"
          state={source}
          onChange={(next) => {
            setSource(next);
            setIpMapping({});
          }}
          clouds={clouds}
          cloudsLoading={cloudsQuery.isLoading}
        />
        <div className="flex items-center justify-center lg:px-1">
          <ArrowRight className="h-5 w-5 text-clr-text-secondary" />
        </div>
        <EndpointPicker
          title="Destination"
          subtitle="Generate HCL aimed here"
          state={target}
          onChange={setTarget}
          clouds={clouds}
          cloudsLoading={cloudsQuery.isLoading}
        />
      </div>

      {sameEdge && (
        <p className="text-xs text-clr-danger">
          Source and destination are the same edge on the same cloud.
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={handlePreview}
          disabled={!ready || preview.isPending || badMapping}
          className="inline-flex items-center gap-2 rounded-sm bg-clr-action px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {preview.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {preview.isPending
            ? "Reading source edge..."
            : result
              ? "Regenerate HCL"
              : "Generate HCL"}
        </button>
        {preview.isError && (
          <span className="text-xs text-clr-danger">
            {(preview.error as { response?: { data?: { detail?: string } } })
              ?.response?.data?.detail ?? "Preview failed"}
          </span>
        )}
      </div>

      {result && (
        <>
          <AddressRemapTable
            addresses={result.addresses}
            mapping={ipMapping}
            onChange={setIpMapping}
          />

          <section className="rounded-sm border border-clr-border bg-white p-4">
            <h2 className="text-sm font-semibold text-clr-text mb-2">
              What will be created
            </h2>
            <dl className="flex flex-wrap gap-x-6 gap-y-1">
              {Object.entries(SUMMARY_LABELS).map(([k, label]) => (
                <div key={k} className="flex items-baseline gap-1.5">
                  <dt className="text-xs text-clr-text-secondary">{label}</dt>
                  <dd className="text-sm font-medium text-clr-text">
                    {result.summary[k] ?? 0}
                  </dd>
                </div>
              ))}
            </dl>
          </section>

          {result.warnings.length > 0 && (
            <section className="rounded-sm border border-amber-300 bg-amber-50 p-4">
              <h2 className="flex items-center gap-1.5 text-sm font-semibold text-amber-900 mb-2">
                <AlertTriangle className="h-4 w-4" />
                Check before applying ({result.warnings.length})
              </h2>
              <ul className="space-y-1">
                {result.warnings.map((w, i) => (
                  <li key={i} className="text-xs text-amber-900">
                    • {w}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <MigrationHclPreview
            hcl={result.hcl}
            edgeName={target.edgeName || "target_edge"}
          />
        </>
      )}
    </div>
  );
}
