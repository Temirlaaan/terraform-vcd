import axios from "axios";

import keycloak from "@/auth/keycloak";

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

/**
 * Axios instance for all backend API calls.
 *
 * In development, Vite proxies `/api` → `http://localhost:8000`
 * (see vite.config.ts), so no VITE_API_URL is needed.
 *
 * In production, set VITE_API_URL to the backend origin.
 */
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "",
  headers: { "Content-Type": "application/json" },
});

/**
 * Request interceptor — injects the Keycloak Bearer token.
 *
 * Before each request, we attempt to refresh the token if it will
 * expire within the next 30 seconds, ensuring the backend always
 * receives a valid JWT.
 *
 * Skipped when AUTH_DISABLED is set.
 */
if (!AUTH_DISABLED) {
  api.interceptors.request.use(async (config) => {
    if (keycloak.authenticated) {
      // Refresh token if it expires within 30s
      try {
        await keycloak.updateToken(30);
      } catch {
        // Token refresh failed — force re-login
        keycloak.login();
        return config;
      }

      config.headers.Authorization = `Bearer ${keycloak.token}`;
    }
    return config;
  });
}

export default api;
