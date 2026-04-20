import { useState } from "react";
import { Save, Loader2, CheckCircle2, X, AlertCircle } from "lucide-react";
import { useCreateDeployment } from "@/api/deploymentsApi";
import { useMigrationStore } from "@/store/useMigrationStore";
import { isAxiosError } from "axios";

function defaultName(edgeName: string): string {
  const d = new Date();
  const stamp =
    d.getFullYear().toString() +
    String(d.getMonth() + 1).padStart(2, "0") +
    String(d.getDate()).padStart(2, "0");
  const safe = (edgeName || "migration").replace(/[^a-zA-Z0-9 \-_()]/g, "_");
  return `${safe}_${stamp}`;
}

function getErrorMessage(error: unknown): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  }
  return "Failed to save deployment.";
}

export function MigrationSaveButton() {
  const form = useMigrationStore((s) => s.form);
  const result = useMigrationStore((s) => s.result);

  const createMutation = useCreateDeployment();

  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saved, setSaved] = useState(false);

  if (!result) return null;

  const openDialog = () => {
    setName(defaultName(result.edgeName));
    setDescription("");
    setOpen(true);
    setSaved(false);
    createMutation.reset();
  };

  const handleConfirm = () => {
    createMutation.mutate(
      {
        name: name.trim(),
        description: description.trim() || null,
        source_host: form.host,
        source_edge_uuid: form.edgeUuid,
        source_edge_name: result.edgeName,
        verify_ssl: form.verifySsl,
        target_org: form.orgName,
        target_vdc: form.vdcName,
        target_vdc_id: form.vdcId,
        target_edge_id: form.edgeGatewayId,
        hcl: result.hcl,
        summary: result.summary,
      },
      {
        onSuccess: () => {
          setSaved(true);
          setTimeout(() => setOpen(false), 1200);
        },
      },
    );
  };

  const canConfirm = name.trim().length > 0 && !createMutation.isPending;

  return (
    <>
      <div className="flex-none border-b border-clr-border px-4 py-2">
        <button
          onClick={openDialog}
          className="w-full flex items-center justify-center gap-2 rounded-sm border border-clr-border bg-white text-clr-text text-sm font-medium py-1.5 px-4 hover:border-clr-action hover:text-clr-action transition-colors"
        >
          <Save className="h-4 w-4" />
          Keep in deployments
        </button>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-sm bg-white border border-clr-border shadow-lg">
            <div className="flex items-center justify-between px-4 py-3 border-b border-clr-border">
              <h3 className="text-sm font-semibold text-clr-text">
                Save deployment
              </h3>
              <button
                onClick={() => setOpen(false)}
                className="text-clr-placeholder hover:text-clr-text"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="p-4 space-y-3">
              <label className="block space-y-1">
                <span className="text-xs font-medium text-clr-text-secondary">
                  Name
                </span>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full rounded-sm bg-white border border-clr-border px-2.5 py-1.5 text-sm text-clr-text focus:border-clr-action focus:outline-none"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs font-medium text-clr-text-secondary">
                  Description (optional)
                </span>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                  className="w-full rounded-sm bg-white border border-clr-border px-2.5 py-1.5 text-sm text-clr-text focus:border-clr-action focus:outline-none resize-none"
                />
              </label>

              {createMutation.isError && (
                <div className="flex items-start gap-2 rounded-sm border border-clr-danger/30 bg-red-50 p-2">
                  <AlertCircle className="h-4 w-4 text-clr-danger flex-none mt-0.5" />
                  <p className="text-xs text-clr-danger break-words">
                    {getErrorMessage(createMutation.error)}
                  </p>
                </div>
              )}

              {saved && (
                <div className="flex items-start gap-2 rounded-sm border border-clr-success/30 bg-green-50 p-2">
                  <CheckCircle2 className="h-4 w-4 text-clr-success flex-none mt-0.5" />
                  <p className="text-xs text-clr-success">Deployment saved.</p>
                </div>
              )}
            </div>
            <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-clr-border bg-clr-near-white">
              <button
                onClick={() => setOpen(false)}
                className="rounded-sm px-3 py-1.5 text-xs text-clr-text-secondary hover:text-clr-text"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirm}
                disabled={!canConfirm}
                className="flex items-center gap-1.5 rounded-sm bg-clr-action text-white text-xs font-medium px-3 py-1.5 hover:bg-clr-action-hover disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {createMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="h-3.5 w-3.5" />
                )}
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
