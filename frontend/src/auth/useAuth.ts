import { useEffect, useState } from "react";

import keycloak from "./keycloak";

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

interface AuthState {
  initialized: boolean;
  authenticated: boolean;
  token: string;
  username: string;
  fullName: string;
  email: string;
  roles: string[];
  logout: () => void;
}

function readAuthState(): AuthState {
  if (AUTH_DISABLED) {
    return {
      initialized: true,
      authenticated: true,
      token: "auth-disabled",
      username: "anonymous",
      fullName: "Anonymous (auth disabled)",
      email: "anonymous@local",
      roles: ["tf-admin", "tf-operator", "tf-viewer"],
      logout: () => window.location.reload(),
    };
  }

  const tokenParsed = keycloak.tokenParsed as Record<string, unknown> | undefined;
  const username =
    (tokenParsed?.preferred_username as string | undefined) ??
    (tokenParsed?.name as string | undefined) ??
    "";
  const fullName = (tokenParsed?.name as string | undefined) ?? username;
  const email = (tokenParsed?.email as string | undefined) ?? "";
  const roles =
    ((tokenParsed?.realm_access as { roles?: string[] } | undefined)?.roles) ?? [];

  return {
    initialized: !!keycloak.authenticated,
    authenticated: !!keycloak.authenticated,
    token: keycloak.token ?? "",
    username,
    fullName,
    email,
    roles,
    logout: () => {
      keycloak.logout();
    },
  };
}

/**
 * Convenience hook reading directly from the keycloak-js singleton.
 *
 * Components re-render on auth events (login, refresh, logout, expiry).
 * When AUTH_DISABLED is set, returns a mock admin identity.
 */
export function useAuth(): AuthState {
  const [state, setState] = useState<AuthState>(readAuthState);

  useEffect(() => {
    if (AUTH_DISABLED) return;

    const rerender = () => setState(readAuthState());

    keycloak.onAuthSuccess = rerender;
    keycloak.onAuthRefreshSuccess = rerender;
    keycloak.onAuthLogout = rerender;
    keycloak.onTokenExpired = rerender;

    rerender();

    return () => {
      keycloak.onAuthSuccess = undefined;
      keycloak.onAuthRefreshSuccess = undefined;
      keycloak.onAuthLogout = undefined;
      keycloak.onTokenExpired = undefined;
    };
  }, []);

  return state;
}
