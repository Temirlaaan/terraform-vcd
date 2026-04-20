import { useEffect } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import {
  ArrowLeftRight,
  AlertCircle,
  FileCode2,
  RotateCcw,
} from "lucide-react";
import { useMigrationGenerate, type MigrationRequest } from "@/api/migrationApi";
import { useDeployment } from "@/api/deploymentsApi";
import { MigrationForm } from "@/components/migration/MigrationForm";
import { MigrationSummary } from "@/components/migration/MigrationSummary";
import { MigrationHclPreview } from "@/components/migration/MigrationHclPreview";
import { MigrationActionBar } from "@/components/migration/MigrationActionBar";
import { MigrationSaveButton } from "@/components/migration/MigrationSaveButton";
import { DuplicateDeploymentBanner } from "@/components/migration/DuplicateDeploymentBanner";
import { useMigrationStore } from "@/store/useMigrationStore";
import { isAxiosError } from "axios";

function getErrorMessage(error: unknown): string {
  if (isAxiosError(error)) {
    const status = error.response?.status;
    const detail = error.response?.data?.detail;
    if (status === 401) return "Authentication failed. Check VCD credentials.";
    if (status === 502) return "Cannot connect to legacy VCD. Check host URL.";
    if (status === 400) return detail || "Failed to parse edge gateway XML.";
    if (detail) return String(detail);
  }
  return "An unexpected error occurred. Please try again.";
}

export function MigrationPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const deploymentId = searchParams.get("deployment") ?? undefined;

  const mutation = useMigrationGenerate();
  const form = useMigrationStore((s) => s.form);
  const result = useMigrationStore((s) => s.result);
  const setResult = useMigrationStore((s) => s.setResult);
  const hydrateFromDeployment = useMigrationStore(
    (s) => s.hydrateFromDeployment,
  );
  const resetForm = useMigrationStore((s) => s.resetForm);

  const deploymentQuery = useDeployment(deploymentId);

  useEffect(() => {
    if (deploymentQuery.data) {
      hydrateFromDeployment(deploymentQuery.data);
      navigate("/migration", { replace: true });
    }
  }, [deploymentQuery.data, hydrateFromDeployment, navigate]);

  const handleSubmit = (data: MigrationRequest) => {
    mutation.mutate(data, {
      onSuccess: (resp) => {
        setResult({
          hcl: resp.hcl,
          edgeName: resp.edge_name,
          summary: resp.summary,
        });
      },
    });
  };

  const handleReset = () => {
    resetForm();
    mutation.reset();
    navigate("/migration", { replace: true });
  };

  return (
    <div className="flex flex-1 min-h-0">
      {/* Left panel — form */}
      <aside className="w-96 flex-none bg-clr-near-white border-r border-clr-border overflow-y-auto flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-clr-border">
          <div className="flex items-center gap-2">
            <ArrowLeftRight className="h-4 w-4 text-clr-action" />
            <h2 className="text-clr-text font-semibold tracking-tight text-sm">
              Edge Migration
            </h2>
            <span className="text-[10px] font-medium text-amber-600 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5">
              NSX-V → NSX-T
            </span>
          </div>
          <button
            onClick={handleReset}
            className="text-clr-placeholder hover:text-clr-text transition-colors"
            title="Reset form"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* Layer 1 duplicate check */}
        <DuplicateDeploymentBanner targetEdgeId={form.edgeGatewayId} />

        {/* Form */}
        <div className="flex-1 overflow-y-auto">
          <MigrationForm
            onSubmit={handleSubmit}
            isLoading={mutation.isPending}
          />
        </div>

        {/* Error alert */}
        {mutation.isError && (
          <div className="mx-4 mb-4 flex items-start gap-2 rounded-sm border border-red-200 bg-red-50 p-3">
            <AlertCircle className="h-4 w-4 text-red-500 flex-none mt-0.5" />
            <p className="text-xs text-red-700 leading-relaxed">
              {getErrorMessage(mutation.error)}
            </p>
          </div>
        )}
      </aside>

      {/* Right panel — results */}
      <div className="flex-1 min-w-0 overflow-hidden flex flex-col">
        {result ? (
          <>
            {/* Summary */}
            <div className="flex-none border-b border-clr-border">
              <MigrationSummary
                summary={result.summary}
                edgeName={result.edgeName}
              />
            </div>
            {/* Action bar: Plan / Apply */}
            <MigrationActionBar
              hcl={result.hcl}
              targetOrg={form.orgName}
              targetEdgeId={form.edgeGatewayId}
            />
            {/* Save to deployments */}
            <MigrationSaveButton />
            {/* HCL preview */}
            <div className="flex-1 min-h-0">
              <MigrationHclPreview
                hcl={result.hcl}
                edgeName={result.edgeName}
              />
            </div>
          </>
        ) : (
          /* Empty state */
          <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
            <FileCode2 className="h-12 w-12 text-clr-border mb-4" />
            <h3 className="text-sm font-semibold text-clr-text mb-1">
              No HCL generated yet
            </h3>
            <p className="text-xs text-clr-text-secondary max-w-xs">
              Fill in the legacy VCD connection details and target references,
              then click <strong>Generate HCL</strong> to migrate edge gateway
              configuration.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
