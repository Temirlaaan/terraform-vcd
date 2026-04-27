import Keycloak from "keycloak-js";

const keycloak = new Keycloak({
  url: import.meta.env.VITE_KEYCLOAK_URL ?? "https://sso-ttc.t-cloud.kz",
  realm: import.meta.env.VITE_KEYCLOAK_REALM ?? "prod-v1",
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "terraform-dashboard",
});

if (import.meta.env.DEV) {
  keycloak.onAuthSuccess = () => console.log("[kc] onAuthSuccess", { token: !!keycloak.token });
  keycloak.onAuthError = (e) => console.error("[kc] onAuthError", e);
  keycloak.onAuthRefreshSuccess = () => console.log("[kc] onAuthRefreshSuccess");
  keycloak.onAuthRefreshError = () => console.error("[kc] onAuthRefreshError");
  keycloak.onAuthLogout = () => console.log("[kc] onAuthLogout");
  keycloak.onTokenExpired = () => console.log("[kc] onTokenExpired");
  keycloak.onReady = (auth) => console.log("[kc] onReady authenticated=", auth);
}

let initPromise: Promise<boolean> | null = null;

export function initKeycloak(): Promise<boolean> {
  if (!initPromise) {
    initPromise = keycloak.init({
      onLoad: "login-required",
      checkLoginIframe: false,
      pkceMethod: "S256",
      redirectUri: window.location.origin + "/",
      enableLogging: import.meta.env.DEV,
    }).then((ok) => {
      if (import.meta.env.DEV) console.log("[kc] init resolved authenticated=", ok);
      return ok;
    }).catch((err) => {
      console.error("[kc] init rejected", err);
      throw err;
    });
  }
  return initPromise;
}

export default keycloak;
