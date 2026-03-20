import { FolderOpen } from "lucide-react";

export function DeploymentsPage() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center p-6">
      <div className="h-12 w-12 rounded-sm bg-clr-action/10 flex items-center justify-center mb-4">
        <FolderOpen className="h-6 w-6 text-clr-action" />
      </div>
      <h1 className="text-lg font-semibold text-clr-text tracking-tight">
        My Deployments
      </h1>
      <p className="text-xs text-clr-text-secondary mt-2 max-w-xs">
        View and manage your provisioned infrastructure. This feature is coming
        soon.
      </p>
    </div>
  );
}
