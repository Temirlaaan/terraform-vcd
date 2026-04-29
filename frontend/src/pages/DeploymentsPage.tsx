import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  FolderOpen,
  RefreshCw,
  ArrowLeftRight,
  ArrowRight,
  MoreVertical,
  Plus,
  Trash2,
  Pencil,
  User,
  Loader2,
  X,
  AlertCircle,
  Download,
  Filter,
} from "lucide-react";
import { isAxiosError } from "axios";
import {
  useDeployments,
  useDeleteDeployment,
  useUpdateDeployment,
  useAvailableEdges,
  useImportEdge,
  type DeploymentListItem,
  type AvailableEdge,
} from "@/api/deploymentsApi";
import {
  useOrgs,
  useVdcsByOrg,
} from "@/api/metadataApi";
import { cn } from "@/utils/cn";
import { useAuth } from "@/auth/useAuth";

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diff = Math.max(0, now - then);
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return "just now";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const days = Math.floor(hr / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  const years = Math.floor(days / 365);
  return `${years}y ago`;
}

function getErrorMessage(error: unknown): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  }
  return "Request failed.";
}

const KIND_BADGE: Record<string, { label: string; cls: string }> = {
  migrated: {
    label: "MIGRATED",
    cls: "text-amber-600 bg-amber-50 border-amber-200",
  },
  manual_created: {
    label: "MANUAL",
    cls: "text-sky-700 bg-sky-50 border-sky-200",
  },
  imported: {
    label: "IMPORTED",
    cls: "text-violet-700 bg-violet-50 border-violet-200",
  },
};

function kindBadge(kind: string): { label: string; cls: string } {
  return (
    KIND_BADGE[kind] ?? {
      label: kind.toUpperCase(),
      cls: "text-clr-text-secondary bg-clr-near-white border-clr-border",
    }
  );
}

function SummaryBadges({ d }: { d: DeploymentListItem }) {
  const items = [
    { label: "FW", value: d.summary.firewall_rules_total },
    { label: "NAT", value: d.summary.nat_rules_total },
    { label: "Routes", value: d.summary.static_routes_total },
    { label: "Ports", value: d.summary.app_port_profiles_total },
  ];
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((it) => (
        <span
          key={it.label}
          className="text-[10px] font-medium text-clr-text-secondary bg-clr-near-white border border-clr-border rounded px-1.5 py-0.5"
        >
          {it.label}: {it.value}
        </span>
      ))}
    </div>
  );
}

interface KebabMenuProps {
  onRename: () => void;
  onDelete: () => void;
  canDelete: boolean;
  canRename: boolean;
}

function KebabMenu({ onRename, onDelete, canDelete, canRename }: KebabMenuProps) {
  if (!canDelete && !canRename) return null;
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="text-clr-placeholder hover:text-clr-text p-1 rounded-sm hover:bg-clr-near-white"
      >
        <MoreVertical className="h-4 w-4" />
      </button>
      {open && (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setOpen(false);
            }}
          />
          <div className="absolute right-0 top-full mt-1 z-20 min-w-[120px] rounded-sm border border-clr-border bg-white shadow-md py-1">
            {canRename && (
              <button
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setOpen(false);
                  onRename();
                }}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-clr-text hover:bg-clr-near-white"
              >
                <Pencil className="h-3.5 w-3.5" />
                Rename
              </button>
            )}
            {canDelete && (
              <button
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setOpen(false);
                  onDelete();
                }}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-clr-danger hover:bg-red-50"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Delete
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

interface DeploymentCardProps {
  d: DeploymentListItem;
  onRename: (d: DeploymentListItem) => void;
  onDelete: (d: DeploymentListItem) => void;
  canDelete: boolean;
  canRename: boolean;
}

function DeploymentCard({ d, onRename, onDelete, canDelete, canRename }: DeploymentCardProps) {
  const badge = kindBadge(d.kind);
  return (
    <div className="bg-white border border-clr-border rounded-sm p-5 flex flex-col gap-4 transition-all hover:shadow-md hover:border-clr-action/40">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="h-9 w-9 rounded-sm bg-clr-action/10 flex items-center justify-center">
            <ArrowLeftRight className="h-4.5 w-4.5 text-clr-action" />
          </div>
          <span
            className={cn(
              "text-[10px] font-medium border rounded px-1.5 py-0.5",
              badge.cls,
            )}
          >
            {badge.label}
          </span>
        </div>
        <KebabMenu
          onRename={() => onRename(d)}
          onDelete={() => onDelete(d)}
          canRename={canRename}
          canDelete={canDelete}
        />
      </div>

      <div>
        <Link
          to={`/deployments/${d.id}`}
          className="text-sm font-semibold text-clr-text leading-tight hover:text-clr-action break-words"
        >
          {d.name}
        </Link>
        {d.description && (
          <p className="text-xs text-clr-text-secondary mt-1 line-clamp-2">
            {d.description}
          </p>
        )}
      </div>

      <div className="flex items-center gap-1.5 text-xs text-clr-text-secondary">
        <span className="font-medium text-clr-text truncate max-w-[40%]">
          {d.source_edge_name}
        </span>
        <ArrowRight className="h-3 w-3 flex-none" />
        <span className="truncate">
          {d.target_org} / {d.target_vdc}
          {d.target_edge_name ? ` / ${d.target_edge_name}` : ""}
        </span>
      </div>

      <SummaryBadges d={d} />

      <div className="mt-auto pt-1 flex items-center justify-between text-[10px] text-clr-placeholder">
        <span className="flex items-center gap-1">
          <User className="h-3 w-3" />
          {d.created_by}
        </span>
        <span>{relativeTime(d.created_at)}</span>
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="bg-white border border-clr-border rounded-sm p-5 flex flex-col gap-4 animate-pulse"
        >
          <div className="h-9 w-9 rounded-sm bg-clr-near-white" />
          <div className="h-4 w-3/4 rounded bg-clr-near-white" />
          <div className="h-3 w-1/2 rounded bg-clr-near-white" />
          <div className="h-3 w-full rounded bg-clr-near-white" />
        </div>
      ))}
    </div>
  );
}

interface RenameModalProps {
  d: DeploymentListItem;
  onClose: () => void;
}

function RenameModal({ d, onClose }: RenameModalProps) {
  const [name, setName] = useState(d.name);
  const [description, setDescription] = useState(d.description ?? "");
  const mutation = useUpdateDeployment();

  const canSubmit = name.trim().length > 0 && !mutation.isPending;

  const handleConfirm = () => {
    mutation.mutate(
      {
        id: d.id,
        patch: {
          name: name.trim(),
          description: description.trim() || null,
        },
      },
      { onSuccess: onClose },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-sm bg-white border border-clr-border shadow-lg">
        <div className="flex items-center justify-between px-4 py-3 border-b border-clr-border">
          <h3 className="text-sm font-semibold text-clr-text">Rename deployment</h3>
          <button onClick={onClose} className="text-clr-placeholder hover:text-clr-text">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-4 space-y-3">
          <label className="block space-y-1">
            <span className="text-xs font-medium text-clr-text-secondary">Name</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-sm bg-white border border-clr-border px-2.5 py-1.5 text-sm text-clr-text focus:border-clr-action focus:outline-none"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-clr-text-secondary">Description (optional)</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full rounded-sm bg-white border border-clr-border px-2.5 py-1.5 text-sm text-clr-text focus:border-clr-action focus:outline-none resize-none"
            />
          </label>
          {mutation.isError && (
            <div className="flex items-start gap-2 rounded-sm border border-clr-danger/30 bg-red-50 p-2">
              <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
              <p className="text-xs text-clr-danger break-words">{getErrorMessage(mutation.error)}</p>
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-clr-border bg-clr-near-white">
          <button onClick={onClose} className="rounded-sm px-3 py-1.5 text-xs text-clr-text-secondary hover:text-clr-text">Cancel</button>
          <button
            onClick={handleConfirm}
            disabled={!canSubmit}
            className="flex items-center gap-1.5 rounded-sm bg-clr-action text-white text-xs font-medium px-3 py-1.5 hover:bg-clr-action-hover disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {mutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

interface DeleteModalProps {
  d: DeploymentListItem;
  onClose: () => void;
}

function DeleteModal({ d, onClose }: DeleteModalProps) {
  const mutation = useDeleteDeployment();
  const handleConfirm = () => {
    mutation.mutate(d.id, { onSuccess: onClose });
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-sm bg-white border border-clr-border shadow-lg">
        <div className="flex items-center justify-between px-4 py-3 border-b border-clr-border">
          <h3 className="text-sm font-semibold text-clr-text">Delete deployment</h3>
          <button onClick={onClose} className="text-clr-placeholder hover:text-clr-text">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-4 space-y-3">
          <p className="text-xs text-clr-text">
            Are you sure you want to delete <span className="font-semibold">{d.name}</span>? This action cannot be undone.
          </p>
          {mutation.isError && (
            <div className="flex items-start gap-2 rounded-sm border border-clr-danger/30 bg-red-50 p-2">
              <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
              <p className="text-xs text-clr-danger break-words">{getErrorMessage(mutation.error)}</p>
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-clr-border bg-clr-near-white">
          <button onClick={onClose} className="rounded-sm px-3 py-1.5 text-xs text-clr-text-secondary hover:text-clr-text">Cancel</button>
          <button
            onClick={handleConfirm}
            disabled={mutation.isPending}
            className="flex items-center gap-1.5 rounded-sm bg-clr-danger text-white text-xs font-medium px-3 py-1.5 hover:bg-clr-danger/90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {mutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------- */
/*  Import existing edge modal                                          */
/* -------------------------------------------------------------------- */

interface ImportModalProps {
  onClose: () => void;
}

function ImportModal({ onClose }: ImportModalProps) {
  const [orgId, setOrgId] = useState<string>("");
  const [vdcId, setVdcId] = useState<string>("");
  const [edgeId, setEdgeId] = useState<string>("");
  const [name, setName] = useState<string>("");

  const orgsQuery = useOrgs();
  const vdcsQuery = useVdcsByOrg(orgId || undefined);

  const orgName = orgsQuery.data?.find((o) => o.id === orgId)?.name ?? null;
  const vdcName = vdcsQuery.data?.find((v) => v.id === vdcId)?.name ?? null;

  const edgesQuery = useAvailableEdges(vdcId || null, !!vdcId);
  const selectedEdge: AvailableEdge | undefined = edgesQuery.data?.items.find((e) => e.id === edgeId);

  const importMut = useImportEdge();

  const canSubmit =
    !!orgName &&
    !!vdcId &&
    !!selectedEdge &&
    !selectedEdge.deployed &&
    !importMut.isPending;

  const handleSubmit = () => {
    if (!selectedEdge || !orgName || !vdcName) return;
    importMut.mutate(
      {
        name: name.trim() || undefined,
        target_org: orgName,
        target_vdc: vdcName,
        target_vdc_id: vdcId,
        target_edge_id: selectedEdge.id,
        target_edge_name: selectedEdge.name,
      },
      {
        onSuccess: () => {
          onClose();
          // Stay on the list — useImportEdge invalidates the deployments
          // query so the freshly imported card appears without navigation.
        },
      },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-sm bg-white border border-clr-border shadow-lg">
        <div className="flex items-center justify-between px-4 py-3 border-b border-clr-border">
          <h3 className="text-sm font-semibold text-clr-text flex items-center gap-2">
            <Download className="h-4 w-4" />
            Import existing edge
          </h3>
          <button onClick={onClose} className="text-clr-placeholder hover:text-clr-text">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-4 space-y-3">
          <p className="text-xs text-clr-text-secondary">
            Pick an edge that already exists in VCD. The dashboard will pull all
            ip-sets, NAT rules, static routes, and app port profiles into a new
            deployment with kind <code className="bg-clr-near-white px-1 rounded">imported</code>.
          </p>

          <label className="block space-y-1">
            <span className="text-xs font-medium text-clr-text-secondary">Organization</span>
            <select
              value={orgId}
              onChange={(e) => {
                setOrgId(e.target.value);
                setVdcId("");
                setEdgeId("");
              }}
              className="w-full rounded-sm bg-white border border-clr-border px-2.5 py-1.5 text-sm text-clr-text focus:border-clr-action focus:outline-none"
            >
              <option value="">— select —</option>
              {orgsQuery.data?.map((o) => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-xs font-medium text-clr-text-secondary">VDC</span>
            <select
              value={vdcId}
              onChange={(e) => {
                setVdcId(e.target.value);
                setEdgeId("");
              }}
              disabled={!orgId}
              className="w-full rounded-sm bg-white border border-clr-border px-2.5 py-1.5 text-sm text-clr-text focus:border-clr-action focus:outline-none disabled:opacity-50"
            >
              <option value="">— select —</option>
              {vdcsQuery.data?.map((v) => (
                <option key={v.id} value={v.id}>{v.name}</option>
              ))}
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-xs font-medium text-clr-text-secondary">Edge gateway</span>
            <select
              value={edgeId}
              onChange={(e) => setEdgeId(e.target.value)}
              disabled={!vdcId || edgesQuery.isLoading}
              className="w-full rounded-sm bg-white border border-clr-border px-2.5 py-1.5 text-sm text-clr-text focus:border-clr-action focus:outline-none disabled:opacity-50"
            >
              <option value="">— select —</option>
              {edgesQuery.data?.items.map((e) => (
                <option
                  key={e.id}
                  value={e.id}
                  disabled={e.deployed}
                >
                  {e.name}{e.deployed ? `  (already managed: ${e.deployment_kind})` : ""}
                </option>
              ))}
            </select>
            {edgesQuery.isLoading && (
              <span className="text-[10px] text-clr-placeholder">loading edges…</span>
            )}
          </label>

          {selectedEdge?.deployed && (
            <div className="flex items-start gap-2 rounded-sm border border-amber-300/60 bg-amber-50 p-2">
              <AlertCircle className="h-4 w-4 text-amber-700 flex-none mt-0.5" />
              <p className="text-xs text-amber-800">
                This edge is already managed by another deployment. Open it{" "}
                <Link
                  to={`/deployments/${selectedEdge.deployment_id}`}
                  className="underline"
                  onClick={onClose}
                >
                  here
                </Link>{" "}
                instead of importing again.
              </p>
            </div>
          )}

          <label className="block space-y-1">
            <span className="text-xs font-medium text-clr-text-secondary">
              Deployment name (optional)
            </span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={selectedEdge ? `imported_${selectedEdge.name}` : "imported_<edge>"}
              className="w-full rounded-sm bg-white border border-clr-border px-2.5 py-1.5 text-sm text-clr-text focus:border-clr-action focus:outline-none"
            />
          </label>

          {importMut.isError && (
            <div className="flex items-start gap-2 rounded-sm border border-clr-danger/30 bg-red-50 p-2">
              <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
              <p className="text-xs text-clr-danger break-words">{getErrorMessage(importMut.error)}</p>
            </div>
          )}
          {importMut.isPending && (
            <div className="flex items-start gap-2 rounded-sm border border-clr-border bg-clr-near-white p-2">
              <Loader2 className="h-4 w-4 text-clr-action flex-none mt-0.5 animate-spin" />
              <p className="text-xs text-clr-text">
                Importing edge — running terraform import for each resource. This may take 30–90s.
              </p>
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-clr-border bg-clr-near-white">
          <button
            onClick={onClose}
            disabled={importMut.isPending}
            className="rounded-sm px-3 py-1.5 text-xs text-clr-text-secondary hover:text-clr-text disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="flex items-center gap-1.5 rounded-sm bg-clr-action text-white text-xs font-medium px-3 py-1.5 hover:bg-clr-action-hover disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {importMut.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            Import
          </button>
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------- */
/*  Page                                                                */
/* -------------------------------------------------------------------- */

type SortKey = "created_desc" | "created_asc" | "name_asc" | "name_desc" | "updated_desc";

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: "created_desc", label: "Newest first" },
  { value: "created_asc", label: "Oldest first" },
  { value: "updated_desc", label: "Recently updated" },
  { value: "name_asc", label: "Name A→Z" },
  { value: "name_desc", label: "Name Z→A" },
];

const KIND_OPTIONS: { value: string; label: string }[] = [
  { value: "all", label: "All kinds" },
  { value: "migrated", label: "Migrated" },
  { value: "manual_created", label: "Manual" },
  { value: "imported", label: "Imported" },
];

export function DeploymentsPage() {
  const query = useDeployments();
  const { roles } = useAuth();
  const isWriter = roles.includes("tf-admin") || roles.includes("tf-operator");
  const isAdmin = roles.includes("tf-admin");
  const [renameTarget, setRenameTarget] = useState<DeploymentListItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeploymentListItem | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [kindFilter, setKindFilter] = useState<string>("all");
  const [sortKey, setSortKey] = useState<SortKey>("created_desc");
  const [searchQuery, setSearchQuery] = useState<string>("");

  const items = query.data?.items ?? [];

  const view = useMemo(() => {
    let arr = items;
    if (kindFilter !== "all") {
      arr = arr.filter((d) => d.kind === kindFilter);
    }
    const q = searchQuery.trim().toLowerCase();
    if (q) {
      arr = arr.filter((d) => {
        const hay = [
          d.name,
          d.description ?? "",
          d.source_edge_name,
          d.target_org,
          d.target_vdc,
          d.target_edge_name ?? "",
          d.created_by,
        ].join(" ").toLowerCase();
        return hay.includes(q);
      });
    }
    arr = [...arr].sort((a, b) => {
      switch (sortKey) {
        case "created_asc":
          return a.created_at.localeCompare(b.created_at);
        case "updated_desc":
          return b.updated_at.localeCompare(a.updated_at);
        case "name_asc":
          return a.name.localeCompare(b.name);
        case "name_desc":
          return b.name.localeCompare(a.name);
        default:
          return b.created_at.localeCompare(a.created_at);
      }
    });
    return arr;
  }, [items, kindFilter, sortKey, searchQuery]);

  const kindCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const d of items) c[d.kind] = (c[d.kind] ?? 0) + 1;
    return c;
  }, [items]);

  return (
    <div className="p-6 max-w-6xl">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-clr-text tracking-tight">Saved Deployments</h1>
          <p className="text-xs text-clr-text-secondary mt-1">
            Review previously generated HCL and reopen a deployment to edit, plan, or apply it.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => query.refetch()}
            disabled={query.isFetching}
            className="flex items-center gap-1.5 rounded-sm border border-clr-border bg-white text-clr-text-secondary hover:text-clr-text hover:border-clr-action text-xs font-medium py-1.5 px-3 disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} />
            Refresh
          </button>
          {isWriter && (
            <Link
              to="/deployments/new"
              className="flex items-center gap-1.5 rounded-sm bg-clr-action text-white text-xs font-medium py-1.5 px-3 hover:bg-clr-action-hover"
            >
              <Plus className="h-3.5 w-3.5" />
              New Deployment
            </Link>
          )}
          {isAdmin && (
            <button
              onClick={() => setImportOpen(true)}
              className="flex items-center gap-1.5 rounded-sm border border-clr-action/40 bg-white text-clr-action text-xs font-medium py-1.5 px-3 hover:bg-clr-action/10"
            >
              <Download className="h-3.5 w-3.5" />
              Import existing
            </button>
          )}
        </div>
      </div>

      {/* Filter / sort toolbar */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1 text-xs text-clr-text-secondary">
          <Filter className="h-3.5 w-3.5" />
          <span>Kind</span>
        </div>
        <select
          value={kindFilter}
          onChange={(e) => setKindFilter(e.target.value)}
          className="rounded-sm border border-clr-border bg-white px-2 py-1 text-xs text-clr-text focus:border-clr-action focus:outline-none"
        >
          {KIND_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
              {o.value !== "all" && kindCounts[o.value] !== undefined
                ? ` (${kindCounts[o.value]})`
                : ""}
            </option>
          ))}
        </select>

        <div className="ml-3 flex items-center gap-1 text-xs text-clr-text-secondary">
          <span>Sort</span>
        </div>
        <select
          value={sortKey}
          onChange={(e) => setSortKey(e.target.value as SortKey)}
          className="rounded-sm border border-clr-border bg-white px-2 py-1 text-xs text-clr-text focus:border-clr-action focus:outline-none"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        <div className="ml-auto flex items-center gap-2">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search name, edge, org…"
            className="rounded-sm border border-clr-border bg-white px-2 py-1 text-xs text-clr-text placeholder:text-clr-placeholder focus:border-clr-action focus:outline-none w-56"
          />
          <span className="text-[11px] text-clr-placeholder whitespace-nowrap">
            {view.length} of {items.length} deployment{items.length === 1 ? "" : "s"}
          </span>
        </div>
      </div>

      {query.isLoading ? (
        <LoadingSkeleton />
      ) : query.isError ? (
        <div className="flex items-start gap-2 rounded-sm border border-clr-danger/30 bg-red-50 p-3">
          <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
          <p className="text-xs text-clr-danger">{getErrorMessage(query.error)}</p>
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center text-center py-16">
          <div className="h-12 w-12 rounded-sm bg-clr-action/10 flex items-center justify-center mb-4">
            <FolderOpen className="h-6 w-6 text-clr-action" />
          </div>
          <h3 className="text-sm font-semibold text-clr-text">No saved deployments yet</h3>
          <p className="text-xs text-clr-text-secondary mt-2 max-w-sm">
            Generate HCL from the{" "}
            <Link to="/migration" className="text-clr-action hover:underline">Edge Migration</Link>{" "}
            page, then click <strong>Keep in deployments</strong> to save it here for later review.
          </p>
        </div>
      ) : view.length === 0 ? (
        <div className="rounded-sm border border-clr-border bg-clr-near-white p-6 text-center">
          <p className="text-xs text-clr-text-secondary">No deployments match the current filter.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {view.map((d) => (
            <DeploymentCard
              key={d.id}
              d={d}
              onRename={setRenameTarget}
              onDelete={setDeleteTarget}
              canRename={isWriter}
              canDelete={isAdmin}
            />
          ))}
        </div>
      )}

      {renameTarget && <RenameModal d={renameTarget} onClose={() => setRenameTarget(null)} />}
      {deleteTarget && <DeleteModal d={deleteTarget} onClose={() => setDeleteTarget(null)} />}
      {importOpen && <ImportModal onClose={() => setImportOpen(false)} />}
    </div>
  );
}
