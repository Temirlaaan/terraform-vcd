# Terraform VCD Dashboard — Fix Keycloak login loop + host migration

## Context

The Keycloak SSO integration in this project is currently broken. When a user
logs in through `https://sso-ttc.t-cloud.kz`, they get redirected back to the
app but the page enters an infinite loading loop with visible flickering.
Session storage is empty after return, no visible errors in browser console,
no errors on the Keycloak side, no meaningful server-side logs.

Separately, the project is being moved to a new host. Old IP `10.121.253.14`
must be replaced everywhere with the new IP `10.121.245.146`. The frontend
runs on port `5174`, the backend on `8000`.

Keycloak itself lives at `https://sso-ttc.t-cloud.kz` (IP `10.121.253.148`).
The backend container will need to resolve this hostname — see Part 3.

The Keycloak client `terraform-dashboard` is configured as **PUBLIC** (Client
authentication OFF, PKCE S256, Standard flow ON). `KEYCLOAK_CLIENT_SECRET` in
the backend `.env` is unused by the code and can be ignored.

**The user will handle `.env` changes themselves. Do not edit `.env` or
`.env.example` values — they're responsible for those.**

---

## Prerequisite (manual step, NOT a code change — just remind the user)

In Keycloak Admin UI → realm `prod-v1` → Clients → `terraform-dashboard` →
Settings: update all URLs from `http://10.121.253.14:5174` to
`http://10.121.245.146:5174`:
- Root URL
- Home URL
- Valid redirect URIs (keep trailing `/*`)
- Web origins (no trailing slash)
- Admin URL

Without this, Keycloak will reject the callback with "Invalid redirect_uri"
after login. Remind the user to do this before testing.

---

## Root cause analysis

### Why the loop happens

1. `main.tsx` wraps `<App />` in `<React.StrictMode>`.
2. In React 18 dev mode, StrictMode intentionally mounts every effect twice.
3. `@react-keycloak/web` v3.4.0 (last released in 2021, effectively
   unmaintained) calls `keycloak.init()` inside a `useEffect`. It runs twice.
4. `keycloak-js` v21 `init()` is NOT idempotent — the second call during a
   PKCE callback consumes/overwrites the PKCE `code_verifier` in
   sessionStorage that the first call was mid-way through using.
5. First `init()` exchanges the `code` for a token successfully. Second
   `init()` has no verifier and no token → `onLoad: "login-required"` kicks
   off ANOTHER redirect to Keycloak.
6. Keycloak has an active SSO session → silently redirects back with a new
   `code`. The cycle repeats. The browser starts marking history entries as
   "skippable" (the console warning the user observed).

### Secondary issues

- `useAuth.ts` calls `useKeycloak()` conditionally (after an early return
  when `AUTH_DISABLED`), violating Rules of Hooks. Currently masked by an
  `eslint-disable` comment because `AUTH_DISABLED` is a constant, but fragile.
- `TerminalDrawer.tsx` has `[operationId, token]` as `useEffect` deps. The
  axios interceptor calls `keycloak.updateToken(30)` before every API
  request, which can produce a new token and cause `useAuth()` to return a
  new token string → the WebSocket reconnects mid-operation, interrupting
  the terraform log stream.
- `KeycloakProvider.tsx` sets `redirectUri: window.location.origin + "/"`.
  User wants this kept at `/` but it can be simplified.
- `docker-compose.yml` has stale `VITE_API_URL` default pointing at the old
  IP. CORS default too.
- Backend container cannot resolve `sso-ttc.t-cloud.kz` without DNS config.
  Without it, JWKS fetch fails and every API call returns 401.

---

## Required changes

### Part 1: Replace `@react-keycloak/web` with a custom provider (FIXES THE LOOP)

This is the core fix. We're removing the unmaintained wrapper and using
`keycloak-js` directly with a module-level init guard. This makes StrictMode
safe and removes a known-broken dependency.

#### 1.1 — `frontend/src/auth/keycloak.ts`

Add a module-level singleton initializer. The key idea: `init()` is called
exactly once per page lifetime, regardless of how many times React mounts.

```typescript
import Keycloak from "keycloak-js";

const keycloak = new Keycloak({
  url: import.meta.env.VITE_KEYCLOAK_URL ?? "https://sso-ttc.t-cloud.kz",
  realm: import.meta.env.VITE_KEYCLOAK_REALM ?? "prod-v1",
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "terraform-dashboard",
});

// Module-level init guard. StrictMode mounts effects twice in dev; keycloak-js
// init() is not idempotent. Caching the promise makes it effectively a singleton.
let initPromise: Promise<boolean> | null = null;

export function initKeycloak(): Promise<boolean> {
  if (!initPromise) {
    initPromise = keycloak.init({
      onLoad: "login-required",
      checkLoginIframe: false,
      pkceMethod: "S256",
      // Always return to root after login (user preference)
      redirectUri: window.location.origin + "/",
    });
  }
  return initPromise;
}

export default keycloak;
```

#### 1.2 — `frontend/src/auth/KeycloakProvider.tsx`

Replace the ReactKeycloakProvider wrapper with a minimal custom provider.
It awaits `initKeycloak()`, then renders children. Also sets up a background
token refresh interval so that tokens are always fresh for API calls (we
remove the per-request refresh from axios in 1.4 below).

```typescript
import { Loader2 } from "lucide-react";
import { ReactNode, useEffect, useState } from "react";

import keycloak, { initKeycloak } from "./keycloak";

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

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

interface Props {
  children: ReactNode;
}

export function KeycloakProvider({ children }: Props) {
  const [initialized, setInitialized] = useState(AUTH_DISABLED);

  useEffect(() => {
    if (AUTH_DISABLED) return;

    initKeycloak()
      .then(() => setInitialized(true))
      .catch((err) => {
        console.error("[keycloak] init failed:", err);
        // Fallback: still render, will trigger login on first protected call
        setInitialized(true);
      });

    // Background refresh — keeps the token fresh without doing a refresh
    // on every single API request (which caused WebSocket reconnects).
    const interval = setInterval(() => {
      keycloak
        .updateToken(60)
        .catch(() => {
          console.warn("[keycloak] token refresh failed, forcing login");
          keycloak.login();
        });
    }, 30_000);

    return () => clearInterval(interval);
  }, []);

  if (!initialized) return <AuthLoading />;
  return <>{children}</>;
}
```

#### 1.3 — `frontend/src/auth/useAuth.ts`

Rewrite without `useKeycloak()`. Read directly from the singleton. Use a
small forceUpdate pattern so components re-render when auth state changes.

```typescript
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
  return {
    initialized: !!keycloak.authenticated || keycloak.didInitialize === true,
    authenticated: !!keycloak.authenticated,
    token: keycloak.token ?? "",
    username:
      (tokenParsed?.preferred_username as string) ??
      (tokenParsed?.name as string) ??
      "",
    fullName: (tokenParsed?.name as string) ?? "",
    email: (tokenParsed?.email as string) ?? "",
    roles:
      ((tokenParsed?.realm_access as { roles?: string[] })?.roles) ?? [],
    logout: () => keycloak.logout(),
  };
}

export function useAuth(): AuthState {
  const [state, setState] = useState<AuthState>(readAuthState);

  useEffect(() => {
    if (AUTH_DISABLED) return;

    const rerender = () => setState(readAuthState());

    keycloak.onAuthSuccess = rerender;
    keycloak.onAuthRefreshSuccess = rerender;
    keycloak.onAuthLogout = rerender;
    keycloak.onTokenExpired = rerender;

    // Sync once after mount in case init completed while we were rendering.
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
```

Note: `keycloak-js` v21 has a `didInitialize` property. If its type
definition complains, just replace that line with `initialized: true` after
auth succeeds, or use your own boolean tracked via `onReady`.

#### 1.4 — `frontend/src/api/client.ts`

Simplify: no more per-request `updateToken(30)`. The background refresh in
`KeycloakProvider` handles it. This prevents the WebSocket reconnect issue
at its source.

```typescript
import axios from "axios";
import keycloak from "@/auth/keycloak";

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

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
```

#### 1.5 — `frontend/src/App.tsx`

Just confirm it still imports `KeycloakProvider` from `@/auth/KeycloakProvider`.
No other changes needed — our provider has the same API (children prop).

#### 1.6 — Remove `@react-keycloak/web` from dependencies

Edit `frontend/package.json`: remove the line `"@react-keycloak/web": "^3.4.0"`.
Remind the user to run `npm install` (or `docker compose build frontend`) after.

Do NOT downgrade or upgrade `keycloak-js`. Keep `"keycloak-js": "21.1.1"`.

---

### Part 2: WebSocket stability in TerminalDrawer

**Decision: keep the initial token; do not reconnect on refresh.**

Rationale: the backend validates the token only at the WebSocket handshake.
Once connected, the stream is trusted for its lifetime. Reconnecting
mid-operation would drop log lines — worse UX than a maybe-stale token on a
long-running connection. Since operations rarely exceed Keycloak's 5-minute
access token lifetime + refresh, this is safe in practice.

#### 2.1 — `frontend/src/components/TerminalDrawer.tsx`

Change the effect deps so the socket is (re)created only when `operationId`
changes. Snapshot the token once inside the effect.

Replace:
```typescript
useEffect(() => {
  if (!operationId || !token) return;
  // ...
}, [operationId, token]);
```

With:
```typescript
useEffect(() => {
  if (!operationId) return;

  // Snapshot the token at connection time. Subsequent token refreshes must
  // not trigger a reconnect — backend only validates at handshake, and
  // reconnecting mid-operation would drop log lines.
  const currentToken = token;
  if (!currentToken) return;

  setLogs([]);
  setConnected(false);

  const ws = new WebSocket(wsUrl(operationId, currentToken));
  // ... rest unchanged, but use `currentToken` in any captured reference
}, [operationId]);
// eslint-disable-next-line react-hooks/exhaustive-deps
```

The `token` variable is still read from `useAuth()` at effect-creation
time (it's closed over), but NOT tracked in deps — so a refreshed token
later on won't retrigger the effect. That's the whole point.

---

### Part 3: Host address migration + DNS for Keycloak

#### 3.1 — `docker-compose.yml`

1. Change default `VITE_API_URL` fallback from the old IP:
   ```yaml
   - VITE_API_URL=${VITE_API_URL:-http://10.121.245.146:8000}
   ```
2. Change default `CORS_ORIGINS` fallback (it was also referencing old
   thinking):
   ```yaml
   - CORS_ORIGINS=${CORS_ORIGINS:-http://10.121.245.146:5174}
   ```
3. Add `extra_hosts` to the `backend` service so the container can resolve
   `sso-ttc.t-cloud.kz` (needed for JWKS fetching):
   ```yaml
   backend:
     # ... existing config ...
     extra_hosts:
       - "sso-ttc.t-cloud.kz:10.121.253.148"
   ```

   Place `extra_hosts` next to `volumes` / `depends_on` at the same
   indentation level. Do NOT add it to frontend — the frontend runs in the
   user's browser, not in Docker.

#### 3.2 — `frontend/vite.config.ts`

Two options. Pick whichever is cleaner:

**Option A (recommended):** Since the frontend already uses `VITE_API_URL`
directly (via axios `baseURL`) and constructs WebSocket URLs against
`window.location.host`, the Vite proxy is dead code. Remove it:

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    host: "0.0.0.0",
  },
});
```

Wait — but the WebSocket URL in `TerminalDrawer.tsx` is built from
`window.location.host`. When the frontend is served from
`http://10.121.245.146:5174`, the WS will connect to
`ws://10.121.245.146:5174/ws/...` which goes to Vite, not the backend.

So we actually **do need the proxy** (for WS at least). Use Option B:

**Option B:** Update proxy targets to the new IP.

```typescript
server: {
  port: 5173,
  host: "0.0.0.0",
  proxy: {
    "/api": "http://10.121.245.146:8000",
    "/ws": {
      target: "ws://10.121.245.146:8000",
      ws: true,
    },
  },
},
```

Better yet — make the WS URL respect `VITE_API_URL` so we don't need the
proxy at all. In `TerminalDrawer.tsx`:

```typescript
function wsUrl(operationId: string, token: string): string {
  const apiUrl = import.meta.env.VITE_API_URL ?? window.location.origin;
  const wsBase = apiUrl.replace(/^http/, "ws");
  return `${wsBase}/ws/terraform/${operationId}?token=${encodeURIComponent(token)}`;
}
```

If you go this route, also update `docker-compose.yml` so the backend has
CORS for WS (it already does via the existing CORS middleware covering the
frontend origin, but WebSocket origin checks are handled by uvicorn — double
check this works end to end).

**Pick the approach that minimizes risk. My recommendation: do Option B
(update proxy to new IP) AND do not change the WS URL logic. Least churn.**

#### 3.3 — Grep for any other stale references

Run `grep -rn "10.121.253.14" .` in the repo (EXCLUDING `.env` and
`node_modules`) and fix remaining references. Likely already clean, but
worth a check.

---

### Part 4: Backend robustness (quick wins)

#### 4.1 — `backend/app/auth/keycloak.py` — robust audience check

For PUBLIC Keycloak clients with default scopes, the JWT `aud` claim is
`"account"` (from the `roles` scope). Current code hardcodes this. If
Anthropic later adds an Audience mapper or changes client scopes, every API
call will return 401 with a cryptic error. Make it robust.

Replace the audience validation:

```python
# Disable python-jose's audience check; verify manually with fallback.
payload = jwt.decode(
    token,
    rsa_key,
    algorithms=["RS256"],
    issuer=issuer,
    options={"verify_at_hash": False, "verify_aud": False},
)

# Accept either "account" (default Keycloak behaviour) or the client id.
aud = payload.get("aud")
aud_list = aud if isinstance(aud, list) else [aud] if aud else []
accepted = {"account", settings.keycloak_client_id}
if not (set(aud_list) & accepted):
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=f"Invalid token audience: {aud}",
    )
```

This catches both PUBLIC-client (aud="account") and Confidential-client (aud
includes client_id) deployments. No change needed elsewhere.

#### 4.2 — Nothing else on backend

Do not touch migration routes, deployments, database, or tests. Those are
out of scope.

---

## Files touched (summary)

```
frontend/src/auth/keycloak.ts            REWRITE
frontend/src/auth/KeycloakProvider.tsx   REWRITE
frontend/src/auth/useAuth.ts             REWRITE
frontend/src/api/client.ts               EDIT (simplify interceptor)
frontend/src/components/TerminalDrawer.tsx   EDIT (effect deps)
frontend/vite.config.ts                  EDIT (proxy targets)
frontend/package.json                    EDIT (remove @react-keycloak/web)
docker-compose.yml                       EDIT (defaults + extra_hosts)
backend/app/auth/keycloak.py             EDIT (audience check)
```

Do NOT edit:
- `.env` / `.env.example` (user handles it)
- `main.tsx` — keep StrictMode; our fix handles it
- Any migration / deployments / provision code
- Any tests (but feel free to run them)

---

## Verification checklist

After applying all changes and `docker-compose up -d --build`:

1. Hard-refresh `http://10.121.245.146:5174` in an incognito window.
2. Expected: single redirect to `sso-ttc.t-cloud.kz`, login page.
3. Log in with an account that has `tf-admin` / `tf-operator` / `tf-viewer`
   realm role.
4. Expected: single redirect back to `http://10.121.245.146:5174/`,
   Service Catalog page renders immediately. **No flicker. No loop.**
5. DevTools → Network: exactly ONE request to `/realms/prod-v1/protocol/openid-connect/token`
   with status 200. Not multiple.
6. DevTools → Application → Session Storage: there should be keys like
   `kc-callback-<uuid>` briefly during login, and after auth a key with the
   access token / refresh token (keycloak-js internal).
7. Top bar shows the real username + initials.
8. Open browser console, check that `keycloak.token` (in Console tab, after
   typing `window.keycloak`... actually this won't work because we don't
   expose it). Instead: go to Network, make any API call (navigate to
   Migration page), check request has `Authorization: Bearer eyJ...`.
9. Open the Terminal drawer. Trigger a Plan on a small config. Logs stream
   smoothly; no "WS reconnected" gaps. Let it run > 30 seconds to verify
   token refresh doesn't reconnect WS.
10. F5 on Migration page — form fields persist (except api_token), page
    does NOT re-trigger Keycloak login.

If step 2 still redirect-loops, open Keycloak Admin → Events → Login Events
(must be enabled in realm Events settings) and look for `CODE_TO_TOKEN_ERROR`.
That would indicate redirect-uri mismatch (back to the manual prerequisite).

---

## Code style reminders

- No emojis anywhere (code or UI).
- Strict TypeScript, no `any`.
- Path alias `@/` always, never relative `../../`.
- Reuse existing components; don't invent new styling tokens.
- If removing imports, also remove unused dead code they leave behind.
- Keep code comments in English. Keep them minimal and factual.
