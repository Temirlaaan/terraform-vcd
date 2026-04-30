import { Info } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "@/auth/useAuth";

export function UnauthorizedPage() {
  const { roles } = useAuth();
  return (
    <div className="flex flex-col items-center justify-center flex-1 p-8 text-center">
      <Info className="h-14 w-14 text-clr-text-secondary mb-4" />
      <h1 className="text-base font-semibold text-clr-text mb-1">
        This page isn’t available for your account
      </h1>
      <p className="text-xs text-clr-text-secondary mb-1 max-w-md">
        You can browse deployments and drift reports. Editing, migration
        and provisioning actions are limited to operator and admin roles.
      </p>
      <p className="text-[10px] text-clr-text-secondary mb-6">
        Current roles: {roles.length ? roles.join(", ") : "(none)"}
      </p>
      <Link
        to="/deployments"
        className="text-clr-action hover:underline text-xs"
      >
        ← Back to deployments
      </Link>
    </div>
  );
}
