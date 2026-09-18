# Terraform VCD Dashboard — Claude Code Configuration

## Project Overview

terraform-vcd is a full-stack web dashboard for managing VMware Cloud Director infrastructure through Terraform. It covers four flows:

1. **Provision** — fill a form → generate HCL → `terraform plan` / `apply` / `destroy` with live output.
2. **Migration** — pull an NSX-V edge gateway config from a legacy VCD, normalize it, and re-render it as NSX-T HCL against a new edge.
3. **Deployments** — persisted edge configurations (firewall / NAT / IP sets / app port profiles / static routes) with a structured spec editor.
4. **Lifecycle** — versioning, drift detection, rollback, and import of pre-existing VCD edges into management.

## Tech Stack

- **Backend**: FastAPI (Python 3.11), async SQLAlchemy 2 + asyncpg, Redis, Jinja2 HCL templates, boto3 (MinIO), APScheduler, defusedxml, python-jose
- **Frontend**: React 18, TypeScript 5.7, Vite 6, Tailwind CSS, Zustand, TanStack Query, react-router-dom 7, keycloak-js, `diff`
- **Auth**: Keycloak SSO (JWT + JWKS, `aud` enforced), RBAC with 3 roles (tf-admin, tf-operator, tf-viewer)
- **Infra**: PostgreSQL 15, Redis 7 (password + renamed dangerous commands), MinIO (Terraform S3 state + version snapshots), Terraform 1.7.5 CLI, Docker Compose, nginx (frontend runtime + host reverse proxy)
- **IaC target**: VMware VCD, NSX-T backed resources via the `vmware/vcd` provider `~> 3.12`

## Project Structure

```
terraform-vcd/
├── backend/
│   ├── app/
│   │   ├── main.py                       # FastAPI entry, router wiring, AUTH_DISABLED guardrail, /health
│   │   ├── config.py                     # Pydantic Settings (incl. TF_ENV, CORS validation, drift-sync cron)
│   │   ├── database.py                   # SQLAlchemy async engine
│   │   ├── scheduler.py                  # APScheduler — daily drift sync
│   │   ├── api/routes/
│   │   │   ├── terraform.py              # /terraform  — generate, plan, apply, destroy
│   │   │   ├── metadata.py               # /metadata   — VCD orgs, pvdcs, vdcs, edges, edge clusters, networks
│   │   │   ├── migration.py              # /migration  — auth-handle, generate, plan, apply, target-check
│   │   │   ├── deployments.py            # /deployments — CRUD, spec PUT, editor-data
│   │   │   ├── deployment_hcl.py         # /deployments/{id} — hcl, plan, apply, state orphans
│   │   │   ├── versions.py               # /deployments/{id}/versions, snapshots, pin
│   │   │   ├── drift.py                  # /deployments/{id}/drift-check, /drift-reports
│   │   │   ├── rollback.py               # /deployments/{id}/rollback/{prepare,confirm}
│   │   │   ├── imports.py                # /deployments/available-edges, import existing edge
│   │   │   └── ws.py                     # WebSocket log streaming (+ ownership check)
│   │   ├── auth/
│   │   │   ├── keycloak.py               # JWT/JWKS validation, audience check
│   │   │   └── rbac.py                   # require_roles(...) dependency factory
│   │   ├── core/
│   │   │   ├── tf_runner.py              # Terraform CLI subprocess + stream redaction
│   │   │   ├── tf_workspace.py           # Workspace lifecycle
│   │   │   ├── hcl_generator.py          # Jinja2 → HCL (provision flow)
│   │   │   ├── deployment_builder.py     # DeploymentSpec → main.tf
│   │   │   ├── deployment_spec_from_state.py  # tfstate → DeploymentSpec (editor round-trip)
│   │   │   ├── deployment_state_align.py # Re-map state addresses when HCL is rebuilt
│   │   │   ├── state_to_hcl.py           # Patch HCL to match drifted state
│   │   │   ├── state_hash.py             # Canonical state hashing for version dedup
│   │   │   ├── version_store.py          # Snapshot / rotate / restore versions in MinIO
│   │   │   ├── minio_client.py           # boto3 S3 wrapper (async via to_thread)
│   │   │   ├── rollback.py               # Whole-deployment rollback (prepare → confirm)
│   │   │   ├── drift_importer.py         # Auto-import unmanaged VCD resources during drift sync
│   │   │   ├── tf_import.py              # Pre-apply conflict resolution via terraform import
│   │   │   ├── import_firewall.py        # Firewall-specific import helper
│   │   │   ├── plan_parser.py            # Parse `terraform show -json` for drift classification
│   │   │   ├── redact.py                 # Secret redaction (at-store + at-stream)
│   │   │   ├── vcd_handle.py             # Redis-backed opaque handle for legacy-VCD API tokens
│   │   │   ├── aria_attribution.py       # Embed kc_user into VCD-visible descriptions
│   │   │   ├── locking.py                # Redis distributed locks
│   │   │   └── cache.py                  # Redis cache decorator
│   │   ├── migration/
│   │   │   ├── fetcher.py                # Pull raw NSX-V edge XML from legacy VCD
│   │   │   ├── normalizer.py             # XML → canonical JSON (defusedxml)
│   │   │   └── generator.py              # Canonical JSON → NSX-T HCL
│   │   ├── jobs/drift_sync.py            # Daily reconcile of dashboard state vs VCD reality
│   │   ├── integrations/vcd_client.py    # VCD CloudAPI client
│   │   ├── models/                       # Operation, Template, Deployment, DeploymentVersion, DriftReport
│   │   └── schemas/                      # Pydantic schemas (incl. DeploymentSpec)
│   ├── templates/
│   │   ├── *.tf.j2                       # Provision flow (base, organization, vdc, edgegateway, network, vapp)
│   │   ├── deployment/*.tf.j2            # Deployment spec → HCL
│   │   └── migration/*.tf.j2             # Migration flow → HCL
│   ├── alembic/versions/                 # 0001 operations+templates, 0002 indexes, 0003 deployments
│   └── tests/
├── frontend/
│   ├── Dockerfile                        # Multi-stage: node build → nginx runtime
│   ├── nginx.conf
│   └── src/
│       ├── App.tsx                       # Routes + RequireRole guards
│       ├── pages/                        # Catalog, Provision, Migration, Deployments{,Detail,Editor}, Settings, Unauthorized, NotFound
│       ├── components/{provision,migration,shared}/
│       ├── api/                          # Axios client + React Query hooks per domain
│       ├── auth/                         # Keycloak provider, useAuth, RequireRole
│       └── store/                        # useConfigStore, useMigrationStore
├── deploy/nginx/tf-dashboard.conf        # Host reverse proxy
├── docker-compose.yml                    # postgres, redis, minio, minio-init, backend, frontend
└── .env.example
```

## Key Architecture Patterns

- **Credentials safety**: secrets injected via `TF_VAR_*` env vars, NEVER written into HCL files
- **Distributed locking**: Redis `SET NX` per org prevents concurrent terraform ops (409 Conflict); release via compare-and-delete Lua script
- **Real-time streaming**: Redis Pub/Sub → WebSocket → Terminal UI; WS subscribe enforces operation ownership or `tf-admin`
- **Secret redaction**: `core/redact.py` applied twice — SQLAlchemy event hook before `Operation` rows hit the DB, and in `tf_runner._read_stream` before lines are published
- **Legacy-VCD token handling**: the browser never stores the VCD API token — `POST /migration/auth-handle` exchanges it for a short-lived opaque UUID backed by Redis
- **Versioning**: every apply snapshots HCL + state into MinIO under `deployments/<id>/v<N>/`; `state_hash` dedupes no-op versions; versions can be pinned or rolled back
- **Drift sync**: APScheduler cron (default `0 3 * * *`, `Asia/Almaty`) runs `sync_all_deployments`; results land in `drift_reports` and flag `deployment.needs_review`
- **Attribution**: `aria_attribution.py` stamps the Keycloak username into VCD resource descriptions so VCD-side audit shows who acted
- **AUTH_DISABLED guardrail**: the app refuses to start with `AUTH_DISABLED=true` unless `TF_ENV=dev` AND `DASHBOARD_HOSTNAME` is a localhost address
- **CORS**: `cors_origins_list` rejects `*`, `null`, and wildcard subdomains — explicit http(s) origins only
- **Async throughout**: FastAPI, httpx, asyncpg, Redis; boto3 (sync) is dispatched via `asyncio.to_thread`
- **VCD metadata caching**: Redis TTL 5 min via the `@cached` decorator; frontend `staleTime` matches

## RBAC Matrix

| Area | tf-admin | tf-operator | tf-viewer |
|---|---|---|---|
| Metadata, deployment list/detail, version list, drift reports, target-check | ✅ | ✅ | ✅ |
| Terraform generate | ✅ | ✅ | ✅ |
| Plan / apply / destroy, deployment write, spec edit | ✅ | ✅ | ❌ |
| Migration (auth-handle, generate, plan, apply) | ✅ | ✅ | ❌ |
| Deployment HCL read + plan/apply, version HCL, drift-check trigger | ✅ | ✅ | ❌ |
| Version raw state, pin/unpin, named snapshot, import existing edge, rollback | ✅ | ❌ | ❌ |

Frontend mirrors this: `RequireRole` guards `/provision`, `/migration`, `/deployments/new`, `/deployments/:id/edit` (writers) and `/settings` (admin). Viewers are redirected from the index route to `/deployments` and do not see the Service Catalog, Settings, or the HCL tab.

## Resource Dependency Order

All VCD resources use NSX-T backed variants. Create in this order:

```
vcd_org → vcd_org_vdc → vcd_nsxt_edgegateway → vcd_network_routed_v2 → vcd_vapp → vcd_vapp_vm
       → vcd_nsxt_ip_set / vcd_nsxt_app_port_profile → vcd_nsxt_nat_rule → vcd_nsxt_firewall
       → vcd_nsxt_edgegateway_static_route
```

Each resource may reference its parent via a Terraform data source (e.g. edge gateway uses `data.vcd_org_vdc` for `owner_id`).

## Build & Run Commands

```bash
# Start all services (requires .env with DB_PASSWORD, REDIS_PASSWORD, MINIO_ROOT_USER/PASSWORD)
docker-compose up -d

# Backend only (dev)
cd backend && uvicorn app.main:app --reload --port 8000

# Frontend only (dev)
cd frontend && npm run dev

# DB migrations (the backend container runs `alembic upgrade head` on start)
cd backend && alembic upgrade head
cd backend && alembic revision --autogenerate -m "description"

# Type check / build frontend
cd frontend && npx tsc --noEmit
cd frontend && npm run build

# Backend tests (pytest is not in requirements.txt — install it first)
cd backend && pip install pytest pytest-asyncio && python -m pytest tests/ -v
```

There is no frontend test runner configured — `npm run build` (`tsc -b && vite build`) is the type-safety gate.

## Coding Conventions

### Python (Backend)

- Python 3.11, async/await everywhere; `from __future__ import annotations` in new modules
- FastAPI dependency injection for DB sessions, auth, roles
- Pydantic v2 models with `model_config = {"from_attributes": True}`
- Use `field_validator` for input sanitization (see `_validate_safe_name`)
- Logging with `logger = logging.getLogger(__name__)` — structured `key=value` format, always include `user=` on state-changing ops
- All Redis connections must be closed with `await redis.aclose()` in finally blocks
- Blocking libraries (boto3) go through `asyncio.to_thread`
- No secrets in code — use `app.config.settings` and env vars only

### TypeScript (Frontend)

- React 18 functional components with hooks only
- Zustand for global state (`useConfigStore`, `useMigrationStore`)
- TanStack Query for server state (useQuery/useMutation)
- Tailwind CSS — dark theme (slate-900/950 palette)
- Path alias `@/` maps to `src/`
- `cn()` utility (clsx + tailwind-merge) for conditional classes
- Role checks via `useAuth().roles` and the `RequireRole` wrapper — never rely on hiding UI alone; the backend enforces too

### Terraform / HCL

- Provision templates in `backend/templates/*.tf.j2`; deployment and migration flows have their own subdirectories
- `slug` filter converts names to terraform identifiers: "My Org" → `my_org`; `hcl_escape` filter for interpolated strings
- Provider credentials via `var.vcd_url`, `var.vcd_user`, `var.vcd_password`
- S3 backend (MinIO) for state; migration state key is `migration/{org_slug}/{edge_slug}/terraform.tfstate`

## Agent Delegation

- `/plan` — before implementing any new feature
- `/code-review` — after completing a feature, before committing
- `/security-scan` — after any auth/credentials changes
- `/tdd` — when adding new backend endpoints or core logic

## Security Rules (CRITICAL)

- NEVER hardcode VCD/Keycloak/NSX-T credentials in source code
- NEVER write secrets into HCL files — use `TF_VAR_*` env vars only
- NEVER commit .env files — they are gitignored
- Always validate user input through Pydantic schemas before passing to tf_runner
- Always use `_validate_safe_name()` regex for org/vdc names (prevent path traversal)
- Redis locks must use compare-and-delete (Lua script) for safe release
- WebSocket auth via query parameter token (browsers can't send headers on WS) — and the handler must verify the caller owns the operation or holds `tf-admin`
- Any new terraform output path must pass through `core/redact.py` before storage or publication
- Legacy-VCD API tokens go through `vcd_handle`, never to the browser
- JWT validation enforces `aud == KEYCLOAK_CLIENT_ID`; do not relax `verify_aud`

## Current Status & Roadmap

### Done
- [x] Organization (vcd_org) and VDC (vcd_org_vdc) creation via form
- [x] Edge Gateway, routed network, vApp/VM templates
- [x] Real-time terraform output streaming (plan / apply / destroy)
- [x] Keycloak SSO with RBAC, route guards, `aud` enforcement
- [x] Redis distributed locking + VCD metadata caching
- [x] NSX-V → NSX-T edge migration pipeline (fetch → normalize → generate → plan → apply)
- [x] Deployments as a persisted entity with a structured spec editor
- [x] Deployment HCL plan/apply, orphan state cleanup
- [x] Versioning with MinIO snapshots, pinning, manual snapshots
- [x] Daily drift sync + drift reports + review workflow
- [x] Whole-deployment rollback (prepare → confirm)
- [x] Import of pre-existing VCD edges into management
- [x] Secret redaction at-store and at-stream, hardened compose (no exposed ports, Redis auth)

### Next
- [ ] Operation history (the `operations` table is written to, but there is no read endpoint and no UI)
- [ ] Template save/load (`templates` table exists, no UI)
- [ ] Terraform state viewer
- [ ] Frontend test runner (none configured today)
- [ ] Pin pytest/pytest-asyncio in a dev requirements file
