import Keycloak from "keycloak-js";

const keycloak = new Keycloak({
  url: import.meta.env.VITE_KEYCLOAK_URL ?? "https://sso-ttc.t-cloud.kz",
  realm: import.meta.env.VITE_KEYCLOAK_REALM ?? "prod-v1",
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "terraform-dashboard",
});

// Debug: expose to window and log every event
(window as any).kc = keycloak;

keycloak.onAuthSuccess = () => console.log("[kc] onAuthSuccess", { token: !!keycloak.token, parsed: keycloak.tokenParsed });
keycloak.onAuthError = (e) => console.error("[kc] onAuthError", e);
keycloak.onAuthRefreshSuccess = () => console.log("[kc] onAuthRefreshSuccess");
keycloak.onAuthRefreshError = () => console.error("[kc] onAuthRefreshError");
keycloak.onAuthLogout = () => console.log("[kc] onAuthLogout");
keycloak.onTokenExpired = () => console.log("[kc] onTokenExpired");
keycloak.onReady = (auth) => console.log("[kc] onReady authenticated=", auth);

console.log("[kc] module eval, href=", window.location.href, "hash=", window.location.hash);

let initPromise: Promise<boolean> | null = null;

export function initKeycloak(): Promise<boolean> {
  if (!initPromise) {
    console.log("[kc] init() called, URL=", window.location.href);
    initPromise = keycloak.init({
      onLoad: "login-required",
      checkLoginIframe: false,
      pkceMethod: "S256",
      redirectUri: window.location.origin + "/",
      enableLogging: true,
    }).then((ok) => {
      console.log("[kc] init resolved authenticated=", ok, "token?", !!keycloak.token);
      return ok;
    }).catch((err) => {
      console.error("[kc] init rejected", err);
      throw err;
    });
  } else {
    console.log("[kc] init() re-call, returning cached promise");
  }
  return initPromise;
}

export default keycloak;
