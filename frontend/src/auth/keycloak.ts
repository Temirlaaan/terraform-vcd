import Keycloak from "keycloak-js";

/**
 * Keycloak JS adapter singleton.
 *
 * Reads configuration from Vite env vars:
 *   VITE_KEYCLOAK_URL   — e.g. "https://sso-ttc.t-cloud.kz"
 *   VITE_KEYCLOAK_REALM — e.g. "prod-v1"
 *   VITE_KEYCLOAK_CLIENT_ID — e.g. "terraform-dashboard"
 */
const keycloak = new Keycloak({
  url: import.meta.env.VITE_KEYCLOAK_URL ?? "https://sso-ttc.t-cloud.kz",
  realm: import.meta.env.VITE_KEYCLOAK_REALM ?? "prod-v1",
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "terraform-dashboard",
});

export default keycloak;
