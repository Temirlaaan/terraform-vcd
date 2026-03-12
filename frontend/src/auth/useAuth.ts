import { useKeycloak } from "@react-keycloak/web";

/**
 * Convenience hook wrapping @react-keycloak/web.
 *
 * Returns the user's display name, roles, raw token, and logout helper.
 */
export function useAuth() {
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
