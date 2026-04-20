import { ReactKeycloakProvider } from "@react-keycloak/web";
import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import keycloak from "./keycloak";

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

/* ------------------------------------------------------------------ */
/*  Loading / error screens                                            */
/* ------------------------------------------------------------------ */

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

/* ------------------------------------------------------------------ */
/*  Provider                                                           */
/* ------------------------------------------------------------------ */

interface Props {
  children: ReactNode;
}

export function KeycloakProvider({ children }: Props) {
  // Skip Keycloak entirely when auth is disabled (testing mode)
  if (AUTH_DISABLED) {
    return <>{children}</>;
  }

  return (
    <ReactKeycloakProvider
      authClient={keycloak}
      initOptions={{
        onLoad: "login-required",
        checkLoginIframe: false,
        pkceMethod: "S256",
        redirectUri: window.location.origin + "/",
      }}
      LoadingComponent={<AuthLoading />}
    >
      {children}
    </ReactKeycloakProvider>
  );
}
