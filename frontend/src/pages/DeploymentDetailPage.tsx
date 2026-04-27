import { useMemo, useRef, useState, useEffect, type ReactNode } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  History,
  FileCode2,
  Info,
  Lock,
  LockOpen,
  RotateCcw,
  Loader2,
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Play,
  Pencil,
  Save,
  User,
  Clock,
  Eye,
  GitCompare,
  RefreshCw,
  Cloud,
  Wrench,
  Sprout,
  BookMarked,
  X,
} from "lucide-react";
import { diffLines } from "diff";
import { isAxiosError } from "axios";
import {
  useDeployment,
  useDeploymentVersions,
  useRollbackPrepare,
  useRollbackConfirm,
  usePinVersion,
  useDeploymentHcl,
  useDeploymentPlan,
  useDeploymentApply,
  useOrphanScan,
  useCleanupOrphans,
  useVersionHcl,
  useVersionState,
  type DeploymentVersion,
} from "@/api/deploymentsApi";
import {
  useDriftReports,
  useTriggerDriftCheck,
  useReviewDriftReport,
  useDriftReport,
  type DriftReportSummary,
} from "@/api/driftApi";
import { useConfigStore } from "@/store/useConfigStore";
import { cn } from "@/utils/cn";

type Tab = "overview" | "versions" | "hcl" | "drift";

const SOURCE_META: Record<
  string,
  { label: string; color: string; icon: typeof Info }
> = {
  apply: { label: "Apply", color: "text-clr-action bg-clr-action/10", icon: Wrench },
  drift: { label: "Drift (cloud)", color: "text-orange-700 bg-orange-50", icon: Cloud },
  migration: { label: "Migration", color: "text-emerald-700 bg-emerald-50", icon: Sprout },
  migration_baseline: { label: "Migration", color: "text-emerald-700 bg-emerald-50", icon: Sprout },
  named_snapshot: { label: "Named", color: "text-indigo-700 bg-indigo-50", icon: BookMarked },
  rollback: { label: "Rollback", color: "text-purple-700 bg-purple-50", icon: RotateCcw },
};

function SourceBadge({ source }: { source: string }) {
  const meta = SOURCE_META[source] ?? {
    label: source,
    color: "text-clr-text-secondary bg-clr-near-white",
    icon: Info,
  };
  const Icon = meta.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium",
        meta.color,
      )}
    >
      <Icon className="h-3 w-3" />
      {meta.label}
    </span>
  );
}

function getErrorMessage(error: unknown): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  }
  if (error instanceof Error) return error.message;
  return "Request failed.";
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString();
}

/* ------------------------------------------------------------------ */
/*  Rollback confirm modal                                             */
/* ------------------------------------------------------------------ */

interface RollbackModalProps {
  deploymentId: string;
  version: DeploymentVersion;
  onClose: () => void;
}

function RollbackModal({
  deploymentId,
  version,
  onClose,
}: RollbackModalProps) {
  const prepare = useRollbackPrepare(deploymentId);
  const confirm = useRollbackConfirm(deploymentId);
  const planStatus = useConfigStore((s) => s.planStatus);
  const currentOp = useConfigStore((s) => s.currentOperationId);
  const setOp = useConfigStore((s) => s.setOperation);
  const openTerminal = useConfigStore((s) => s.openTerminal);

  const [prepareOpId, setPrepareOpId] = useState<string | null>(null);

  const handlePrepare = async () => {
    try {
      const res = await prepare.mutateAsync(version.version_num);
      setPrepareOpId(res.operation_id);
      setOp(res.operation_id, "planning");
      openTerminal();
    } catch {
      /* error shown from prepare.error */
    }
  };

  const handleConfirm = async () => {
    if (!prepareOpId) return;
    try {
      const res = await confirm.mutateAsync(prepareOpId);
      setOp(res.operation_id, "applying");
      openTerminal();
    } catch {
      /* error shown from confirm.error */
    }
  };

  const planReady = Boolean(
    prepareOpId && currentOp === prepareOpId && planStatus === "planned",
  );

  const planFailed = Boolean(
    prepareOpId && currentOp === prepareOpId && planStatus === "error",
  );

  const applyDone = Boolean(
    prepareOpId && currentOp !== prepareOpId && planStatus === "applied",
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-sm bg-white border border-clr-border shadow-lg">
        <div className="flex items-center justify-between px-4 py-3 border-b border-clr-border">
          <h3 className="text-sm font-semibold text-clr-text flex items-center gap-2">
            <RotateCcw className="h-4 w-4" />
            Rollback to v{version.version_num}
          </h3>
          <button
            onClick={onClose}
            className="text-clr-placeholder hover:text-clr-text text-lg leading-none"
          >
            ×
          </button>
        </div>

        <div className="p-4 space-y-3 text-xs">
          <div className="rounded-sm border border-clr-border bg-clr-near-white p-3">
            <div className="flex justify-between">
              <span className="font-medium">v{version.version_num}</span>
              <span className="text-clr-text-secondary">
                {fmtDate(version.created_at)}
              </span>
            </div>
            <div className="text-clr-text-secondary mt-1">
              source: <span className="font-mono">{version.source}</span>
              {version.label && (
                <>
                  {" · "}
                  label: <span className="font-mono">{version.label}</span>
                </>
              )}
              {" · "}
              by <span className="font-mono">{version.created_by}</span>
            </div>
          </div>

          {!prepareOpId && (
            <>
              <p className="text-clr-text">
                Terraform will compute a plan that reverts the deployment to
                this version. No changes are applied until you confirm.
              </p>
              <p className="text-clr-text-secondary">
                The current live state will be backed up to{" "}
                <code className="font-mono text-[10px] bg-clr-near-white px-1 rounded">
                  pre-rollback/terraform.tfstate
                </code>{" "}
                before any destructive action.
              </p>
            </>
          )}

          {prepare.isError && (
            <div className="flex items-start gap-2 rounded-sm border border-clr-danger/30 bg-red-50 p-2">
              <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
              <p className="text-clr-danger break-words">
                {getErrorMessage(prepare.error)}
              </p>
            </div>
          )}

          {prepareOpId && !planReady && !planFailed && !applyDone && (
            <div className="flex items-center gap-2 text-clr-text-secondary">
              <Loader2 className="h-4 w-4 animate-spin" />
              {planStatus === "applying"
                ? "Applying rollback…"
                : "Running terraform plan — open the terminal to watch output"}
            </div>
          )}

          {planReady && (
            <div className="flex items-start gap-2 rounded-sm border border-emerald-300 bg-emerald-50 p-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-600 flex-none mt-0.5" />
              <p className="text-emerald-800">
                Plan succeeded. Review the diff in the terminal, then click{" "}
                <strong>Confirm rollback</strong> to apply.
              </p>
            </div>
          )}

          {planFailed && (
            <div className="flex items-start gap-2 rounded-sm border border-clr-danger/30 bg-red-50 p-2">
              <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
              <p className="text-clr-danger">
                Plan failed. Check the terminal for errors.
              </p>
            </div>
          )}

          {applyDone && (
            <div className="flex items-start gap-2 rounded-sm border border-emerald-300 bg-emerald-50 p-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-600 flex-none mt-0.5" />
              <p className="text-emerald-800">
                Rollback complete. A new version has been appended to history.
              </p>
            </div>
          )}

          {confirm.isError && (
            <div className="flex items-start gap-2 rounded-sm border border-clr-danger/30 bg-red-50 p-2">
              <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
              <p className="text-clr-danger break-words">
                {getErrorMessage(confirm.error)}
              </p>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-clr-border bg-clr-near-white">
          <button
            onClick={onClose}
            className="rounded-sm px-3 py-1.5 text-xs text-clr-text-secondary hover:text-clr-text"
          >
            {applyDone ? "Close" : "Cancel"}
          </button>

          {!prepareOpId && (
            <button
              onClick={handlePrepare}
              disabled={prepare.isPending}
              className="flex items-center gap-1.5 rounded-sm bg-clr-action text-white text-xs font-medium px-3 py-1.5 hover:bg-clr-action-hover disabled:opacity-50"
            >
              {prepare.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              Prepare plan
            </button>
          )}

          {planReady && (
            <button
              onClick={handleConfirm}
              disabled={confirm.isPending}
              className="flex items-center gap-1.5 rounded-sm bg-clr-danger text-white text-xs font-medium px-3 py-1.5 hover:bg-clr-danger/90 disabled:opacity-50"
            >
              {confirm.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RotateCcw className="h-3.5 w-3.5" />
              )}
              Confirm rollback
            </button>
          )}
        </div>
      </div>
    </div>
  );
}


/* ------------------------------------------------------------------ */
/*  View HCL modal                                                     */
/* ------------------------------------------------------------------ */

interface ViewHclModalProps {
  deploymentId: string;
  version: DeploymentVersion;
  onClose: () => void;
}

function ViewHclModal({ deploymentId, version, onClose }: ViewHclModalProps) {
  const isDrift = version.source === "drift";
  const [view, setView] = useState<"hcl" | "state">(isDrift ? "state" : "hcl");

  const hclQ = useVersionHcl(deploymentId, version.version_num);
  const stateQ = useVersionState(
    deploymentId, version.version_num, view === "state",
  );

  const activeLoading = view === "hcl" ? hclQ.isLoading : stateQ.isLoading;
  const activeError = view === "hcl" ? hclQ.isError : stateQ.isError;
  const activeErr = view === "hcl" ? hclQ.error : stateQ.error;

  const stateText =
    stateQ.data !== undefined ? JSON.stringify(stateQ.data, null, 2) : "";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-4xl h-[80vh] rounded-sm bg-white border border-clr-border shadow-lg flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-clr-border">
          <h3 className="text-sm font-semibold text-clr-text flex items-center gap-2">
            <Eye className="h-4 w-4" />
            v{version.version_num}
            <SourceBadge source={version.source} />
            {version.label && (
              <span className="text-[10px] font-normal text-clr-text-secondary">
                {version.label}
              </span>
            )}
          </h3>
          <button
            onClick={onClose}
            className="text-clr-placeholder hover:text-clr-text"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex items-center gap-1 px-3 pt-2 border-b border-clr-border">
          <button
            onClick={() => setView("hcl")}
            className={cn(
              "text-xs px-3 py-1.5 border-b-2 -mb-px",
              view === "hcl"
                ? "border-clr-action text-clr-action"
                : "border-transparent text-clr-text-secondary hover:text-clr-text",
            )}
          >
            main.tf (HCL)
          </button>
          <button
            onClick={() => setView("state")}
            className={cn(
              "text-xs px-3 py-1.5 border-b-2 -mb-px",
              view === "state"
                ? "border-clr-action text-clr-action"
                : "border-transparent text-clr-text-secondary hover:text-clr-text",
            )}
          >
            terraform.tfstate
          </button>
        </div>

        {isDrift && view === "hcl" && (
          <div className="px-3 py-2 text-[11px] bg-orange-50 text-orange-900 border-b border-orange-200">
            Drift snapshots capture VCD state only. HCL is unchanged from the
            previous version — to inspect what changed in cloud, switch to the
            tfstate tab or open the drift report.
          </div>
        )}

        <div className="flex-1 overflow-auto p-3 bg-slate-900">
          {activeLoading && (
            <div className="text-xs text-slate-400 flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading…
            </div>
          )}
          {activeError && (
            <div className="text-xs text-rose-300">{getErrorMessage(activeErr)}</div>
          )}
          {!activeLoading && !activeError && view === "hcl" && hclQ.data && (
            <pre className="font-mono text-[12px] leading-relaxed text-slate-100 whitespace-pre-wrap break-words">
              {hclQ.data}
            </pre>
          )}
          {!activeLoading && !activeError && view === "state" && stateText && (
            <pre className="font-mono text-[12px] leading-relaxed text-slate-100 whitespace-pre-wrap break-words">
              {stateText}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Compare versions modal                                             */
/* ------------------------------------------------------------------ */

interface CompareModalProps {
  deploymentId: string;
  versions: DeploymentVersion[];
  initialBase: number;
  initialTarget: number;
  onClose: () => void;
}

function canonicalStateText(raw: unknown): string {
  if (raw === undefined || raw === null) return "";
  // Extract resources only — tfstate serial/lineage/outputs change every run
  // and drown the signal. Sort keys + resources by address for stable diff.
  const state = raw as {
    resources?: Array<{
      module?: string;
      mode?: string;
      type?: string;
      name?: string;
      instances?: unknown[];
    }>;
  };
  const resources = (state.resources ?? [])
    .map((r) => ({
      address: `${r.module ? r.module + "." : ""}${r.mode === "data" ? "data." : ""}${r.type}.${r.name}`,
      mode: r.mode,
      type: r.type,
      name: r.name,
      instances: r.instances,
    }))
    .sort((a, b) => a.address.localeCompare(b.address));
  const sortKeys = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(sortKeys);
    if (v && typeof v === "object") {
      const out: Record<string, unknown> = {};
      for (const k of Object.keys(v as object).sort()) {
        out[k] = sortKeys((v as Record<string, unknown>)[k]);
      }
      return out;
    }
    return v;
  };
  return JSON.stringify(sortKeys(resources), null, 2);
}

function CompareModal({
  deploymentId,
  versions,
  initialBase,
  initialTarget,
  onClose,
}: CompareModalProps) {
  const [baseNum, setBaseNum] = useState(initialBase);
  const [targetNum, setTargetNum] = useState(initialTarget);

  const baseVersion = versions.find((v) => v.version_num === baseNum);
  const targetVersion = versions.find((v) => v.version_num === targetNum);
  const eitherIsDrift =
    baseVersion?.source === "drift" || targetVersion?.source === "drift";
  const [view, setView] = useState<"hcl" | "state">(
    eitherIsDrift ? "state" : "hcl",
  );

  useEffect(() => {
    setView(eitherIsDrift ? "state" : "hcl");
  }, [eitherIsDrift]);

  const baseHcl = useVersionHcl(deploymentId, baseNum);
  const targetHcl = useVersionHcl(deploymentId, targetNum);
  const baseState = useVersionState(deploymentId, baseNum, view === "state");
  const targetState = useVersionState(deploymentId, targetNum, view === "state");

  const loading =
    view === "hcl"
      ? baseHcl.isLoading || targetHcl.isLoading
      : baseState.isLoading || targetState.isLoading;
  const error =
    view === "hcl"
      ? baseHcl.error || targetHcl.error
      : baseState.error || targetState.error;

  const baseText =
    view === "hcl" ? baseHcl.data : canonicalStateText(baseState.data);
  const targetText =
    view === "hcl" ? targetHcl.data : canonicalStateText(targetState.data);

  const parts =
    baseText !== undefined && targetText !== undefined
      ? diffLines(baseText, targetText)
      : [];

  const addedLines = parts
    .filter((p) => p.added)
    .reduce((n, p) => n + (p.count ?? 0), 0);
  const removedLines = parts
    .filter((p) => p.removed)
    .reduce((n, p) => n + (p.count ?? 0), 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-5xl h-[85vh] rounded-sm bg-white border border-clr-border shadow-lg flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-clr-border">
          <h3 className="text-sm font-semibold text-clr-text flex items-center gap-2">
            <GitCompare className="h-4 w-4" />
            Compare versions
          </h3>
          <button
            onClick={onClose}
            className="text-clr-placeholder hover:text-clr-text"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-4 py-3 border-b border-clr-border bg-clr-near-white flex items-center gap-3 text-xs">
          <label className="flex items-center gap-2">
            <span className="text-clr-text-secondary">Base:</span>
            <select
              value={baseNum}
              onChange={(e) => setBaseNum(parseInt(e.target.value, 10))}
              className="rounded-sm border border-clr-border bg-white px-2 py-1 font-mono"
            >
              {versions.map((v) => (
                <option key={v.version_num} value={v.version_num}>
                  v{v.version_num} · {v.source}
                  {v.label ? ` (${v.label})` : ""}
                </option>
              ))}
            </select>
          </label>
          <span className="text-clr-text-secondary">→</span>
          <label className="flex items-center gap-2">
            <span className="text-clr-text-secondary">Target:</span>
            <select
              value={targetNum}
              onChange={(e) => setTargetNum(parseInt(e.target.value, 10))}
              className="rounded-sm border border-clr-border bg-white px-2 py-1 font-mono"
            >
              {versions.map((v) => (
                <option key={v.version_num} value={v.version_num}>
                  v{v.version_num} · {v.source}
                  {v.label ? ` (${v.label})` : ""}
                </option>
              ))}
            </select>
          </label>
          <div className="ml-auto flex items-center gap-3">
            <div className="inline-flex rounded-sm border border-clr-border overflow-hidden">
              <button
                onClick={() => setView("hcl")}
                className={cn(
                  "px-2 py-1 text-[11px]",
                  view === "hcl"
                    ? "bg-clr-action text-white"
                    : "bg-white text-clr-text-secondary",
                )}
              >
                HCL
              </button>
              <button
                onClick={() => setView("state")}
                className={cn(
                  "px-2 py-1 text-[11px]",
                  view === "state"
                    ? "bg-clr-action text-white"
                    : "bg-white text-clr-text-secondary",
                )}
              >
                State
              </button>
            </div>
            <span className="text-emerald-700 font-mono">+{addedLines}</span>
            <span className="text-rose-700 font-mono">-{removedLines}</span>
          </div>
        </div>
        {eitherIsDrift && view === "hcl" && (
          <div className="px-4 py-2 bg-amber-50 border-b border-amber-200 text-[11px] text-amber-800">
            Drift snapshots carry the same HCL as the previous version — real
            changes live in state. Switch to <b>State</b> to see them.
          </div>
        )}

        <div className="flex-1 overflow-auto bg-slate-900 font-mono text-[12px] leading-relaxed">
          {loading && (
            <div className="p-4 text-slate-400 flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading HCL…
            </div>
          )}
          {error && (
            <div className="p-4 text-rose-300">{getErrorMessage(error)}</div>
          )}
          {!loading &&
            !error &&
            (baseNum === targetNum ? (
              <div className="p-4 text-slate-400">
                Same version — no diff.
              </div>
            ) : addedLines === 0 && removedLines === 0 ? (
              <div className="p-4 text-slate-400">
                No changes between v{baseNum} and v{targetNum}.
              </div>
            ) : (
              parts.map((part, i) => {
                const lines = part.value.split("\n");
                if (lines[lines.length - 1] === "") lines.pop();
                return lines.map((line, j) => {
                  const prefix = part.added ? "+" : part.removed ? "-" : " ";
                  const cls = part.added
                    ? "bg-emerald-900/40 text-emerald-200"
                    : part.removed
                      ? "bg-rose-900/40 text-rose-200"
                      : "text-slate-400";
                  return (
                    <div
                      key={`${i}-${j}`}
                      className={cn("px-3 whitespace-pre", cls)}
                    >
                      {prefix} {line}
                    </div>
                  );
                });
              })
            ))}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Versions tab                                                       */
/* ------------------------------------------------------------------ */

function VersionsTab({ deploymentId }: { deploymentId: string }) {
  const { data, isLoading, isError, error, refetch, isFetching } =
    useDeploymentVersions(deploymentId);
  const [rollbackTarget, setRollbackTarget] = useState<DeploymentVersion | null>(
    null,
  );
  const [viewTarget, setViewTarget] = useState<DeploymentVersion | null>(null);
  const [compareOpen, setCompareOpen] = useState<{
    base: number;
    target: number;
  } | null>(null);
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const [hideDismissed, setHideDismissed] = useState<boolean>(true);
  const pinMutation = usePinVersion(deploymentId);

  const allItems = [...(data?.items ?? [])].sort(
    (a, b) => b.version_num - a.version_num,
  );
  const currentVersionNum = allItems[0]?.version_num ?? null;

  const filterGroups: { key: string; label: string; match: (s: string) => boolean }[] = [
    { key: "all", label: "All", match: () => true },
    { key: "apply", label: "Terraform apply", match: (s) => s === "apply" },
    { key: "drift", label: "Drift (cloud)", match: (s) => s === "drift" },
    {
      key: "migration",
      label: "Migration",
      match: (s) => s === "migration" || s === "migration_baseline",
    },
    { key: "named_snapshot", label: "Named", match: (s) => s === "named_snapshot" },
    { key: "rollback", label: "Rollback", match: (s) => s === "rollback" },
  ];
  const activeFilter =
    filterGroups.find((g) => g.key === sourceFilter) ?? filterGroups[0];
  const items = allItems
    .filter((v) => activeFilter.match(v.source))
    .filter((v) => !(hideDismissed && v.label === "dismissed"));
  const dismissedCount = allItems.filter(
    (v) => v.label === "dismissed",
  ).length;

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-clr-text-secondary p-4">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading versions…
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-start gap-2 rounded-sm border border-clr-danger/30 bg-red-50 p-3 m-4">
        <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
        <p className="text-xs text-clr-danger">{getErrorMessage(error)}</p>
      </div>
    );
  }

  if (allItems.length === 0) {
    return (
      <div className="p-6 text-xs text-clr-text-secondary">
        No version snapshots yet. Run a Plan + Apply from the Migration page to
        create the first one.
      </div>
    );
  }

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
        <div className="flex items-center gap-1 flex-wrap">
          {filterGroups.map((g) => {
            const count = allItems.filter((v) => g.match(v.source)).length;
            const active = sourceFilter === g.key;
            return (
              <button
                key={g.key}
                onClick={() => setSourceFilter(g.key)}
                className={cn(
                  "text-xs rounded-sm border px-2 py-1 transition-colors",
                  active
                    ? "border-clr-action bg-clr-action/10 text-clr-action"
                    : "border-clr-border text-clr-text-secondary hover:text-clr-text",
                )}
              >
                {g.label}
                <span className="ml-1 text-[10px] opacity-70">{count}</span>
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              const a = allItems[0];
              const b = allItems[1];
              if (a && b) {
                setCompareOpen({
                  base: b.version_num,
                  target: a.version_num,
                });
              }
            }}
            disabled={allItems.length < 2}
            className="inline-flex items-center gap-1 text-xs text-clr-action hover:underline disabled:opacity-40 disabled:no-underline"
          >
            <GitCompare className="h-3 w-3" />
            Compare versions
          </button>
          {dismissedCount > 0 && (
            <label
              className="inline-flex items-center gap-1.5 text-xs text-clr-text-secondary cursor-pointer select-none"
              title="Hide drift snapshots that were reviewed as 'Ignore'"
            >
              <input
                type="checkbox"
                checked={hideDismissed}
                onChange={(e) => setHideDismissed(e.target.checked)}
                className="h-3 w-3 accent-clr-action"
              />
              Hide dismissed ({dismissedCount})
            </label>
          )}
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="text-xs text-clr-action hover:underline disabled:opacity-50"
          >
            {isFetching ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      <div className="border border-clr-border rounded-sm overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-clr-near-white text-clr-text-secondary">
            <tr>
              <th className="text-left px-3 py-2 font-medium">Version</th>
              <th className="text-left px-3 py-2 font-medium">Source</th>
              <th className="text-left px-3 py-2 font-medium">Label</th>
              <th className="text-left px-3 py-2 font-medium">Created</th>
              <th className="text-left px-3 py-2 font-medium">By</th>
              <th className="text-right px-3 py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((v) => {
              const isCurrent = v.version_num === currentVersionNum;
              return (
                <tr
                  key={v.version_num}
                  className={cn(
                    "border-t border-clr-border",
                    isCurrent && "bg-clr-action/5",
                  )}
                >
                  <td className="px-3 py-2 font-mono font-semibold">
                    v{v.version_num}
                    {isCurrent && (
                      <span className="ml-2 text-[10px] font-sans font-medium text-clr-action bg-clr-action/10 rounded px-1.5 py-0.5">
                        CURRENT
                      </span>
                    )}
                    {v.is_pinned && (
                      <Lock className="inline-block h-3 w-3 ml-1.5 text-amber-600" />
                    )}
                    {v.label === "dismissed" && (
                      <span
                        className="ml-2 text-[10px] font-sans font-medium text-clr-text-secondary bg-clr-near-white border border-clr-border rounded px-1.5 py-0.5"
                        title="Drift reviewed as Ignore — snapshot marked dismissed"
                      >
                        DISMISSED
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <SourceBadge source={v.source} />
                  </td>
                  <td className="px-3 py-2 text-clr-text-secondary">
                    {v.label || "—"}
                  </td>
                  <td className="px-3 py-2 text-clr-text-secondary whitespace-nowrap">
                    {fmtDate(v.created_at)}
                  </td>
                  <td className="px-3 py-2 font-mono text-clr-text-secondary">
                    {v.created_by}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="inline-flex items-center gap-3">
                      <button
                        onClick={() => setViewTarget(v)}
                        title="View HCL"
                        className="inline-flex items-center gap-1 text-xs text-clr-text-secondary hover:text-clr-action"
                      >
                        <Eye className="h-3 w-3" />
                        View
                      </button>
                      <button
                        onClick={() => {
                          const prev = allItems.find(
                            (x) => x.version_num === v.version_num - 1,
                          );
                          setCompareOpen({
                            base: prev ? prev.version_num : v.version_num,
                            target: v.version_num,
                          });
                        }}
                        title="Compare with previous version"
                        className="inline-flex items-center gap-1 text-xs text-clr-text-secondary hover:text-clr-action"
                      >
                        <GitCompare className="h-3 w-3" />
                        Diff
                      </button>
                      <button
                        onClick={() =>
                          pinMutation.mutate({
                            versionNum: v.version_num,
                            pinned: !v.is_pinned,
                          })
                        }
                        disabled={pinMutation.isPending}
                        title={
                          v.is_pinned
                            ? "Unpin (allow rotation)"
                            : "Pin (never rotate)"
                        }
                        className="inline-flex items-center gap-1 text-xs text-clr-text-secondary hover:text-amber-700 disabled:opacity-40"
                      >
                        {v.is_pinned ? (
                          <LockOpen className="h-3 w-3" />
                        ) : (
                          <Lock className="h-3 w-3" />
                        )}
                        {v.is_pinned ? "Unpin" : "Pin"}
                      </button>
                      <button
                        onClick={() => setRollbackTarget(v)}
                        disabled={isCurrent}
                        title={
                          isCurrent
                            ? "This is the current version"
                            : "Rollback here"
                        }
                        className="inline-flex items-center gap-1 text-xs text-clr-action hover:underline disabled:opacity-40 disabled:cursor-not-allowed disabled:no-underline"
                      >
                        <RotateCcw className="h-3 w-3" />
                        Rollback
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {rollbackTarget && (
        <RollbackModal
          deploymentId={deploymentId}
          version={rollbackTarget}
          onClose={() => setRollbackTarget(null)}
        />
      )}
      {viewTarget && (
        <ViewHclModal
          deploymentId={deploymentId}
          version={viewTarget}
          onClose={() => setViewTarget(null)}
        />
      )}
      {compareOpen && (
        <CompareModal
          deploymentId={deploymentId}
          versions={allItems}
          initialBase={compareOpen.base}
          initialTarget={compareOpen.target}
          onClose={() => setCompareOpen(null)}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Drift tab                                                          */
/* ------------------------------------------------------------------ */

function DriftTab({ deploymentId }: { deploymentId: string }) {
  const { data: deployment } = useDeployment(deploymentId);
  const { data: reports, isLoading, isError, error, refetch, isFetching } =
    useDriftReports(deploymentId);
  const trigger = useTriggerDriftCheck(deploymentId);
  const review = useReviewDriftReport(deploymentId);
  const [detailId, setDetailId] = useState<string | null>(null);

  const handleTrigger = async () => {
    try {
      await trigger.mutateAsync();
      setTimeout(() => refetch(), 1500);
    } catch {
      /* surfaced via mutation error */
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-clr-text-secondary p-4">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading drift reports…
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-start gap-2 rounded-sm border border-clr-danger/30 bg-red-50 p-3 m-4">
        <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
        <p className="text-xs text-clr-danger">{getErrorMessage(error)}</p>
      </div>
    );
  }

  const rows = reports ?? [];

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="text-xs text-clr-text-secondary">
          Drift sync compares cloud state (VCD) against last snapshot. Detected
          changes create a new <span className="font-mono">drift</span> version
          you can rollback to.
          {deployment?.last_drift_check && (
            <span className="block mt-1">
              Last check: {fmtDate(deployment.last_drift_check)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="text-xs text-clr-action hover:underline disabled:opacity-50"
          >
            {isFetching ? "Refreshing…" : "Refresh"}
          </button>
          <button
            onClick={handleTrigger}
            disabled={trigger.isPending}
            className="inline-flex items-center gap-1.5 rounded-sm bg-clr-action text-white text-xs font-medium px-3 py-1.5 hover:bg-clr-action-hover disabled:opacity-50"
          >
            {trigger.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            Check drift now
          </button>
        </div>
      </div>

      {trigger.isError && (
        <div className="flex items-start gap-2 rounded-sm border border-clr-danger/30 bg-red-50 p-2">
          <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
          <p className="text-xs text-clr-danger break-words">
            {getErrorMessage(trigger.error)}
          </p>
        </div>
      )}
      {trigger.isSuccess && (
        <div className="rounded-sm border border-emerald-200 bg-emerald-50 p-2 text-xs text-emerald-800">
          Drift check scheduled. Reports list refreshes shortly.
        </div>
      )}

      {rows.length === 0 ? (
        <div className="p-6 text-xs text-clr-text-secondary border border-dashed border-clr-border rounded-sm text-center">
          No drift reports yet. Trigger a check or wait for the daily cron.
        </div>
      ) : (
        <div className="border border-clr-border rounded-sm overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-clr-near-white text-clr-text-secondary">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Ran at</th>
                <th className="text-left px-3 py-2 font-medium">Status</th>
                <th className="text-left px-3 py-2 font-medium">Changes</th>
                <th className="text-left px-3 py-2 font-medium">Snapshot</th>
                <th className="text-left px-3 py-2 font-medium">Resolution</th>
                <th className="text-right px-3 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <DriftReportRow
                  key={r.id}
                  report={r}
                  onView={() => setDetailId(r.id)}
                  onReview={(res) =>
                    review.mutate({ reportId: r.id, resolution: res })
                  }
                  reviewing={review.isPending}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detailId && (
        <DriftReportModal
          reportId={detailId}
          onClose={() => setDetailId(null)}
        />
      )}
    </div>
  );
}

function DriftReportRow({
  report,
  onView,
  onReview,
  reviewing,
}: {
  report: DriftReportSummary;
  onView: () => void;
  onReview: (res: "accepted" | "rolled_back" | "ignored") => void;
  reviewing: boolean;
}) {
  const totalChanges =
    report.additions_count + report.modifications_count + report.deletions_count;

  let statusBadge: { label: string; color: string };
  if (report.error) {
    statusBadge = { label: "Error", color: "text-clr-danger bg-red-50" };
  } else if (report.has_changes === null) {
    statusBadge = {
      label: "Skipped",
      color: "text-clr-text-secondary bg-clr-near-white",
    };
  } else if (report.has_changes) {
    statusBadge = { label: "Drift", color: "text-orange-700 bg-orange-50" };
  } else {
    statusBadge = { label: "Clean", color: "text-emerald-700 bg-emerald-50" };
  }

  const unreviewed =
    report.has_changes && report.resolution === null && !report.error;

  return (
    <tr className="border-t border-clr-border">
      <td className="px-3 py-2 whitespace-nowrap text-clr-text-secondary">
        {fmtDate(report.ran_at)}
      </td>
      <td className="px-3 py-2">
        <span
          className={cn(
            "inline-flex rounded px-1.5 py-0.5 text-[10px] font-medium",
            statusBadge.color,
          )}
        >
          {statusBadge.label}
        </span>
      </td>
      <td className="px-3 py-2 text-clr-text-secondary">
        {totalChanges > 0 ? (
          <span className="font-mono">
            +{report.additions_count} ~{report.modifications_count} -
            {report.deletions_count}
          </span>
        ) : (
          "—"
        )}
      </td>
      <td className="px-3 py-2">
        {report.version_num !== null && report.version_num !== undefined ? (
          <span className="font-mono text-clr-action">v{report.version_num}</span>
        ) : (
          <span className="text-clr-text-secondary">—</span>
        )}
      </td>
      <td className="px-3 py-2 text-clr-text-secondary">
        {report.resolution ?? (unreviewed ? "needs review" : "—")}
        {report.reviewed_by && (
          <span className="block text-[10px]">
            by {report.reviewed_by}
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-right">
        <div className="inline-flex items-center gap-3">
          <button
            onClick={onView}
            className="inline-flex items-center gap-1 text-xs text-clr-text-secondary hover:text-clr-action"
          >
            <Eye className="h-3 w-3" />
            Details
          </button>
          {unreviewed && (
            <>
              <button
                onClick={() => onReview("accepted")}
                disabled={reviewing}
                title="Drift is expected — keep snapshot in history, clear review flag"
                className="text-xs text-emerald-700 hover:underline disabled:opacity-50"
              >
                Accept
              </button>
              <button
                onClick={() => onReview("ignored")}
                disabled={reviewing}
                title="Drift is noise — tag snapshot as 'dismissed' and hide from history by default"
                className="text-xs text-clr-text-secondary hover:underline disabled:opacity-50"
              >
                Ignore
              </button>
            </>
          )}
        </div>
      </td>
    </tr>
  );
}

function DriftReportModal({
  reportId,
  onClose,
}: {
  reportId: string;
  onClose: () => void;
}) {
  const { data, isLoading, isError, error } = useDriftReport(reportId);
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40">
      <div className="bg-white w-[min(900px,95vw)] max-h-[90vh] rounded-sm border border-clr-border flex flex-col">
        <div className="flex items-center justify-between border-b border-clr-border px-4 py-2">
          <div className="text-sm font-medium">Drift report detail</div>
          <button
            onClick={onClose}
            className="text-clr-text-secondary hover:text-clr-text"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="overflow-auto p-4 text-xs">
          {isLoading && (
            <div className="flex items-center gap-2 text-clr-text-secondary">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading…
            </div>
          )}
          {isError && (
            <div className="text-clr-danger">{getErrorMessage(error)}</div>
          )}
          {data && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <div className="text-[10px] uppercase text-clr-text-secondary">
                    Ran at
                  </div>
                  <div>{fmtDate(data.ran_at)}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase text-clr-text-secondary">
                    Snapshot version
                  </div>
                  <div className="font-mono">
                    {data.version_num !== null && data.version_num !== undefined
                      ? `v${data.version_num}`
                      : "—"}
                  </div>
                </div>
              </div>
              {data.error && (
                <div className="rounded-sm border border-clr-danger/30 bg-red-50 p-2 text-clr-danger whitespace-pre-wrap">
                  {data.error}
                </div>
              )}
              <Section title={`Modifications (${data.modifications.length})`}>
                {data.modifications.length ? (
                  <pre className="bg-slate-900 text-slate-100 p-2 rounded-sm overflow-auto text-[11px]">
                    {JSON.stringify(data.modifications, null, 2)}
                  </pre>
                ) : (
                  <div className="text-clr-text-secondary">None</div>
                )}
              </Section>
              <Section title={`Deletions (${data.deletions.length})`}>
                {data.deletions.length ? (
                  <pre className="bg-slate-900 text-slate-100 p-2 rounded-sm overflow-auto text-[11px]">
                    {JSON.stringify(data.deletions, null, 2)}
                  </pre>
                ) : (
                  <div className="text-clr-text-secondary">None</div>
                )}
              </Section>
              <Section title={`Addition hints (${data.additions.length})`}>
                {data.additions.length ? (
                  <pre className="bg-slate-900 text-slate-100 p-2 rounded-sm overflow-auto text-[11px]">
                    {JSON.stringify(data.additions, null, 2)}
                  </pre>
                ) : (
                  <div className="text-clr-text-secondary">None</div>
                )}
              </Section>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div>
      <div className="text-[10px] uppercase text-clr-text-secondary mb-1">
        {title}
      </div>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  HCL tab                                                            */
/* ------------------------------------------------------------------ */

/**
 * Textarea + synced line-number gutter. Scroll on the textarea mirrors
 * into the gutter via ``scrollTop`` on each event. Font metrics
 * (family / size / line-height) are kept identical on both sides so
 * the number always lines up with its row.
 */
function HclEditorWithGutter({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const gutterRef = useRef<HTMLPreElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const lineCount = useMemo(() => {
    if (!value) return 1;
    return value.split("\n").length;
  }, [value]);

  const gutterText = useMemo(
    () => Array.from({ length: lineCount }, (_, i) => i + 1).join("\n"),
    [lineCount],
  );

  const handleScroll = () => {
    const ta = textareaRef.current;
    const g = gutterRef.current;
    if (ta && g) {
      g.scrollTop = ta.scrollTop;
    }
  };

  return (
    <div className="flex h-[500px] w-full rounded-sm border border-clr-border bg-slate-900 overflow-hidden font-mono text-[12px] leading-relaxed">
      <pre
        ref={gutterRef}
        aria-hidden
        className="select-none overflow-hidden py-3 pl-2 pr-2 text-right text-slate-500 bg-slate-800/60 border-r border-slate-700 min-w-[3rem]"
      >
        {gutterText}
      </pre>
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onScroll={handleScroll}
        spellCheck={false}
        className="flex-1 py-3 pl-3 pr-3 bg-slate-900 text-slate-100 focus:outline-none resize-none overflow-auto"
      />
    </div>
  );
}

function HclTab({
  deploymentId,
  onGoToDrift,
}: {
  deploymentId: string;
  onGoToDrift: () => void;
}) {
  const { data: remoteHcl, isLoading, isError, error, refetch } =
    useDeploymentHcl(deploymentId);
  const { data: deployment } = useDeployment(deploymentId);
  const [draft, setDraft] = useState<string>("");
  const [dirty, setDirty] = useState(false);

  const planMut = useDeploymentPlan(deploymentId);
  const applyMut = useDeploymentApply(deploymentId);
  const orphanScan = useOrphanScan(deploymentId);
  const cleanupMut = useCleanupOrphans(deploymentId);

  const planStatus = useConfigStore((s) => s.planStatus);
  const currentOp = useConfigStore((s) => s.currentOperationId);
  const setOp = useConfigStore((s) => s.setOperation);
  const openTerminal = useConfigStore((s) => s.openTerminal);

  const [planOpId, setPlanOpId] = useState<string | null>(null);
  const [orphanDialogOpen, setOrphanDialogOpen] = useState(false);

  useEffect(() => {
    if (remoteHcl !== undefined && !dirty) {
      setDraft(remoteHcl);
    }
  }, [remoteHcl, dirty]);

  const onChange = (v: string) => {
    setDraft(v);
    setDirty(v !== (remoteHcl ?? ""));
  };

  const handlePlan = async () => {
    try {
      const res = await planMut.mutateAsync(draft);
      setPlanOpId(res.operation_id);
      setOp(res.operation_id, "planning");
      openTerminal();
    } catch {
      /* error shown via planMut.error */
    }
  };

  const handleApply = async () => {
    if (!planOpId) return;
    try {
      const res = await applyMut.mutateAsync(planOpId);
      setOp(res.operation_id, "applying");
      openTerminal();
    } catch {
      /* error */
    }
  };

  const planReady = Boolean(
    planOpId && currentOp === planOpId && planStatus === "planned",
  );
  const applyingOrDone = Boolean(
    planOpId && (planStatus === "applying" || planStatus === "applied"),
  );

  const handleResetDraft = () => {
    setDraft(remoteHcl ?? "");
    setDirty(false);
    setPlanOpId(null);
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-clr-text-secondary p-4">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading HCL…
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-start gap-2 rounded-sm border border-clr-danger/30 bg-red-50 p-3 m-4">
        <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
        <p className="text-xs text-clr-danger">{getErrorMessage(error)}</p>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-3">
      {deployment?.needs_review && (
        <div className="flex items-start gap-2 rounded-sm border border-orange-200 bg-orange-50 p-2">
          <AlertTriangle className="h-4 w-4 text-orange-700 flex-none mt-0.5" />
          <div className="flex-1 text-xs text-orange-900">
            Drift detected in cloud state. HCL below is the last saved snapshot,
            not live VCD.
          </div>
          <button
            onClick={onGoToDrift}
            className="text-xs text-clr-action hover:underline whitespace-nowrap"
          >
            View drift →
          </button>
        </div>
      )}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <p className="text-xs text-clr-text-secondary">
            Editing <span className="font-mono">main.tf</span> from last saved
            snapshot. Save & Plan creates a new version on successful apply.
          </p>
          {dirty && (
            <span className="text-[10px] font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5">
              UNSAVED
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => refetch()}
            title="Reload last saved snapshot from MinIO"
            className="text-xs text-clr-action hover:underline"
          >
            Reload snapshot
          </button>
          <button
            onClick={onGoToDrift}
            title="Check cloud drift vs snapshot"
            className="inline-flex items-center gap-1 text-xs text-clr-text-secondary hover:text-clr-action"
          >
            <Cloud className="h-3 w-3" />
            Check VCD drift
          </button>
        </div>
      </div>

      {orphanScan.data && orphanScan.data.removed.length > 0 && (
        <div className="flex items-start gap-2 rounded-sm border border-amber-300 bg-amber-50 p-2">
          <AlertTriangle className="h-4 w-4 text-amber-700 flex-none mt-0.5" />
          <div className="flex-1 text-xs text-amber-900 space-y-1">
            <div className="font-medium">
              {orphanScan.data.removed.length} orphan state{" "}
              {orphanScan.data.removed.length === 1 ? "entry" : "entries"} detected
            </div>
            <div className="text-[11px] opacity-80">
              These addresses exist in Terraform state but not in the
              current HCL — typically leftover migration-era slugs that
              now duplicate-track resources already managed under new
              names. Cleaning them prevents spurious destroy+create on
              the next Plan. <code>terraform state rm</code> does not
              touch VCD.
            </div>
            <div className="font-mono text-[10px] break-all">
              {orphanScan.data.removed.slice(0, 6).join(", ")}
              {orphanScan.data.removed.length > 6 &&
                ` +${orphanScan.data.removed.length - 6} more`}
            </div>
          </div>
          <button
            onClick={() => setOrphanDialogOpen(true)}
            className="flex-none text-xs font-medium text-amber-800 hover:text-amber-900 underline"
          >
            Clean
          </button>
        </div>
      )}

      {orphanDialogOpen && orphanScan.data && (
        <div
          className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
          onClick={() => !cleanupMut.isPending && setOrphanDialogOpen(false)}
        >
          <div
            className="bg-white rounded-sm border border-clr-border p-4 max-w-lg w-full space-y-3"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-sm font-semibold text-clr-text">
              Remove {orphanScan.data.removed.length} orphan state entries?
            </h3>
            <p className="text-xs text-clr-text-secondary">
              <code>terraform state rm</code> will run for each address
              below. Real VCD resources are not affected — only the
              state mapping is removed.
            </p>
            <div className="max-h-48 overflow-auto rounded-sm bg-slate-50 border border-clr-border p-2 font-mono text-[11px] space-y-0.5">
              {orphanScan.data.removed.map((a) => (
                <div key={a}>{a}</div>
              ))}
            </div>
            {cleanupMut.isError && (
              <p className="text-xs text-clr-danger">
                {getErrorMessage(cleanupMut.error)}
              </p>
            )}
            {cleanupMut.data && cleanupMut.data.errors.length > 0 && (
              <div className="rounded-sm border border-clr-danger/30 bg-red-50 p-2 text-[11px] text-clr-danger space-y-0.5">
                {cleanupMut.data.errors.map((e, i) => (
                  <div key={i}>{e}</div>
                ))}
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setOrphanDialogOpen(false)}
                disabled={cleanupMut.isPending}
                className="rounded-sm px-3 py-1.5 text-xs text-clr-text-secondary hover:text-clr-text disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={async () => {
                  try {
                    const res = await cleanupMut.mutateAsync();
                    if (res.errors.length === 0) {
                      setOrphanDialogOpen(false);
                    }
                  } catch {
                    /* error shown via cleanupMut.error */
                  }
                }}
                disabled={cleanupMut.isPending}
                className="flex items-center gap-1.5 rounded-sm bg-amber-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-amber-700 disabled:opacity-50"
              >
                {cleanupMut.isPending && (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                )}
                Remove orphans
              </button>
            </div>
          </div>
        </div>
      )}

      <HclEditorWithGutter
        value={draft}
        onChange={onChange}
      />

      {planMut.isError && (
        <div className="flex items-start gap-2 rounded-sm border border-clr-danger/30 bg-red-50 p-2">
          <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
          <p className="text-xs text-clr-danger break-words">
            {getErrorMessage(planMut.error)}
          </p>
        </div>
      )}
      {applyMut.isError && (
        <div className="flex items-start gap-2 rounded-sm border border-clr-danger/30 bg-red-50 p-2">
          <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
          <p className="text-xs text-clr-danger break-words">
            {getErrorMessage(applyMut.error)}
          </p>
        </div>
      )}

      <div className="flex items-center justify-end gap-2">
        {dirty && (
          <button
            onClick={handleResetDraft}
            className="rounded-sm px-3 py-1.5 text-xs text-clr-text-secondary hover:text-clr-text"
          >
            Discard changes
          </button>
        )}
        <button
          onClick={handlePlan}
          disabled={planMut.isPending || applyingOrDone}
          title={
            dirty
              ? "Save HCL changes and run terraform plan"
              : "Run terraform plan against the current saved HCL"
          }
          className="flex items-center gap-1.5 rounded-sm bg-clr-action text-white text-xs font-medium px-3 py-1.5 hover:bg-clr-action-hover disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {planMut.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Pencil className="h-3.5 w-3.5" />
          )}
          Save & Plan
        </button>
        <button
          onClick={handleApply}
          disabled={!planReady || applyMut.isPending || applyingOrDone}
          className="flex items-center gap-1.5 rounded-sm bg-emerald-600 text-white text-xs font-medium px-3 py-1.5 hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {applyMut.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          Apply
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Overview tab                                                       */
/* ------------------------------------------------------------------ */

function OverviewTab({ deploymentId }: { deploymentId: string }) {
  const { data: d, isLoading, isError, error } = useDeployment(deploymentId);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-clr-text-secondary p-4">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading deployment…
      </div>
    );
  }

  if (isError || !d) {
    return (
      <div className="flex items-start gap-2 rounded-sm border border-clr-danger/30 bg-red-50 p-3 m-4">
        <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
        <p className="text-xs text-clr-danger">{getErrorMessage(error)}</p>
      </div>
    );
  }

  const isMigration = d.kind === "migrated";
  const rows: [string, string][] = [
    ["Kind", d.kind],
    ...(isMigration
      ? ([
          ["Source edge", d.source_edge_name],
          ["Source host", d.source_host],
        ] as [string, string][])
      : []),
    ["Target org", d.target_org],
    ["Target VDC", d.target_vdc],
    ["Target edge", d.target_edge_name ?? "—"],
    ["Target edge ID", d.target_edge_id],
    ["Created", `${fmtDate(d.created_at)} by ${d.created_by}`],
    ["Updated", fmtDate(d.updated_at)],
  ];

  return (
    <div className="p-4 space-y-3">
      {d.description && (
        <div className="rounded-sm border border-clr-border bg-clr-near-white p-3 text-xs text-clr-text">
          {d.description}
        </div>
      )}
      <dl className="border border-clr-border rounded-sm divide-y divide-clr-border text-xs">
        {rows.map(([k, v]) => (
          <div key={k} className="flex">
            <dt className="w-40 bg-clr-near-white px-3 py-2 font-medium text-clr-text-secondary">
              {k}
            </dt>
            <dd className="flex-1 px-3 py-2 font-mono break-all">{v}</dd>
          </div>
        ))}
      </dl>

      <div className="flex items-center gap-2 pt-2">
        <Link
          to={`/deployments/${d.id}/edit`}
          className="flex items-center gap-1.5 rounded-sm bg-clr-action text-white text-xs font-medium px-3 py-1.5 hover:bg-clr-action-hover"
        >
          <Pencil className="h-3.5 w-3.5" />
          Edit deployment
        </Link>
        {d.kind === "migrated" && (
          <Link
            to={`/migration?deployment=${d.id}`}
            className="flex items-center gap-1.5 rounded-sm border border-clr-border bg-white text-clr-text hover:border-clr-action text-xs font-medium px-3 py-1.5"
          >
            <Pencil className="h-3.5 w-3.5" />
            Edit in Migration form
          </Link>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page shell                                                         */
/* ------------------------------------------------------------------ */

export function DeploymentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("overview");
  const { data: d } = useDeployment(id);

  if (!id) {
    return (
      <div className="p-6 text-xs text-clr-danger">Invalid deployment id</div>
    );
  }

  const tabs: { key: Tab; label: string; icon: typeof Info }[] = [
    { key: "overview", label: "Overview", icon: Info },
    { key: "versions", label: "Version history", icon: History },
    { key: "hcl", label: "HCL", icon: FileCode2 },
    { key: "drift", label: "Drift", icon: Cloud },
  ];

  return (
    <div className="p-6 max-w-6xl">
      <button
        onClick={() => navigate("/deployments")}
        className="flex items-center gap-1 text-xs text-clr-text-secondary hover:text-clr-text mb-3"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to Saved Deployments
      </button>

      <div className="mb-4">
        <h1 className="text-lg font-semibold text-clr-text tracking-tight break-words">
          {d?.name ?? "Deployment"}
        </h1>
        {d && (
          <p className="text-xs text-clr-text-secondary mt-1 flex items-center gap-3 flex-wrap">
            <span className="flex items-center gap-1">
              <User className="h-3 w-3" />
              {d.created_by}
            </span>
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {fmtDate(d.created_at)}
            </span>
            <span className="font-mono text-[10px]">{d.id}</span>
          </p>
        )}
      </div>

      <div className="border-b border-clr-border mb-2">
        <div className="flex gap-1">
          {tabs.map((t) => {
            const Icon = t.icon;
            const active = tab === t.key;
            const showBadge = t.key === "drift" && d?.needs_review;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 -mb-px transition-colors",
                  active
                    ? "border-clr-action text-clr-action"
                    : "border-transparent text-clr-text-secondary hover:text-clr-text",
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {t.label}
                {showBadge && (
                  <span className="ml-1 inline-flex items-center gap-0.5 rounded px-1 py-0.5 bg-orange-100 text-orange-700 text-[10px] font-medium">
                    <AlertTriangle className="h-2.5 w-2.5" />
                    needs review
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      <div className="bg-white border border-clr-border rounded-sm">
        {tab === "overview" && <OverviewTab deploymentId={id} />}
        {tab === "versions" && <VersionsTab deploymentId={id} />}
        {tab === "hcl" && <HclTab deploymentId={id} onGoToDrift={() => setTab("drift")} />}
        {tab === "drift" && <DriftTab deploymentId={id} />}
      </div>
    </div>
  );
}
