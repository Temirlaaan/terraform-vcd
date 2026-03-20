import { Settings } from "lucide-react";

export function SettingsPage() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center p-6">
      <div className="h-12 w-12 rounded-sm bg-clr-action/10 flex items-center justify-center mb-4">
        <Settings className="h-6 w-6 text-clr-action" />
      </div>
      <h1 className="text-lg font-semibold text-clr-text tracking-tight">
        Settings
      </h1>
      <p className="text-xs text-clr-text-secondary mt-2 max-w-xs">
        Configure provider credentials, S3 backend, and environment preferences.
        This feature is coming soon.
      </p>
    </div>
  );
}
