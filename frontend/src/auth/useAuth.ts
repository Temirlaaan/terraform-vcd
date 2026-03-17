import { useKeycloak } from "@react-keycloak/web";

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

/**
 * Convenience hook wrapping @react-keycloak/web.
 *
 * Returns the user's display name, roles, raw token, and logout helper.
 * When AUTH_DISABLED is set, returns a mock admin identity.
 */
export function useAuth() {
  if (AUTH_DISABLED) {
    return {
      initialized: true,
      authenticated: true,
      token: "auth-disabled",
      username: "anonymous",
      fullName: "Anonymous (auth disabled)",
      email: "anonymous@local",
      roles: ["tf-admin", "tf-operator", "tf-viewer"],
      logout: () => {
        window.location.reload();
      },
      keycloak: {} as ReturnType<typeof useKeycloak>["keycloak"],
    };
  }

  // eslint-disable-next-line react-hooks/rules-of-hooks
  const { keycloak, initialized } = useKeycloak();

  const tokenParsed = keycloak.tokenParsed as Record<string, unknown> | undefined;

  const username: string =
    (tokenParsed?.preferred_username as string) ??
    (tokenParsed?.name as string) ??
    "";

  const fullName: string =
    (tokenParsed?.name as string) ?? username;

  const email: string = (tokenParsed?.email as string) ?? "";

  const roles: string[] =
    ((tokenParsed?.realm_access as { roles?: string[] })?.roles) ?? [];

  return {
    initialized,
    authenticated: !!keycloak.authenticated,
    token: keycloak.token ?? "",
    username,
    fullName,
    email,
    roles,
    logout: () => keycloak.logout(),
    keycloak,
  };
}
