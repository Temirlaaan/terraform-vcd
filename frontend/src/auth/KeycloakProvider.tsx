import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import keycloak, { initKeycloak } from "./keycloak";

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

if (AUTH_DISABLED && import.meta.env.PROD) {
  throw new Error(
    "VITE_AUTH_DISABLED=true refused in production build. " +
      "Rebuild without this flag or run a dev server.",
  );
}

function AuthLoading() {
  return (
    <div className="flex items-center justify-center h-screen bg-slate-950 text-slate-400">
      <div className="flex flex-col items-center gap-3">
        <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
        <p className="text-sm">Authenticating...</p>
      </div>
    </div>
  );
}

interface Props {
  children: ReactNode;
}

export function KeycloakProvider({ children }: Props) {
  const [initialized, setInitialized] = useState(AUTH_DISABLED);

  useEffect(() => {
    if (AUTH_DISABLED) return;

    initKeycloak()
      .then(() => setInitialized(true))
      .catch((err) => {
        console.error("[keycloak] init failed:", err);
        setInitialized(true);
      });

    const interval = setInterval(() => {
      keycloak.updateToken(60).catch(() => {
        console.warn("[keycloak] token refresh failed, forcing login");
        keycloak.login();
      });
    }, 30_000);

    return () => clearInterval(interval);
  }, []);

  if (!initialized) return <AuthLoading />;
  return <>{children}</>;
}
