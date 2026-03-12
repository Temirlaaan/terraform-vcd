import { ReactKeycloakProvider } from "@react-keycloak/web";
import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import keycloak from "./keycloak";

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
  return (
    <ReactKeycloakProvider
      authClient={keycloak}
      initOptions={{
        onLoad: "login-required",
        checkLoginIframe: false,
        pkceMethod: "S256",
      }}
      LoadingComponent={<AuthLoading />}
    >
      {children}
    </ReactKeycloakProvider>
  );
}
