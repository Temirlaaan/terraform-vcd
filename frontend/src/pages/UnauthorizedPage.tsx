import { ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/useAuth";

export function UnauthorizedPage() {
  const { roles } = useAuth();
  return (
    <div className="flex flex-col items-center justify-center flex-1 p-8 text-center">
      <ShieldAlert className="h-16 w-16 text-amber-500 mb-4" />
      <h1 className="text-2xl font-semibold text-clr-text mb-2">403 — Forbidden</h1>
      <p className="text-clr-text-secondary mb-1">
        Your account does not have the role required to access this page.
      </p>
      <p className="text-xs text-clr-text-secondary mb-6">
        Current roles: {roles.length ? roles.join(", ") : "(none)"}
      </p>
      <Link
        to="/deployments"
        className="text-clr-action hover:underline text-sm"
      >
        ← Back to deployments
      </Link>
    </div>
  );
}
