import { useState } from "react";
import { ArrowRight, AlertTriangle, Server } from "lucide-react";
import { FormSelect } from "@/components/shared";
import { Button, Card, PageHeader, Callout, Stats } from "@/components/ui";
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
  useCloudMigrationPlan,
  useCloudMigrationApply,
  type CloudId,
  type PreviewResponse,
} from "@/api/cloudMigrationApi";
import { useConfigStore } from "@/store/useConfigStore";

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
    <Card
      title={
        <span className="flex items-center gap-2">
          <Server className="h-4 w-4 text-clr-text-secondary shrink-0" />
          {title}
        </span>
      }
      description={subtitle}
      className="flex-1 min-w-0"
    >
     <div className="space-y-3">
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
     </div>
    </Card>
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
  const planMutation = useCloudMigrationPlan();
  const applyMutation = useCloudMigrationApply();
  // The plan whose workspace still holds plan.bin — apply reuses it so
  // what lands on the destination is exactly what was reviewed.
  const [planOpId, setPlanOpId] = useState<string | null>(null);
  const setOperation = useConfigStore((s) => s.setOperation);
  const openTerminal = useConfigStore((s) => s.openTerminal);

  const clouds = cloudsQuery.data ?? [];
  const sameEdge =
    source.cloud === target.cloud &&
    !!source.edgeId &&
    source.edgeId === target.edgeId;
  const ready = isComplete(source) && isComplete(target) && !sameEdge;

  const result: PreviewResponse | undefined = preview.data;

  const badMapping = Object.values(ipMapping).some((v) => !isValidIpv4(v));

  const handlePlan = () => {
    if (!result) return;
    setOperation(null, "planning");
    openTerminal();
    planMutation.mutate(
      {
        target_cloud: target.cloud as CloudId,
        target_org: target.orgName,
        target_vdc: target.vdcName,
        target_edge_id: target.edgeId,
        target_edge_name: target.edgeName,
        hcl: result.hcl,
      },
      {
        onSuccess: (d) => {
          setPlanOpId(d.operation_id);
          setOperation(d.operation_id, "planning");
          openTerminal();
        },
        onError: (e) => {
          const msg =
            (e as { response?: { data?: { detail?: string } } })?.response?.data
              ?.detail ?? "Plan failed to start";
          setOperation(null, "error", msg);
        },
      },
    );
  };

  const handleApply = () => {
    if (!planOpId) return;
    setOperation(planOpId, "applying");
    openTerminal();
    applyMutation.mutate(
      {
        target_cloud: target.cloud as CloudId,
        target_org: target.orgName,
        plan_operation_id: planOpId,
      },
      {
        onSuccess: (d) => {
          setOperation(d.operation_id, "applying");
          openTerminal();
        },
        onError: (e) => {
          const msg =
            (e as { response?: { data?: { detail?: string } } })?.response?.data
              ?.detail ?? "Apply failed to start";
          setOperation(planOpId, "error", msg);
        },
      },
    );
  };

  const handlePreview = () => {
    // Regenerating invalidates the reviewed plan.
    setPlanOpId(null);
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
  };

  return (
    <div className="p-6 max-w-6xl space-y-4">
      <PageHeader
        title="Cloud-to-cloud migration"
        description="Copy an NSX-T edge gateway's NAT, firewall, IP sets and static routes onto an edge in another VCD. Both ends must already be NSX-T backed."
      />

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
        <Button
          variant="primary"
          onClick={handlePreview}
          disabled={!ready || badMapping}
          loading={preview.isPending}
        >
          {preview.isPending
            ? "Reading source edge..."
            : result
              ? "Regenerate HCL"
              : "Generate HCL"}
        </Button>
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

          <Card title="What will be created">
            <Stats
              items={Object.entries(SUMMARY_LABELS).map(([k, label]) => ({
                label,
                value: result.summary[k] ?? 0,
              }))}
            />
          </Card>

          {result.warnings.length > 0 && (
            <Callout
              tone="warning"
              title={`Check before applying (${result.warnings.length})`}
              icon={<AlertTriangle className="h-4 w-4" />}
            >
              {result.warnings.map((w, i) => (
                <p key={i}>• {w}</p>
              ))}
            </Callout>
          )}

          <MigrationHclPreview
            hcl={result.hcl}
            edgeName={target.edgeName || "target_edge"}
          />

          <Card
            title={`Apply to ${target.orgName} on ${
              clouds.find((c) => c.id === target.cloud)?.label ?? target.cloud
            }`}
            description="Plan first and read the output. Apply runs exactly that plan — regenerating the HCL discards it."
          >
            <div className="flex items-center gap-2">
              <Button
                onClick={handlePlan}
                loading={planMutation.isPending}
              >
                Plan
              </Button>
              <Button
                variant="primary"
                onClick={handleApply}
                disabled={!planOpId}
                loading={applyMutation.isPending}
                title={planOpId ? undefined : "Run a plan first"}
              >
                Apply
              </Button>
              {planOpId && (
                <span className="text-xs text-clr-text-secondary">
                  Plan ready — check the terminal before applying.
                </span>
              )}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
