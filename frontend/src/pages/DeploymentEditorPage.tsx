/**
 * Create / edit page for manual deployments.
 *
 * Single page that serves both `/deployments/new` (empty spec) and
 * `/deployments/:id/edit` (spec prefilled from state).
 *
 * For migration-kind deployments opened via `/edit`, the target is
 * locked (backend rejects target.edge_id changes); only the rule spec
 * is editable. The UI surfaces this as a disabled target picker.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { isAxiosError } from "axios";
import {
  ArrowLeft,
  Loader2,
  Plus,
  Save,
  ShieldCheck,
  Shuffle,
  Trash2,
  Route as RouteIcon,
  Server,
  Network,
  AlertCircle,
} from "lucide-react";
import { FormInput, FormCheckbox, FormSelect } from "@/components/shared";
import {
  useOrgs,
  useVdcsByOrg,
  useEdgeGatewaysByVdc,
} from "@/api/metadataApi";
import {
  emptySpec,
  useCreateManualDeployment,
  useEditorData,
  useUpdateDeploymentSpec,
  type AppPortEntry,
  type AppPortProfileSpec,
  type DeploymentSpec,
  type FirewallRuleSpec,
  type IpSetSpec,
  type NatRuleSpec,
  type NextHopSpec,
  type StaticRouteSpec,
  type TargetSpec,
} from "@/api/deploymentSpecApi";

/* ------------------------------------------------------------------ */
/*  Utility helpers                                                    */
/* ------------------------------------------------------------------ */

function describeApiError(err: unknown): string {
  if (isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (detail) return JSON.stringify(detail);
    return err.message;
  }
  return (err as Error)?.message || "Unknown error";
}

/** Multiline textarea backed by comma- or newline-separated values. */
function MultilineListInput({
  label,
  value,
  onChange,
  placeholder,
  rows = 3,
}: {
  label: string;
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  rows?: number;
}) {
  const text = value.join("\n");
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-clr-text-secondary">
        {label}
      </span>
      <textarea
        value={text}
        onChange={(e) =>
          onChange(
            e.target.value
              .split(/[\n,]/)
              .map((s) => s.trim())
              .filter((s) => s.length > 0)
          )
        }
        placeholder={placeholder}
        rows={rows}
        className="w-full rounded-sm bg-white border border-clr-border px-2.5 py-1.5 text-xs font-mono text-clr-text placeholder:text-clr-placeholder focus:border-clr-action focus:outline-none resize-y"
      />
    </label>
  );
}

/** Chip picker backed by a list of available names. */
function NamePicker({
  label,
  value,
  options,
  onChange,
  placeholder,
}: {
  label: string;
  value: string[];
  options: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");
  return (
    <div className="space-y-1">
      <span className="text-xs font-medium text-clr-text-secondary">
        {label}
      </span>
      <div className="flex flex-wrap gap-1">
        {value.length === 0 && (
          <span className="text-[11px] italic text-clr-placeholder">
            (any)
          </span>
        )}
        {value.map((name) => {
          const known = options.includes(name);
          return (
            <span
              key={name}
              className={
                "inline-flex items-center gap-1 rounded-sm px-2 py-0.5 text-[11px] font-mono " +
                (known
                  ? "bg-clr-action/10 text-clr-action"
                  : "bg-clr-danger/10 text-clr-danger")
              }
              title={known ? undefined : "Referenced resource not found"}
            >
              {name}
              <button
                type="button"
                onClick={() => onChange(value.filter((v) => v !== name))}
                className="opacity-60 hover:opacity-100"
              >
                ×
              </button>
            </span>
          );
        })}
      </div>
      <div className="flex gap-1">
        <select
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className="flex-1 rounded-sm bg-white border border-clr-border px-2 py-1 text-xs text-clr-text"
        >
          <option value="">{placeholder ?? "Select..."}</option>
          {options
            .filter((o) => !value.includes(o))
            .map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
        </select>
        <button
          type="button"
          onClick={() => {
            if (draft && !value.includes(draft)) {
              onChange([...value, draft]);
              setDraft("");
            }
          }}
          disabled={!draft}
          className="rounded-sm bg-clr-action/10 text-clr-action text-xs font-medium px-2 py-1 disabled:opacity-40"
        >
          Add
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Section: collapsible accordion                                     */
/* ------------------------------------------------------------------ */

function RuleSection({
  title,
  icon: Icon,
  count,
  children,
  onAdd,
  defaultOpen = true,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  count: number;
  children: React.ReactNode;
  onAdd: () => void;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="border border-clr-border rounded-sm bg-white">
      <header className="flex items-center gap-2 px-3 py-2 border-b border-clr-border bg-clr-near-white">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex-1 flex items-center gap-2 text-left"
        >
          <Icon className="h-4 w-4 text-clr-text-secondary" />
          <span className="text-xs font-semibold uppercase tracking-wide text-clr-text">
            {title}
          </span>
          <span className="text-[10px] text-clr-text-secondary">
            ({count})
          </span>
          <span className="ml-auto text-[10px] text-clr-placeholder">
            {open ? "Hide" : "Show"}
          </span>
        </button>
        <button
          type="button"
          onClick={onAdd}
          className="flex items-center gap-1 rounded-sm bg-clr-action text-white text-[11px] font-medium px-2 py-1 hover:bg-clr-action-hover"
        >
          <Plus className="h-3 w-3" /> Add
        </button>
      </header>
      {open && <div className="p-3 space-y-3">{children}</div>}
    </section>
  );
}

function RuleCard({
  title,
  onRemove,
  children,
}: {
  title: string;
  onRemove: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="border border-clr-border rounded-sm p-3 space-y-2 bg-clr-near-white">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-clr-text">{title}</span>
        <button
          type="button"
          onClick={onRemove}
          className="text-clr-danger hover:opacity-80"
          title="Remove"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  IP sets editor                                                     */
/* ------------------------------------------------------------------ */

function IpSetsEditor({
  ipSets,
  onChange,
}: {
  ipSets: IpSetSpec[];
  onChange: (v: IpSetSpec[]) => void;
}) {
  const update = (i: number, patch: Partial<IpSetSpec>) => {
    const next = ipSets.slice();
    next[i] = { ...next[i]!, ...patch };
    onChange(next);
  };
  const remove = (i: number) =>
    onChange(ipSets.filter((_, idx) => idx !== i));

  return (
    <>
      {ipSets.length === 0 && (
        <p className="text-[11px] italic text-clr-placeholder">
          No IP sets defined.
        </p>
      )}
      {ipSets.map((ip, i) => (
        <RuleCard
          key={i}
          title={ip.name || `IP set #${i + 1}`}
          onRemove={() => remove(i)}
        >
          <FormInput
            label="Name"
            value={ip.name}
            onChange={(v) => update(i, { name: v })}
            placeholder="e.g. internal_subnets"
          />
          <FormInput
            label="Description"
            value={ip.description}
            onChange={(v) => update(i, { description: v })}
          />
          <MultilineListInput
            label="IP addresses / CIDRs"
            value={ip.ip_addresses}
            onChange={(v) => update(i, { ip_addresses: v })}
            placeholder={"10.0.0.0/24\n192.168.1.1"}
          />
        </RuleCard>
      ))}
    </>
  );
}

function newIpSet(): IpSetSpec {
  return { name: "", description: "", ip_addresses: [] };
}

/* ------------------------------------------------------------------ */
/*  App port profiles editor                                           */
/* ------------------------------------------------------------------ */

function AppPortProfilesEditor({
  profiles,
  onChange,
}: {
  profiles: AppPortProfileSpec[];
  onChange: (v: AppPortProfileSpec[]) => void;
}) {
  const update = (i: number, patch: Partial<AppPortProfileSpec>) => {
    const next = profiles.slice();
    next[i] = { ...next[i]!, ...patch };
    onChange(next);
  };
  const remove = (i: number) =>
    onChange(profiles.filter((_, idx) => idx !== i));

  const addPort = (i: number) => {
    const next = profiles.slice();
    const cur = next[i]!;
    next[i] = {
      ...cur,
      app_ports: [...cur.app_ports, { protocol: "TCP", ports: [] }],
    };
    onChange(next);
  };
  const updatePort = (i: number, j: number, patch: Partial<AppPortEntry>) => {
    const next = profiles.slice();
    const cur = next[i]!;
    const ports = cur.app_ports.slice();
    ports[j] = { ...ports[j]!, ...patch };
    next[i] = { ...cur, app_ports: ports };
    onChange(next);
  };
  const removePort = (i: number, j: number) => {
    const next = profiles.slice();
    const cur = next[i]!;
    next[i] = {
      ...cur,
      app_ports: cur.app_ports.filter((_, idx) => idx !== j),
    };
    onChange(next);
  };

  return (
    <>
      {profiles.length === 0 && (
        <p className="text-[11px] italic text-clr-placeholder">
          No app port profiles defined.
        </p>
      )}
      {profiles.map((p, i) => (
        <RuleCard
          key={i}
          title={p.name || `Profile #${i + 1}`}
          onRemove={() => remove(i)}
        >
          <FormInput
            label="Name"
            value={p.name}
            onChange={(v) => update(i, { name: v })}
          />
          <FormInput
            label="Description"
            value={p.description}
            onChange={(v) => update(i, { description: v })}
          />
          <FormSelect
            label="Scope"
            value={p.scope}
            onChange={(v) =>
              update(i, { scope: v as AppPortProfileSpec["scope"] })
            }
            options={[
              { label: "TENANT", value: "TENANT" },
              { label: "PROVIDER", value: "PROVIDER" },
              { label: "SYSTEM", value: "SYSTEM" },
            ]}
          />
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-clr-text-secondary">
                App ports
              </span>
              <button
                type="button"
                onClick={() => addPort(i)}
                className="text-[11px] text-clr-action hover:underline"
              >
                + Add protocol
              </button>
            </div>
            {p.app_ports.map((port, j) => (
              <div
                key={j}
                className="flex flex-col gap-1 border border-clr-border rounded-sm p-2 bg-white"
              >
                <div className="flex items-center gap-2">
                  <select
                    value={port.protocol}
                    onChange={(e) =>
                      updatePort(i, j, {
                        protocol: e.target.value as AppPortEntry["protocol"],
                      })
                    }
                    className="rounded-sm bg-white border border-clr-border px-2 py-1 text-xs"
                  >
                    <option value="TCP">TCP</option>
                    <option value="UDP">UDP</option>
                    <option value="ICMPv4">ICMPv4</option>
                    <option value="ICMPv6">ICMPv6</option>
                  </select>
                  <button
                    type="button"
                    onClick={() => removePort(i, j)}
                    className="ml-auto text-clr-danger"
                    title="Remove protocol"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
                {port.protocol !== "ICMPv4" && port.protocol !== "ICMPv6" && (
                  <MultilineListInput
                    label="Ports (one per line)"
                    rows={2}
                    value={port.ports}
                    onChange={(v) => updatePort(i, j, { ports: v })}
                    placeholder={"80\n443\n8000-8080"}
                  />
                )}
              </div>
            ))}
          </div>
        </RuleCard>
      ))}
    </>
  );
}

function newAppPortProfile(): AppPortProfileSpec {
  return {
    name: "",
    description: "",
    scope: "TENANT",
    app_ports: [],
  };
}

/* ------------------------------------------------------------------ */
/*  Firewall editor                                                    */
/* ------------------------------------------------------------------ */

function FirewallEditor({
  rules,
  ipSetNames,
  profileNames,
  onChange,
}: {
  rules: FirewallRuleSpec[];
  ipSetNames: string[];
  profileNames: string[];
  onChange: (v: FirewallRuleSpec[]) => void;
}) {
  const update = (i: number, patch: Partial<FirewallRuleSpec>) => {
    const next = rules.slice();
    next[i] = { ...next[i]!, ...patch };
    onChange(next);
  };
  const remove = (i: number) =>
    onChange(rules.filter((_, idx) => idx !== i));

  return (
    <>
      {rules.length === 0 && (
        <p className="text-[11px] italic text-clr-placeholder">
          No firewall rules defined.
        </p>
      )}
      {rules.map((r, i) => (
        <RuleCard
          key={i}
          title={r.name || `Rule #${i + 1}`}
          onRemove={() => remove(i)}
        >
          <FormInput
            label="Name"
            value={r.name}
            onChange={(v) => update(i, { name: v })}
          />
          <div className="grid grid-cols-3 gap-2">
            <FormSelect
              label="Action"
              value={r.action}
              onChange={(v) =>
                update(i, { action: v as FirewallRuleSpec["action"] })
              }
              options={[
                { label: "ALLOW", value: "ALLOW" },
                { label: "DROP", value: "DROP" },
                { label: "REJECT", value: "REJECT" },
              ]}
            />
            <FormSelect
              label="Direction"
              value={r.direction}
              onChange={(v) =>
                update(i, { direction: v as FirewallRuleSpec["direction"] })
              }
              options={[
                { label: "IN_OUT", value: "IN_OUT" },
                { label: "IN", value: "IN" },
                { label: "OUT", value: "OUT" },
              ]}
            />
            <FormSelect
              label="IP protocol"
              value={r.ip_protocol}
              onChange={(v) =>
                update(i, {
                  ip_protocol: v as FirewallRuleSpec["ip_protocol"],
                })
              }
              options={[
                { label: "IPV4", value: "IPV4" },
                { label: "IPV6", value: "IPV6" },
                { label: "IPV4_IPV6", value: "IPV4_IPV6" },
              ]}
            />
          </div>
          <div className="flex gap-4">
            <FormCheckbox
              label="Enabled"
              checked={r.enabled}
              onChange={(v) => update(i, { enabled: v })}
            />
            <FormCheckbox
              label="Logging"
              checked={r.logging}
              onChange={(v) => update(i, { logging: v })}
            />
          </div>
          <NamePicker
            label="Source IP sets"
            value={r.source_ip_set_names}
            options={ipSetNames}
            onChange={(v) => update(i, { source_ip_set_names: v })}
          />
          <NamePicker
            label="Destination IP sets"
            value={r.destination_ip_set_names}
            options={ipSetNames}
            onChange={(v) => update(i, { destination_ip_set_names: v })}
          />
          <NamePicker
            label="App port profiles"
            value={r.app_port_profile_names}
            options={profileNames}
            onChange={(v) => update(i, { app_port_profile_names: v })}
          />
        </RuleCard>
      ))}
    </>
  );
}

function newFirewallRule(): FirewallRuleSpec {
  return {
    name: "",
    action: "ALLOW",
    direction: "IN_OUT",
    ip_protocol: "IPV4",
    enabled: true,
    logging: false,
    source_ip_set_names: [],
    destination_ip_set_names: [],
    app_port_profile_names: [],
  };
}

/* ------------------------------------------------------------------ */
/*  NAT editor                                                         */
/* ------------------------------------------------------------------ */

function NatEditor({
  rules,
  profileNames,
  onChange,
}: {
  rules: NatRuleSpec[];
  profileNames: string[];
  onChange: (v: NatRuleSpec[]) => void;
}) {
  const update = (i: number, patch: Partial<NatRuleSpec>) => {
    const next = rules.slice();
    next[i] = { ...next[i]!, ...patch };
    onChange(next);
  };
  const remove = (i: number) =>
    onChange(rules.filter((_, idx) => idx !== i));

  return (
    <>
      {rules.length === 0 && (
        <p className="text-[11px] italic text-clr-placeholder">
          No NAT rules defined.
        </p>
      )}
      {rules.map((r, i) => (
        <RuleCard
          key={i}
          title={r.name || `NAT #${i + 1}`}
          onRemove={() => remove(i)}
        >
          <div className="grid grid-cols-2 gap-2">
            <FormInput
              label="Name"
              value={r.name}
              onChange={(v) => update(i, { name: v })}
            />
            <FormSelect
              label="Rule type"
              value={r.rule_type}
              onChange={(v) =>
                update(i, { rule_type: v as NatRuleSpec["rule_type"] })
              }
              options={[
                { label: "DNAT", value: "DNAT" },
                { label: "SNAT", value: "SNAT" },
                { label: "REFLEXIVE", value: "REFLEXIVE" },
                { label: "NO_DNAT", value: "NO_DNAT" },
                { label: "NO_SNAT", value: "NO_SNAT" },
              ]}
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <FormInput
              label="External address"
              value={r.external_address}
              onChange={(v) => update(i, { external_address: v })}
            />
            <FormInput
              label="Internal address"
              value={r.internal_address}
              onChange={(v) => update(i, { internal_address: v })}
            />
          </div>
          {r.rule_type === "DNAT" && (
            <FormInput
              label="DNAT external port"
              value={r.dnat_external_port}
              onChange={(v) => update(i, { dnat_external_port: v })}
              placeholder="e.g. 443 or 8000-8080"
            />
          )}
          {r.rule_type === "SNAT" && (
            <FormInput
              label="SNAT destination address"
              value={r.snat_destination_address}
              onChange={(v) => update(i, { snat_destination_address: v })}
            />
          )}
          <FormSelect
            label="App port profile"
            value={r.app_port_profile_name ?? ""}
            onChange={(v) =>
              update(i, { app_port_profile_name: v || null })
            }
            options={[
              { label: "(none)", value: "" },
              ...profileNames.map((n) => ({ label: n, value: n })),
            ]}
          />
          <div className="grid grid-cols-2 gap-2">
            <FormSelect
              label="Firewall match"
              value={r.firewall_match}
              onChange={(v) =>
                update(i, {
                  firewall_match: v as NatRuleSpec["firewall_match"],
                })
              }
              options={[
                {
                  label: "MATCH_INTERNAL_ADDRESS",
                  value: "MATCH_INTERNAL_ADDRESS",
                },
                {
                  label: "MATCH_EXTERNAL_ADDRESS",
                  value: "MATCH_EXTERNAL_ADDRESS",
                },
                { label: "BYPASS", value: "BYPASS" },
              ]}
            />
            <label className="block space-y-1">
              <span className="text-xs font-medium text-clr-text-secondary">
                Priority
              </span>
              <input
                type="number"
                value={r.priority}
                onChange={(e) =>
                  update(i, { priority: Number(e.target.value) || 0 })
                }
                className="w-full rounded-sm bg-white border border-clr-border px-2 py-1 text-xs"
              />
            </label>
          </div>
          <FormInput
            label="Description"
            value={r.description}
            onChange={(v) => update(i, { description: v })}
          />
          <div className="flex gap-4">
            <FormCheckbox
              label="Enabled"
              checked={r.enabled}
              onChange={(v) => update(i, { enabled: v })}
            />
            <FormCheckbox
              label="Logging"
              checked={r.logging}
              onChange={(v) => update(i, { logging: v })}
            />
          </div>
        </RuleCard>
      ))}
    </>
  );
}

function newNatRule(): NatRuleSpec {
  return {
    name: "",
    rule_type: "DNAT",
    description: "",
    external_address: "",
    internal_address: "",
    dnat_external_port: "",
    snat_destination_address: "",
    app_port_profile_name: null,
    enabled: true,
    logging: false,
    priority: 0,
    firewall_match: "MATCH_INTERNAL_ADDRESS",
  };
}

/* ------------------------------------------------------------------ */
/*  Static routes editor                                               */
/* ------------------------------------------------------------------ */

function StaticRoutesEditor({
  routes,
  onChange,
}: {
  routes: StaticRouteSpec[];
  onChange: (v: StaticRouteSpec[]) => void;
}) {
  const update = (i: number, patch: Partial<StaticRouteSpec>) => {
    const next = routes.slice();
    next[i] = { ...next[i]!, ...patch };
    onChange(next);
  };
  const remove = (i: number) =>
    onChange(routes.filter((_, idx) => idx !== i));

  const updateHop = (i: number, j: number, patch: Partial<NextHopSpec>) => {
    const next = routes.slice();
    const cur = next[i]!;
    const hops = cur.next_hops.slice();
    hops[j] = { ...hops[j]!, ...patch };
    next[i] = { ...cur, next_hops: hops };
    onChange(next);
  };
  const addHop = (i: number) => {
    const next = routes.slice();
    const cur = next[i]!;
    next[i] = {
      ...cur,
      next_hops: [...cur.next_hops, { ip_address: "", admin_distance: 1 }],
    };
    onChange(next);
  };
  const removeHop = (i: number, j: number) => {
    const next = routes.slice();
    const cur = next[i]!;
    next[i] = {
      ...cur,
      next_hops: cur.next_hops.filter((_, idx) => idx !== j),
    };
    onChange(next);
  };

  return (
    <>
      {routes.length === 0 && (
        <p className="text-[11px] italic text-clr-placeholder">
          No static routes defined.
        </p>
      )}
      {routes.map((r, i) => (
        <RuleCard
          key={i}
          title={r.name || `Route #${i + 1}`}
          onRemove={() => remove(i)}
        >
          <FormInput
            label="Name"
            value={r.name}
            onChange={(v) => update(i, { name: v })}
          />
          <FormInput
            label="Description"
            value={r.description}
            onChange={(v) => update(i, { description: v })}
          />
          <FormInput
            label="Network CIDR"
            value={r.network_cidr}
            onChange={(v) => update(i, { network_cidr: v })}
            placeholder="10.50.0.0/24"
          />
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-clr-text-secondary">
                Next hops
              </span>
              <button
                type="button"
                onClick={() => addHop(i)}
                className="text-[11px] text-clr-action hover:underline"
              >
                + Add next hop
              </button>
            </div>
            {r.next_hops.map((hop, j) => (
              <div
                key={j}
                className="grid grid-cols-[1fr,100px,auto] gap-2 items-end border border-clr-border rounded-sm p-2 bg-white"
              >
                <FormInput
                  label="IP address"
                  value={hop.ip_address}
                  onChange={(v) => updateHop(i, j, { ip_address: v })}
                  placeholder="172.20.0.1"
                />
                <label className="block space-y-1">
                  <span className="text-xs font-medium text-clr-text-secondary">
                    Admin dist.
                  </span>
                  <input
                    type="number"
                    value={hop.admin_distance}
                    onChange={(e) =>
                      updateHop(i, j, {
                        admin_distance: Number(e.target.value) || 1,
                      })
                    }
                    className="w-full rounded-sm bg-white border border-clr-border px-2 py-1 text-xs"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => removeHop(i, j)}
                  className="text-clr-danger pb-1"
                  title="Remove hop"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </RuleCard>
      ))}
    </>
  );
}

function newStaticRoute(): StaticRouteSpec {
  return {
    name: "",
    description: "",
    network_cidr: "",
    next_hops: [{ ip_address: "", admin_distance: 1 }],
  };
}

/* ------------------------------------------------------------------ */
/*  Target picker                                                      */
/* ------------------------------------------------------------------ */

function TargetPicker({
  target,
  disabled,
  onChange,
}: {
  target: TargetSpec;
  disabled: boolean;
  onChange: (t: TargetSpec) => void;
}) {
  const orgs = useOrgs();
  // Resolve current selection by id. FormSelect expects the *id* value,
  // but we only persist names on the spec. Re-resolve on every org/vdc/edge
  // list refresh so a freshly loaded editor shows the right labels.
  const selectedOrg = useMemo(
    () => orgs.data?.find((o) => o.name === target.org),
    [orgs.data, target.org]
  );
  const vdcs = useVdcsByOrg(selectedOrg?.id);
  const selectedVdc = useMemo(
    () =>
      vdcs.data?.find(
        (v) => v.id === target.vdc_id || v.name === target.vdc
      ),
    [vdcs.data, target.vdc, target.vdc_id]
  );
  const edges = useEdgeGatewaysByVdc(selectedVdc?.id);

  return (
    <section className="border border-clr-border rounded-sm bg-white p-3 space-y-3">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-clr-text">
        Target
      </h2>
      {disabled && (
        <p className="text-[11px] text-clr-text-secondary">
          Target is locked — editing rules only. Create a new deployment to
          change target edge.
        </p>
      )}
      <FormSelect
        label="Organization"
        value={selectedOrg?.id ?? ""}
        onChange={(id) => {
          const org = orgs.data?.find((o) => o.id === id);
          onChange({
            org: org?.name ?? "",
            vdc: "",
            vdc_id: "",
            edge_id: "",
            edge_name: null,
          });
        }}
        options={(orgs.data ?? []).map((o) => ({ label: o.name, value: o.id }))}
        isLoading={orgs.isLoading}
        disabled={disabled}
        placeholder="Select organization..."
      />
      <FormSelect
        label="VDC"
        value={selectedVdc?.id ?? ""}
        onChange={(id) => {
          const v = vdcs.data?.find((x) => x.id === id);
          onChange({
            ...target,
            vdc: v?.name ?? "",
            vdc_id: id,
            edge_id: "",
            edge_name: null,
          });
        }}
        options={(vdcs.data ?? []).map((v) => ({
          label: v.name,
          value: v.id,
        }))}
        isLoading={vdcs.isLoading}
        disabled={disabled || !selectedOrg}
        placeholder={selectedOrg ? "Select VDC..." : "Select org first"}
      />
      <FormSelect
        label="Edge gateway"
        value={target.edge_id}
        onChange={(id) => {
          const e = edges.data?.find((x) => x.id === id);
          onChange({
            ...target,
            edge_id: id,
            edge_name: e?.name ?? target.edge_name ?? null,
          });
        }}
        options={(() => {
          const opts = (edges.data ?? []).map((e) => ({
            label: e.name,
            value: e.id,
          }));
          // Preserve the stored edge_id even if it is not in the current
          // metadata list (edge removed, list not yet loaded, or cross-VDC
          // reference). Without this, a migration-created deployment with
          // a valid stored edge_id renders as "Select edge..." because
          // React would silently fall back to the placeholder.
          if (
            target.edge_id &&
            !opts.some((o) => o.value === target.edge_id)
          ) {
            opts.unshift({
              label: target.edge_name || target.edge_id,
              value: target.edge_id,
            });
          }
          return opts;
        })()}
        isLoading={edges.isLoading}
        disabled={disabled || !selectedVdc}
        placeholder={selectedVdc ? "Select edge..." : "Select VDC first"}
      />
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export function DeploymentEditorPage() {
  const { id } = useParams<{ id: string }>();
  const isEdit = !!id;
  const navigate = useNavigate();

  const editorQuery = useEditorData(id);
  const createMutation = useCreateManualDeployment();
  const updateMutation = useUpdateDeploymentSpec(id);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [spec, setSpec] = useState<DeploymentSpec>(() =>
    emptySpec({
      org: "",
      vdc: "",
      vdc_id: "",
      edge_id: "",
      edge_name: null,
    })
  );
  const [hydrated, setHydrated] = useState(!isEdit);
  const [error, setError] = useState<string | null>(null);

  // Hydrate editor state once the fetch returns.
  useEffect(() => {
    if (!isEdit) return;
    const data = editorQuery.data;
    if (!data || hydrated) return;
    setSpec(data.spec);
    setHydrated(true);
  }, [editorQuery.data, isEdit, hydrated]);

  const targetLocked = isEdit;

  const ipSetNames = spec.ip_sets.map((s) => s.name).filter(Boolean);
  const profileNames = spec.app_port_profiles
    .map((p) => p.name)
    .filter(Boolean);

  const kind = editorQuery.data?.kind;
  const isMigrationKind = kind === "migration";

  const duplicateNames = useMemo(() => {
    const out: { category: string; name: string }[] = [];
    const scan = (label: string, items: { name: string }[]) => {
      const seen = new Set<string>();
      for (const item of items) {
        const n = item.name?.trim();
        if (!n) continue;
        if (seen.has(n)) out.push({ category: label, name: n });
        else seen.add(n);
      }
    };
    scan("IP set", spec.ip_sets);
    scan("App port profile", spec.app_port_profiles);
    scan("Firewall rule", spec.firewall_rules);
    scan("NAT rule", spec.nat_rules);
    scan("Static route", spec.static_routes);
    return out;
  }, [spec]);

  const hasDuplicates = duplicateNames.length > 0;

  const canSave =
    hydrated &&
    !!spec.target.org &&
    !!spec.target.vdc &&
    !!spec.target.edge_id &&
    !hasDuplicates &&
    (isEdit || name.trim().length > 0);

  const isBusy = createMutation.isPending || updateMutation.isPending;

  const handleSave = async () => {
    setError(null);
    try {
      if (isEdit) {
        await updateMutation.mutateAsync(spec);
        navigate(`/deployments/${id}`);
      } else {
        const created = await createMutation.mutateAsync({
          name: name.trim(),
          description: description.trim() || null,
          spec,
        });
        navigate(`/deployments/${created.id}`);
      }
    } catch (err) {
      setError(describeApiError(err));
    }
  };

  if (isEdit && editorQuery.isLoading) {
    return (
      <div className="p-6 flex items-center gap-2 text-sm text-clr-text-secondary">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading deployment…
      </div>
    );
  }

  if (isEdit && editorQuery.isError) {
    return (
      <div className="p-6 text-sm text-clr-danger flex items-center gap-2">
        <AlertCircle className="h-4 w-4" />
        Failed to load deployment: {describeApiError(editorQuery.error)}
      </div>
    );
  }

  return (
    <div className="p-4 max-w-2xl space-y-3">
      <div className="flex items-center gap-3">
        <Link
          to={isEdit ? `/deployments/${id}` : "/deployments"}
          className="text-clr-text-secondary hover:text-clr-text text-xs flex items-center gap-1"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back
        </Link>
        <h1 className="text-lg font-semibold text-clr-text tracking-tight">
          {isEdit
            ? `Edit deployment${
                editorQuery.data ? ` — ${editorQuery.data.kind}` : ""
              }`
            : "New deployment"}
        </h1>
      </div>

      {!isEdit && (
        <section className="border border-clr-border rounded-sm bg-white p-3 space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-clr-text">
            Identity
          </h2>
          <FormInput
            label="Deployment name"
            value={name}
            onChange={setName}
            placeholder="e.g. prod-edge-gateway"
          />
          <FormInput
            label="Description"
            value={description}
            onChange={setDescription}
            placeholder="Optional — purpose, owner, etc."
          />
        </section>
      )}

      {isEdit && editorQuery.data && !editorQuery.data.has_state && (
        <div className="rounded-sm border border-clr-warning bg-clr-warning/10 px-3 py-2 text-xs text-clr-text">
          This deployment has no Terraform state yet — editing the empty
          spec. Save, then run Plan + Apply to create resources in VCD.
        </div>
      )}

      {isEdit && isMigrationKind && editorQuery.data?.has_state && (
        <div className="rounded-sm border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 space-y-1">
          <div className="font-medium flex items-center gap-1">
            <AlertCircle className="h-3.5 w-3.5" />
            Migration deployment — Terraform addresses will be rewritten
          </div>
          <div>
            The editor regenerates resource slugs from rule names
            (e.g. <code className="font-mono">tcp_53</code> →
            {" "}<code className="font-mono">ttc_fw_tcp_53</code>). On
            save, the backend aligns the existing state to the new
            addresses automatically, but any slug that cannot be matched
            by name will show as destroy+create on the next Plan.
            Review the plan output carefully before Apply.
          </div>
        </div>
      )}

      {hasDuplicates && (
        <div className="rounded-sm border border-clr-danger bg-red-50 px-3 py-2 text-xs text-clr-danger space-y-1">
          <div className="font-medium flex items-center gap-1">
            <AlertCircle className="h-3.5 w-3.5" />
            Duplicate names — save blocked
          </div>
          <ul className="list-disc pl-5 space-y-0.5">
            {duplicateNames.map((d, i) => (
              <li key={`${d.category}-${d.name}-${i}`}>
                <span className="font-medium">{d.category}:</span>{" "}
                <code className="font-mono">{d.name}</code>
              </li>
            ))}
          </ul>
          <div className="text-[11px] opacity-80">
            Names must be unique within each category — VCD enforces
            this and rule references would otherwise be ambiguous.
          </div>
        </div>
      )}

      <TargetPicker
        target={spec.target}
        disabled={targetLocked}
        onChange={(t) => setSpec({ ...spec, target: t })}
      />

      <RuleSection
        title="IP sets"
        icon={Server}
        count={spec.ip_sets.length}
        onAdd={() =>
          setSpec({ ...spec, ip_sets: [...spec.ip_sets, newIpSet()] })
        }
      >
        <IpSetsEditor
          ipSets={spec.ip_sets}
          onChange={(v) => setSpec({ ...spec, ip_sets: v })}
        />
      </RuleSection>

      <RuleSection
        title="App port profiles"
        icon={Network}
        count={spec.app_port_profiles.length}
        onAdd={() =>
          setSpec({
            ...spec,
            app_port_profiles: [
              ...spec.app_port_profiles,
              newAppPortProfile(),
            ],
          })
        }
      >
        <AppPortProfilesEditor
          profiles={spec.app_port_profiles}
          onChange={(v) => setSpec({ ...spec, app_port_profiles: v })}
        />
      </RuleSection>

      <RuleSection
        title="Firewall rules"
        icon={ShieldCheck}
        count={spec.firewall_rules.length}
        onAdd={() =>
          setSpec({
            ...spec,
            firewall_rules: [...spec.firewall_rules, newFirewallRule()],
          })
        }
      >
        <FirewallEditor
          rules={spec.firewall_rules}
          ipSetNames={ipSetNames}
          profileNames={profileNames}
          onChange={(v) => setSpec({ ...spec, firewall_rules: v })}
        />
      </RuleSection>

      <RuleSection
        title="NAT rules"
        icon={Shuffle}
        count={spec.nat_rules.length}
        onAdd={() =>
          setSpec({
            ...spec,
            nat_rules: [...spec.nat_rules, newNatRule()],
          })
        }
      >
        <NatEditor
          rules={spec.nat_rules}
          profileNames={profileNames}
          onChange={(v) => setSpec({ ...spec, nat_rules: v })}
        />
      </RuleSection>

      <RuleSection
        title="Static routes"
        icon={RouteIcon}
        count={spec.static_routes.length}
        onAdd={() =>
          setSpec({
            ...spec,
            static_routes: [...spec.static_routes, newStaticRoute()],
          })
        }
      >
        <StaticRoutesEditor
          routes={spec.static_routes}
          onChange={(v) => setSpec({ ...spec, static_routes: v })}
        />
      </RuleSection>

      {error && (
        <div className="rounded-sm border border-clr-danger bg-clr-danger/10 px-3 py-2 text-xs text-clr-danger flex items-start gap-2">
          <AlertCircle className="h-3.5 w-3.5 mt-0.5" />
          <span className="whitespace-pre-wrap break-all">{error}</span>
        </div>
      )}

      <div className="flex items-center justify-end gap-2 sticky bottom-0 bg-clr-background/95 pt-2 pb-1">
        <Link
          to={isEdit ? `/deployments/${id}` : "/deployments"}
          className="rounded-sm border border-clr-border bg-white text-clr-text-secondary text-xs px-3 py-1.5 hover:text-clr-text hover:border-clr-action"
        >
          Cancel
        </Link>
        <button
          type="button"
          onClick={handleSave}
          disabled={!canSave || isBusy}
          className="flex items-center gap-1.5 rounded-sm bg-clr-action text-white text-xs font-medium px-3 py-1.5 hover:bg-clr-action-hover disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isBusy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          {isEdit ? "Save changes" : "Create deployment"}
        </button>
      </div>
    </div>
  );
}
