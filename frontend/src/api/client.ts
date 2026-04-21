import axios from "axios";

import keycloak from "@/auth/keycloak";

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

/**
 * Axios instance for all backend API calls.
 *
 * Token freshness is maintained by a background refresh loop in
 * KeycloakProvider, so the request interceptor just attaches the
 * current token without touching updateToken().
 */
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "",
  headers: { "Content-Type": "application/json" },
});

if (!AUTH_DISABLED) {
  api.interceptors.request.use((config) => {
    if (keycloak.authenticated && keycloak.token) {
      config.headers.Authorization = `Bearer ${keycloak.token}`;
    }
    return config;
  });
}

export default api;
