import { useState } from "react";
import { Plug, ShieldCheck, AlertTriangle, Info } from "lucide-react";
import { FormInput, FormSelect } from "@/components/shared";
import { Button, Card, PageHeader, Callout, Stats } from "@/components/ui";
import { MigrationHclPreview } from "@/components/migration/MigrationHclPreview";
import { IpsecTunnelTable } from "@/components/migration/IpsecTunnelTable";
import { useAuthHandle } from "@/api/migrationApi";
import {
  useClouds,
  useCloudOrgs,
  useCloudVdcs,
  useCloudEdges,
  type CloudId,
} from "@/api/cloudMigrationApi";
import {
  useIpsecPreview,
  useIpsecPlan,
  useIpsecApply,
  type SourceTarget,
} from "@/api/ipsecMigrationApi";
import { useConfigStore } from "@/store/useConfigStore";

/* IPsec tunnel migration.

   Its own tab rather than part of the firewall/NAT flow, because a tunnel
   is a live session with a third party: it is created disabled and
   switched over one at a time, not applied and verified afterwards. */

function detail(e: unknown, fallback: string): string {
  return (
    (e as { response?: { data?: { detail?: string } } })?.response?.data
      ?.detail ?? fallback
  );
}

export function IpsecMigrationPage() {
  // --- source (legacy VCD) ---
  const [host, setHost] = useState("");
  const [token, setToken] = useState("");
  const [handle, setHandle] = useState<string | null>(null);
  const [edgeUuid, setEdgeUuid] = useState("");
  const authHandle = useAuthHandle();

  // --- destination: either configured VCD ---
  const [cloud, setCloud] = useState<CloudId | "">("");
  const [orgId, setOrgId] = useState("");
  const [orgName, setOrgName] = useState("");
  const [vdcId, setVdcId] = useState("");
  const [vdcName, setVdcName] = useState("");
  const [edgeId, setEdgeId] = useState("");
  const cloudsQuery = useClouds();
  const clouds = cloudsQuery.data ?? [];
  const orgs = useCloudOrgs(cloud);
  const vdcs = useCloudVdcs(cloud, orgId || undefined);
  const edges = useCloudEdges(cloud, vdcId || undefined);

  const preview = useIpsecPreview();
  const planMutation = useIpsecPlan();
  const applyMutation = useIpsecApply();
  const [planOpId, setPlanOpId] = useState<string | null>(null);
  const setOperation = useConfigStore((s) => s.setOperation);
  const openTerminal = useConfigStore((s) => s.openTerminal);

  const result = preview.data;
  const ready = !!(handle && edgeUuid && cloud && orgName && vdcId && edgeId);

  const body = (): SourceTarget => ({
    handle: handle ?? undefined,
    source_edge_uuid: edgeUuid.trim(),
    verify_ssl: false,
    target_cloud: cloud as CloudId,
    target_org: orgName,
    target_vdc: vdcName,
    target_vdc_id: vdcId,
    target_edge_id: edgeId,
  });

  const connect = () =>
    authHandle.mutate(
      { host: host.trim(), api_token: token.trim() },
      {
        onSuccess: (d) => {
          setHandle(d.handle);
          // The raw token is exchanged for a short-lived handle and then
          // dropped: it never reaches sessionStorage.
          setToken("");
        },
      },
    );

  const runPreview = () => {
    setPlanOpId(null);
    preview.mutate(body());
  };

  const runPlan = () => {
    setOperation(null, "planning");
    openTerminal();
    planMutation.mutate(body(), {
      onSuccess: (d) => {
        setPlanOpId(d.operation_id);
        setOperation(d.operation_id, "planning");
        openTerminal();
      },
      onError: (e) =>
        setOperation(null, "error", detail(e, "Plan failed to start")),
    });
  };

  const runApply = () => {
    if (!planOpId) return;
    setOperation(planOpId, "applying");
    openTerminal();
    applyMutation.mutate(
      {
        target_cloud: cloud as CloudId,
        target_org: orgName,
        plan_operation_id: planOpId,
      },
      {
        onSuccess: (d) => {
          setOperation(d.operation_id, "applying");
          openTerminal();
        },
        onError: (e) =>
          setOperation(planOpId, "error", detail(e, "Apply failed to start")),
      },
    );
  };

  return (
    <div className="p-6 max-w-6xl space-y-4">
      <PageHeader
        title="IPsec tunnel migration"
        description="Copy IPsec VPN tunnels from a legacy NSX-V edge onto an NSX-T edge. Tunnels are always created disabled — enable them one at a time during cutover, once the source side is down."
      />

      <div className="flex flex-col lg:flex-row gap-3">
        {/* ---------------- source ---------------- */}
        <Card title="Source" className="flex-1 min-w-0">
         <div className="space-y-3">
          {handle ? (
            <div className="flex items-center gap-2 rounded-sm bg-emerald-50 px-2.5 py-1.5 text-xs text-emerald-900">
              <ShieldCheck className="h-3.5 w-3.5" />
              Connected to {host}
              <button
                onClick={() => {
                  setHandle(null);
                  preview.reset();
                  setPlanOpId(null);
                }}
                className="ml-auto underline"
              >
                change
              </button>
            </div>
          ) : (
            <>
              <FormInput
                label="Legacy VCD host"
                value={host}
                onChange={setHost}
                placeholder="https://vcd02.example.kz"
              />
              <label className="block space-y-1">
                <span className="text-xs font-medium text-clr-text-secondary">
                  API token
                </span>
                <input
                  type="password"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="Exchanged for a short-lived handle"
                  autoComplete="off"
                  className="w-full rounded-sm border border-clr-border bg-white px-2.5 py-1.5 text-sm focus:border-clr-action focus:outline-none"
                />
              </label>
              <Button
                onClick={connect}
                disabled={!host.trim() || !token.trim()}
                loading={authHandle.isPending}
                icon={<Plug className="h-3.5 w-3.5" />}
              >
                Connect
              </Button>
              {authHandle.isError && (
                <p className="text-xs text-clr-danger">
                  {detail(authHandle.error, "Could not connect")}
                </p>
              )}
            </>
          )}

          <FormInput
            label="Source edge gateway UUID"
            value={edgeUuid}
            onChange={setEdgeUuid}
            placeholder="b6b3181a-2596-44c5-9991-c4c54c050bcb"
            disabled={!handle}
          />
          <p className="text-[11px] text-clr-text-secondary">
            A UUID, not an NSX-V id like <code>edge-237</code> — the proxy
            rejects those.
          </p>
         </div>
        </Card>

        {/* ---------------- destination ---------------- */}
        <Card title="Destination" className="flex-1 min-w-0">
         <div className="space-y-3">
          <FormSelect
            label="Cloud"
            value={cloud}
            onChange={(v) => {
              // Everything below is cloud-specific; keeping a stale org
              // would submit an id that does not exist on the new one.
              setCloud(v as CloudId);
              setOrgId("");
              setOrgName("");
              setVdcId("");
              setVdcName("");
              setEdgeId("");
            }}
            isLoading={cloudsQuery.isLoading}
            options={clouds.map((c) => ({
              label: c.configured ? c.label : `${c.label} — not configured`,
              value: c.configured ? c.id : "",
            }))}
          />
          <FormSelect
            label="Organization"
            value={orgId}
            onChange={(v) => {
              setOrgId(v);
              setOrgName(orgs.data?.find((o) => o.id === v)?.name ?? "");
              setVdcId("");
              setEdgeId("");
            }}
            isLoading={orgs.isLoading}
            disabled={!cloud}
            options={(orgs.data ?? []).map((o) => ({
              label: o.name,
              value: o.id,
            }))}
          />
          <FormSelect
            label="VDC"
            value={vdcId}
            onChange={(v) => {
              setVdcId(v);
              setVdcName(vdcs.data?.find((d) => d.id === v)?.name ?? "");
              setEdgeId("");
            }}
            isLoading={vdcs.isLoading}
            disabled={!orgId}
            options={(vdcs.data ?? []).map((d) => ({
              label: d.name,
              value: d.id,
            }))}
          />
          <FormSelect
            label="Edge gateway"
            value={edgeId}
            onChange={setEdgeId}
            isLoading={edges.isLoading}
            disabled={!vdcId}
            options={(edges.data ?? []).map((e) => ({
              label: e.name,
              value: e.id,
            }))}
          />
         </div>
        </Card>
      </div>

      <div className="flex items-center gap-3">
        <Button
          variant="primary"
          onClick={runPreview}
          disabled={!ready}
          loading={preview.isPending}
        >
          {preview.isPending
            ? "Reading tunnels..."
            : result
              ? "Re-read tunnels"
              : "Read tunnels"}
        </Button>
        {preview.isError && (
          <span className="text-xs text-clr-danger">
            {detail(preview.error, "Could not read the source edge")}
          </span>
        )}
      </div>

      {result && (
        <>
          <Card>
            <Stats
              items={[
                { label: "Tunnels found", value: result.total },
                { label: "Will be created", value: result.migratable, tone: "success" },
                {
                  label: "Left on source",
                  value: result.skipped,
                  tone: result.skipped > 0 ? "warning" : undefined,
                },
              ]}
            />
          </Card>

          {result.warnings.length > 0 && (
            <Callout
              tone="warning"
              title="Before you apply"
              icon={<AlertTriangle className="h-4 w-4" />}
            >
              {result.warnings.map((w, i) => (
                <p key={i}>• {w}</p>
              ))}
            </Callout>
          )}

          <IpsecTunnelTable tunnels={result.tunnels} />

          <p className="flex items-start gap-1.5 text-[11px] text-clr-text-secondary">
            <Info className="h-3.5 w-3.5 mt-px shrink-0" />
            Pre-shared keys are not sent to this page. They are read again on
            the server when you plan, and reach terraform as variables.
          </p>

          <MigrationHclPreview hcl={result.hcl} edgeName="ipsec_tunnels" />

          <Card
            title={`Apply to ${orgName} on ${
              clouds.find((c) => c.id === cloud)?.label ?? cloud
            }`}
            description="Plan re-reads the source so the keys and the variables they fill come from one fetch. Apply runs exactly that plan."
          >
            <div className="flex items-center gap-2">
              <Button
                onClick={runPlan}
                disabled={!ready || result.migratable === 0}
                loading={planMutation.isPending}
                title={
                  result.migratable === 0 ? "No tunnel can be migrated" : undefined
                }
              >
                Plan
              </Button>
              <Button
                variant="primary"
                onClick={runApply}
                disabled={!planOpId}
                loading={applyMutation.isPending}
                title={planOpId ? undefined : "Run a plan first"}
              >
                Apply
              </Button>
              {planOpId && (
                <span className="text-xs text-clr-text-secondary">
                  Plan ready — read the terminal before applying.
                </span>
              )}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
