# Feature Additions: Keycloak Activation, Deployments, Form Persistence

Add three related features to the existing Terraform VCD Dashboard:

1. **Activate Keycloak authentication** — the code is already written but currently disabled via `AUTH_DISABLED=true`. Wire it up with real Keycloak credentials and verify the end-to-end flow.
2. **"Keep in deployments" save/reopen flow** — allow users to persist a successful migration HCL generation as a named deployment, view all deployments on a shared page, and reopen any deployment into the Migration form with HCL preview pre-populated.
3. **Form state persistence across page reloads** — the Migration form currently loses all data on F5 because it uses local `useState`. Migrate to a Zustand store with `persist` middleware, putting the API token in `sessionStorage` (session-scoped, for security) and the rest of the form in `localStorage`.

---

## Context

This project already has a working Migration feature (NSX-V → NSX-T edge migration) end-to-end: fetch legacy edge XML, normalize, generate HCL, run plan/apply via existing Terraform runner with WebSocket log streaming.

**Files to KNOW (reuse, do NOT rewrite):**
- `backend/app/auth/keycloak.py` — Keycloak JWT validation via JWKS, `AuthenticatedUser` dataclass, `get_current_user`, `validate_ws_token`, `AUTH_DISABLED` short-circuit
- `backend/app/auth/rbac.py` — `require_roles(*allowed)` dependency factory
- `backend/app/config.py` — `Settings` with `keycloak_url`, `keycloak_realm`, `keycloak_client_id`, `auth_disabled`
- `backend/app/api/routes/migration.py` — existing `/api/v1/migration/generate|plan|apply` endpoints
- `backend/app/models/template.py` — existing `Template` SQLAlchemy model (use as structural reference, but do NOT reuse for deployments — different domain)
- `backend/alembic/versions/0002_*.py` — migration file naming pattern
- `frontend/src/auth/KeycloakProvider.tsx` — React Keycloak provider with `login-required` and PKCE
- `frontend/src/auth/keycloak.ts` — Keycloak JS adapter singleton
- `frontend/src/auth/useAuth.ts` — auth hook with `AUTH_DISABLED` mock
- `frontend/src/api/client.ts` — axios with Bearer token interceptor
- `frontend/src/api/migrationApi.ts` — existing migration mutations
- `frontend/src/components/migration/*` — `MigrationForm`, `MigrationSummary`, `MigrationHclPreview`, `MigrationActionBar`
- `frontend/src/pages/MigrationPage.tsx` — wires the migration feature
- `frontend/src/pages/DeploymentsPage.tsx` — currently a placeholder, WILL BE REPLACED

**Non-goals:**
- Do NOT change the Provisioning flow (CatalogPage → ProvisionPage → `useConfigStore`). That feature already works.
- Do NOT add a separate signup/local-login UI. Auth is 100% Keycloak.
- Do NOT store `api_token` in the database under any circumstances.

---

## Feature 1: Activate Keycloak Authentication

### 1.1 Environment configuration

Update `.env.example` and `docker-compose.yml` to use the real SSO server. The deployment target is:

- `KEYCLOAK_URL=https://sso-ttc.t-cloud.kz`
- `KEYCLOAK_REALM=prod-v1`
- `KEYCLOAK_CLIENT_ID=terraform-dashboard`
- `AUTH_DISABLED=false`
- `VITE_AUTH_DISABLED=false`
- `VITE_KEYCLOAK_URL=https://sso-ttc.t-cloud.kz`
- `VITE_KEYCLOAK_REALM=prod-v1`
- `VITE_KEYCLOAK_CLIENT_ID=terraform-dashboard`

Make sure the frontend container in `docker-compose.yml` gets these `VITE_*` variables passed through.

### 1.2 RBAC policy for this iteration

All authenticated users should behave as admins for now. Concretely:

- Backend: keep `require_roles("tf-admin", "tf-operator", "tf-viewer")` permissive — ANY authenticated user with any of these roles can do anything. Do NOT add per-role gating.
- If the JWT has none of the three roles, the user should still get a clean error (403) from `require_roles`, not a blank page.
- Frontend: no role-based UI gating. Every authenticated user sees Plan/Apply/Destroy/Save.

(We may tighten this later; this prompt explicitly punts on it.)

### 1.3 Verify existing code still works

The Keycloak wiring code is already written. Your job is to:

1. Make sure `KeycloakProvider` is correctly initialized when `VITE_AUTH_DISABLED=false`.
2. Verify the axios interceptor adds `Authorization: Bearer <token>` and refreshes tokens 30s before expiry.
3. Verify the WebSocket endpoint (`/ws/terraform/{operation_id}?token=<jwt>`) authenticates via `validate_ws_token`. Because the frontend TerminalDrawer reads `token` from `useAuth()` and passes it as a query param — confirm this path works end-to-end.
4. Verify `AuthenticatedUser.sub` and `username` get populated from real Keycloak tokens and are written into `operations.user_id` / `operations.username` when a plan/apply runs.

### 1.4 UI additions

- In `Layout.tsx` TopBar, the user avatar and logout are already wired via `useAuth()`. Verify they render the real user's name after login.
- If `useAuth().authenticated` is false (shouldn't happen with `login-required`, but as a safety net), redirect to Keycloak login.

### 1.5 Testing

- Add a backend test `backend/tests/test_auth_flow.py` with mocked JWKS that validates:
  - Valid token with `tf-admin` role → `/api/v1/deployments` returns 200
  - Valid token with no roles → returns 403 with "Insufficient permissions"
  - No token → 401
  - Expired token → 401
- Document manual smoke test steps in a comment at top of `test_auth_flow.py`.

---

## Feature 2: Deployments (Saved Migration Configs)

### 2.1 Data model

New SQLAlchemy model `backend/app/models/deployment.py`:

```python
class Deployment(Base):
    __tablename__ = "deployments"
    __table_args__ = (
        Index("ix_deployments_target_edge_id", "target_edge_id"),
        Index("ix_deployments_created_by", "created_by"),
        Index("ix_deployments_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="migration")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Source (legacy VCD) — NO api_token, NEVER
    source_host: Mapped[str] = mapped_column(String(255), nullable=False)
    source_edge_uuid: Mapped[str] = mapped_column(String(255), nullable=False)
    source_edge_name: Mapped[str] = mapped_column(String(255), nullable=False)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Target VCD
    target_org: Mapped[str] = mapped_column(String(255), nullable=False)
    target_vdc: Mapped[str] = mapped_column(String(255), nullable=False)
    target_vdc_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_edge_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Generated artifact
    hcl: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Metadata
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)  # Keycloak username
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
```

Register in `backend/app/models/__init__.py`.

### 2.2 Alembic migration

Create `backend/alembic/versions/0003_create_deployments_table.py` following the pattern in `0001_*.py` and `0002_*.py`. Depends on `0002`.

### 2.3 Pydantic schemas

Create `backend/app/schemas/deployment.py`:

```python
class DeploymentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    source_host: str = Field(..., min_length=1)
    source_edge_uuid: str = Field(..., min_length=1)
    source_edge_name: str = Field(..., min_length=1)
    verify_ssl: bool = False
    target_org: str = Field(..., min_length=1)
    target_vdc: str = Field(..., min_length=1)
    target_vdc_id: str = Field(..., min_length=1)
    target_edge_id: str = Field(..., min_length=1)
    hcl: str = Field(..., min_length=1)
    summary: dict

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_safe_name(v, "name")  # reuse existing helper from app.schemas.terraform


class DeploymentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None


class DeploymentOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    description: str | None
    source_host: str
    source_edge_uuid: str
    source_edge_name: str
    verify_ssl: bool
    target_org: str
    target_vdc: str
    target_vdc_id: str
    target_edge_id: str
    hcl: str
    summary: dict
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeploymentListItem(BaseModel):
    """Lightweight item for list views (no HCL body — can be megabytes)."""
    id: uuid.UUID
    name: str
    kind: str
    description: str | None
    source_edge_name: str
    target_org: str
    target_vdc: str
    summary: dict
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeploymentList(BaseModel):
    items: list[DeploymentListItem]
    total: int
```

### 2.4 REST routes

Create `backend/app/api/routes/deployments.py`:

- `POST /api/v1/deployments` — create. Body: `DeploymentCreate`. Returns `DeploymentOut` (201). `created_by` comes from `AuthenticatedUser.username`, NOT the request body. Protected by `require_roles("tf-admin", "tf-operator", "tf-viewer")` — everyone can save.
- `GET /api/v1/deployments` — list all. Query params: `target_edge_id` (optional filter), `limit` (default 50, max 200), `offset`. Returns `DeploymentList`. Sort by `created_at DESC`. Protected by `require_roles("tf-admin", "tf-operator", "tf-viewer")`.
- `GET /api/v1/deployments/{id}` — fetch single with full HCL. Returns `DeploymentOut`. 404 if not found.
- `PATCH /api/v1/deployments/{id}` — update name/description only. Body: `DeploymentUpdate`. Returns `DeploymentOut`.
- `DELETE /api/v1/deployments/{id}` — delete. Returns 204. For this iteration, any authenticated user can delete any deployment (since everyone is admin).

Register router in `backend/app/main.py`: `app.include_router(deployments_router, prefix="/api/v1")`.

### 2.5 Layer 1 duplicate check (mandatory)

When the user selects a target edge in the Migration form, the frontend issues `GET /api/v1/deployments?target_edge_id=<urn>`. If `total > 0`, display a yellow warning banner above the form:

> ⚠ На эту edge уже сохранено деплойментов: **N**.
> `<name1>`, `<name2>`, ...

Each deployment name should be a clickable link that navigates to `/migration?deployment=<id>` (which hydrates the form from that deployment — see 2.8).

This check is purely informational — users can still proceed with a fresh migration.

### 2.6 Layer 2 duplicate check (Phase 2 — do AFTER 2.1-2.5 work)

Add methods to `backend/app/integrations/vcd_client.py`:

```python
@cached(prefix="vcd:ipsets", ttl=60)
async def get_ip_sets_on_edge(self, edge_id: str) -> list[dict]: ...
    # GET /cloudapi/1.0.0/edgeGateways/{edge_id}/ipSets

@cached(prefix="vcd:natrules", ttl=60)
async def get_nat_rules_on_edge(self, edge_id: str) -> list[dict]: ...
    # GET /cloudapi/1.0.0/edgeGateways/{edge_id}/natRules

@cached(prefix="vcd:fwrules", ttl=60)
async def get_firewall_rules_on_edge(self, edge_id: str) -> dict: ...
    # GET /cloudapi/1.0.0/edgeGateways/{edge_id}/firewall/rules — returns container with `userDefinedRules`

@cached(prefix="vcd:staticroutes", ttl=60)
async def get_static_routes_on_edge(self, edge_id: str) -> list[dict]: ...
    # GET /cloudapi/1.0.0/edgeGateways/{edge_id}/routing/staticRoutes
```

New endpoint in `backend/app/api/routes/migration.py`:

```python
@router.get("/target-check")
async def target_check(edge_id: str = Query(...), user: AuthenticatedUser = Depends(_any_role)):
    _validate_urn(edge_id, "edge_id")
    ip_sets = await vcd_client.get_ip_sets_on_edge(edge_id)
    nat_rules = await vcd_client.get_nat_rules_on_edge(edge_id)
    fw = await vcd_client.get_firewall_rules_on_edge(edge_id)
    routes = await vcd_client.get_static_routes_on_edge(edge_id)
    return {
        "ip_sets_count": len(ip_sets),
        "nat_rules_count": len(nat_rules),
        "firewall_rules_count": len(fw.get("userDefinedRules", [])),
        "static_routes_count": len(routes),
    }
```

Frontend: right BEFORE submitting `/migration/generate` or `/migration/plan`, fetch `/target-check`. If any count > 0, display a confirmation modal:

> ⚠ На целевой edge gateway уже существуют:
> - IP Sets: X
> - NAT rules: Y
> - Firewall rules: Z
> - Static routes: W
>
> Эта миграция может создать дубли. Продолжить?
>
> [ Отменить ] [ Продолжить ]

### 2.7 Frontend: API hooks

Create `frontend/src/api/deploymentsApi.ts`:

```typescript
export interface DeploymentListItem {
  id: string;
  name: string;
  kind: string;
  description: string | null;
  source_edge_name: string;
  target_org: string;
  target_vdc: string;
  summary: MigrationSummary;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface Deployment extends DeploymentListItem {
  source_host: string;
  source_edge_uuid: string;
  verify_ssl: boolean;
  target_vdc_id: string;
  target_edge_id: string;
  hcl: string;
}

export function useDeployments(targetEdgeId?: string) { /* GET /deployments?... */ }
export function useDeployment(id: string | undefined) { /* GET /deployments/{id} */ }
export function useCreateDeployment() { /* POST */ }
export function useDeleteDeployment() { /* DELETE + queryClient.invalidateQueries(['deployments']) */ }
export function useUpdateDeployment() { /* PATCH */ }
export function useTargetCheck() { /* GET /migration/target-check */ }
```

All hooks should invalidate the relevant query keys on mutation success.

### 2.8 Frontend: Deployments page

Replace `frontend/src/pages/DeploymentsPage.tsx` with a real list view:

- Header: title "Saved Deployments" + refresh button.
- Main content: responsive grid of deployment cards. Each card shows:
  - Icon (arrows — migration)
  - Name (large, clickable → `/migration?deployment=<id>`)
  - `source_edge_name` (legacy edge)
  - → `target_org / target_vdc`
  - Summary badges: X FW rules, Y NAT, Z static routes
  - `created_by` + relative date ("3 hours ago" style)
  - Kebab menu with Rename, Delete (with confirm modal).
- Empty state: friendly illustration + "No saved deployments yet. Run a migration and click 'Keep in deployments' to save it here."
- Loading skeleton while query is pending.

Follow the existing card style (`frontend/src/pages/CatalogPage.tsx`) — white bg, `border-clr-border`, hover border `clr-action`.

### 2.9 Frontend: "Keep in deployments" button

Add to `frontend/src/components/migration/MigrationActionBar.tsx` (or create a new `MigrationSaveBar` component above it) — a secondary action button, available only when `mutation.data` is present (i.e., HCL was generated):

- Button label: "Keep in deployments"
- Icon: `Save` (lucide-react)
- Style: secondary/outlined — NOT the primary Plan/Apply color
- On click: open a modal asking for deployment name (default: `${edge_name}_${YYYYMMDD}`) and optional description.
- Confirm → `useCreateDeployment` with all required fields pulled from the current form state + result.
- Success: toast "Deployment saved" (or similar inline notification — don't add a toast library if not already present; use the existing `AlertCircle` pattern with a success variant).

### 2.10 Frontend: reopen flow

When `/migration?deployment=<uuid>` is opened:

1. `MigrationPage` reads the `deployment` search param.
2. If present, calls `useDeployment(id)`.
3. When data arrives, call `useMigrationStore.getState().hydrateFromDeployment(deployment)` — this sets the form fields AND the result (HCL + summary + edge name).
4. The form renders with pre-filled fields (except `api_token`, which stays empty — user must re-enter if they want to re-fetch).
5. The HCL preview on the right is shown immediately (from saved HCL).
6. Plan/Apply buttons work without re-entering api_token, because those endpoints don't need legacy VCD access — they work with pre-generated HCL and use backend-configured target VCD creds via `TF_VAR_*`. Only clicking "Regenerate HCL" requires the token.
7. Clear the `deployment` param from the URL after hydration (use `navigate("/migration", { replace: true })`) so refresh doesn't re-hydrate on top of user's edits.

---

## Feature 3: Form State Persistence

### 3.1 Create `useMigrationStore`

Create `frontend/src/store/useMigrationStore.ts` using Zustand with `persist` middleware. Mirrors the existing `useConfigStore` patterns.

```typescript
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { MigrationSummary } from "@/api/migrationApi";
import type { Deployment } from "@/api/deploymentsApi";

const API_TOKEN_STORAGE_KEY = "migration_api_token";

export interface MigrationFormState {
  host: string;
  edgeUuid: string;
  orgId: string;        // URN — used for cascading dropdowns
  orgName: string;      // name — sent to API
  vdcId: string;
  vdcName: string;
  edgeGatewayId: string;
  verifySsl: boolean;
}

export interface MigrationResult {
  hcl: string;
  edgeName: string;
  summary: MigrationSummary;
}

interface MigrationStore {
  form: MigrationFormState;
  apiToken: string;       // sessionStorage-backed — NOT persisted via the persist middleware
  result: MigrationResult | null;  // NOT persisted — regenerated

  setFormField: <K extends keyof MigrationFormState>(key: K, value: MigrationFormState[K]) => void;
  setApiToken: (token: string) => void;
  setResult: (result: MigrationResult | null) => void;
  hydrateFromDeployment: (d: Deployment) => void;
  resetForm: () => void;
}

const defaultForm: MigrationFormState = {
  host: "",
  edgeUuid: "",
  orgId: "",
  orgName: "",
  vdcId: "",
  vdcName: "",
  edgeGatewayId: "",
  verifySsl: false,
};

// Initial api_token comes from sessionStorage (survives F5, not browser close)
const getInitialApiToken = (): string => {
  if (typeof window === "undefined") return "";
  return sessionStorage.getItem(API_TOKEN_STORAGE_KEY) || "";
};

export const useMigrationStore = create<MigrationStore>()(
  persist(
    (set) => ({
      form: defaultForm,
      apiToken: getInitialApiToken(),
      result: null,

      setFormField: (key, value) =>
        set((s) => ({ form: { ...s.form, [key]: value } })),

      setApiToken: (token) => {
        set({ apiToken: token });
        if (typeof window !== "undefined") {
          if (token) {
            sessionStorage.setItem(API_TOKEN_STORAGE_KEY, token);
          } else {
            sessionStorage.removeItem(API_TOKEN_STORAGE_KEY);
          }
        }
      },

      setResult: (result) => set({ result }),

      hydrateFromDeployment: (d) =>
        set({
          form: {
            host: d.source_host,
            edgeUuid: d.source_edge_uuid,
            orgId: "",                 // not saved — user re-selects if needed
            orgName: d.target_org,
            vdcId: d.target_vdc_id,
            vdcName: d.target_vdc,
            edgeGatewayId: d.target_edge_id,
            verifySsl: d.verify_ssl,
          },
          result: {
            hcl: d.hcl,
            edgeName: d.source_edge_name,
            summary: d.summary,
          },
        }),

      resetForm: () => {
        if (typeof window !== "undefined") {
          sessionStorage.removeItem(API_TOKEN_STORAGE_KEY);
        }
        set({ form: defaultForm, apiToken: "", result: null });
      },
    }),
    {
      name: "migration-form",
      storage: createJSONStorage(() => localStorage),
      // Only persist `form`. api_token goes to sessionStorage via setApiToken.
      // result is ephemeral.
      partialize: (state) => ({ form: state.form }),
      version: 1,
    }
  )
);
```

### 3.2 Refactor `MigrationForm.tsx`

Remove all local `useState` for form fields. Replace with `useMigrationStore(...)` selectors. Each input's `onChange` calls `setFormField("...", v)`.

The `api_token` input's `onChange` calls `setApiToken(v)`.

Cascading dropdowns — when the user picks a new org, clear dependent fields (`vdcId`, `vdcName`, `edgeGatewayId`) via `setFormField` calls. Same when VDC changes.

### 3.3 Refactor `MigrationPage.tsx`

- Read `result` from the store for rendering the right panel (not from `mutation.data`).
- After `mutation` resolves successfully, call `setResult({ hcl, summary, edgeName })`.
- `lastSubmit.current` pattern can go away — pass `target_org` and `target_edge_id` from the store to `MigrationActionBar`.

### 3.4 "Reset" button

Add a small reset icon button next to the header in `MigrationForm` (or in the `MigrationPage` sidebar header, next to "Edge Migration" title) — clicking it calls `resetForm()` and clears the URL `deployment` param. Same pattern as the existing `ProvisionPage` reset button.

---

## Env changes

**`.env.example`:**
Already has the right fields. Just change the default of `AUTH_DISABLED=false`.

**`docker-compose.yml`:**
Make sure `backend` and `frontend` services both receive the `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, and `VITE_KEYCLOAK_*`, `VITE_AUTH_DISABLED` variables explicitly from the host `.env`.

---

## Tests

### Backend
- `backend/tests/test_auth_flow.py` — roles, missing token, expired token (mocked JWKS). Instructions for manual smoke test at top.
- `backend/tests/test_deployments.py`
  - Create with valid body → 201, returns `DeploymentOut` with server-side `id`, `created_at`, `created_by` (from mocked user).
  - Create fails with empty name → 422.
  - List returns items sorted by `created_at DESC`.
  - List with `target_edge_id` filter returns only matching.
  - Get by id returns 200 with full HCL.
  - Get nonexistent id → 404.
  - Patch updates name only; other fields ignored.
  - Delete → 204, subsequent GET → 404.
  - Create ignores `created_by` in request body and uses `user.username` from dependency.
- `backend/tests/test_vcd_client.py` — extend with tests for new `get_ip_sets_on_edge`, `get_nat_rules_on_edge`, `get_firewall_rules_on_edge`, `get_static_routes_on_edge` (Phase 2).
- `backend/tests/test_api_migration.py` — extend with tests for `/target-check` endpoint (Phase 2).

### Frontend
No new unit tests required. Manual smoke test checklist in commit message:
1. `AUTH_DISABLED=true` → app works as before.
2. `AUTH_DISABLED=false` → Keycloak login screen appears, tokens flow through API calls and WebSocket.
3. Generate HCL → Keep in deployments → appears on DeploymentsPage.
4. Click deployment → opens MigrationPage with form + HCL pre-populated, api_token empty.
5. F5 on MigrationPage with partial form data → all fields except api_token restored from localStorage.
6. Close tab, reopen → form restored (localStorage), api_token empty (sessionStorage cleared).
7. Within same tab, F5 → api_token still present (sessionStorage survives reload).
8. Two users save deployments with different Keycloak accounts → both visible to each other.

---

## Deliverables Checklist

### Backend
- [ ] `backend/app/models/deployment.py` — `Deployment` model
- [ ] `backend/app/models/__init__.py` — export `Deployment`
- [ ] `backend/alembic/versions/0003_create_deployments_table.py`
- [ ] `backend/alembic/env.py` — import `Deployment` for autogenerate (add to existing `noqa` line)
- [ ] `backend/app/schemas/deployment.py` — `DeploymentCreate`, `DeploymentUpdate`, `DeploymentOut`, `DeploymentListItem`, `DeploymentList`
- [ ] `backend/app/api/routes/deployments.py` — CRUD endpoints
- [ ] `backend/app/main.py` — register deployments router
- [ ] `backend/app/integrations/vcd_client.py` — 4 new methods for target-check (Phase 2)
- [ ] `backend/app/api/routes/migration.py` — `/target-check` endpoint (Phase 2)
- [ ] `backend/tests/test_auth_flow.py`
- [ ] `backend/tests/test_deployments.py`

### Frontend
- [ ] `frontend/src/api/deploymentsApi.ts` — hooks
- [ ] `frontend/src/store/useMigrationStore.ts` — Zustand store
- [ ] `frontend/src/components/migration/MigrationForm.tsx` — refactor to use store
- [ ] `frontend/src/components/migration/MigrationActionBar.tsx` — read state from store
- [ ] `frontend/src/components/migration/MigrationSaveButton.tsx` (new) — "Keep in deployments" button with modal
- [ ] `frontend/src/components/migration/DuplicateDeploymentBanner.tsx` (new) — Layer 1 warning
- [ ] `frontend/src/components/migration/TargetCheckModal.tsx` (new, Phase 2) — Layer 2 modal
- [ ] `frontend/src/pages/MigrationPage.tsx` — read `deployment` query param, hydrate on mount
- [ ] `frontend/src/pages/DeploymentsPage.tsx` — REPLACE placeholder with real list view

### Config
- [ ] `.env.example` — set `AUTH_DISABLED=false` as default
- [ ] `docker-compose.yml` — pass `VITE_KEYCLOAK_*` through to frontend service

---

## Implementation order

Do these in order, committing between each step:

1. **Keycloak activation + tests.** Wire env, verify login works end-to-end, add `test_auth_flow.py`.
2. **Migration store + form persistence.** Create `useMigrationStore`, refactor `MigrationForm` and `MigrationPage`. Manually verify F5 and sessionStorage/localStorage behavior.
3. **Deployments backend.** Model, migration, schemas, routes, tests. Hit the API with curl/httpie to verify before touching frontend.
4. **Deployments frontend.** `deploymentsApi.ts`, `DeploymentsPage.tsx`, `MigrationSaveButton.tsx`.
5. **Reopen flow.** `?deployment=<id>` URL param, `hydrateFromDeployment` call on mount.
6. **Layer 1 duplicate check.** `DuplicateDeploymentBanner` on form, wire to `useDeployments({targetEdgeId})`.
7. **Phase 2 — Layer 2 duplicate check.** Only after steps 1-6 are solid.

---

## Code style reminders

- Python 3.11, FastAPI, SQLAlchemy 2.0 async, Pydantic v2, type hints everywhere.
- React 18, TypeScript strict, Tailwind with `clr-*` design tokens.
- No emojis in code or UI copy (Russian or English — the user's dashboard is bilingual in parts; match the existing page's language).
- No `any` in TypeScript.
- Always use the path alias `@/` — never `../../`.
- Reuse shared components: `FormInput`, `FormCheckbox`, `FormSelect` from `@/components/shared`.
- Never log or commit `api_token`, `vcd_password`, or `keycloak_client_secret`.
- For new error banners and modals, follow the existing styling in `MigrationActionBar` and `MigrationPage` (e.g., `bg-red-50 border-clr-danger/30` for errors, `bg-amber-50 border-amber-200` for warnings).
