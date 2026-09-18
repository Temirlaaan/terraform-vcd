# Terraform VCD Dashboard — Project Overview

## What Is This Project?

**terraform-vcd** is a full-stack web application that puts a graphical UI in front of **VMware Cloud Director (VCD)** infrastructure managed by **Terraform**. It started as a provisioning form ("fill in org + VDC, get HCL, run apply") and has grown into a lifecycle tool: it migrates legacy NSX-V edge gateways to NSX-T, keeps the resulting configuration as a versioned **deployment**, watches for drift against VCD reality, and can roll a deployment back to an earlier version.

Nobody on the team writes the HCL by hand. The dashboard generates it, runs Terraform against an S3 state backend, streams the output live, and stores a snapshot of every apply.

## Architecture

```
┌──────────────┐        ┌───────────────────────────┐        ┌──────────────┐
│  Frontend    │──HTTP─▶│  Backend (FastAPI)        │──API──▶│  VCD         │
│  React + TS  │        │                           │        │  (CloudAPI)  │
│  Vite        │◀──WS───│  routers ──┬── tf_runner ─┼──exec─▶ terraform CLI │
│  Zustand     │        │            ├── migration  │        └──────┬───────┘
│  TanStack    │        │            ├── versions   │               │
└──────────────┘        │            ├── drift      │        ┌──────▼───────┐
                        │            └── rollback   │        │ VCD Provider │
                        └──────┬────────────────────┘        │ (NSX-T res.) │
                               │                             └──────────────┘
          ┌────────────────────┼────────────────────┐
          │                    │                    │
   ┌──────▼──────┐     ┌───────▼───────┐    ┌───────▼────────┐
   │ PostgreSQL  │     │     Redis     │    │     MinIO      │
   │ operations  │     │ locks, cache, │    │ TF state (S3   │
   │ deployments │     │ pub/sub, VCD  │    │ backend) +     │
   │ versions    │     │ token handles │    │ version        │
   │ drift       │     └───────────────┘    │ snapshots      │
   └─────────────┘                          └────────────────┘
```

Six containers via Docker Compose: `postgres`, `redis`, `minio`, `minio-init` (one-shot bucket creation), `backend`, `frontend`. The frontend container is a multi-stage build — Node compiles the bundle, nginx serves it. A host-level nginx config lives in `deploy/nginx/tf-dashboard.conf`; backend and frontend also join an external `proxy-network`.

## Tech Stack

| Layer    | Technology                                                                          |
| -------- | ----------------------------------------------------------------------------------- |
| Frontend | React 18, TypeScript 5.7, Vite 6, Tailwind CSS, Zustand, TanStack Query, react-router 7 |
| Backend  | FastAPI, Python 3.11, async SQLAlchemy 2, asyncpg, httpx, Jinja2, boto3, APScheduler  |
| Auth     | Keycloak SSO (JWT + JWKS, audience enforced), RBAC with 3 realm roles                 |
| Infra    | PostgreSQL 15, Redis 7, MinIO (S3), Terraform 1.7.5 CLI, nginx, Docker Compose        |

## The Four Flows

### 1. Provision (`/provision`)

The original flow. A form collects org and VDC settings; `POST /api/v1/terraform/generate` renders Jinja2 templates into HCL; `plan`, `apply` and `destroy` run the Terraform CLI with output streamed to a terminal drawer. Templates exist for `vcd_org`, `vcd_org_vdc`, `vcd_nsxt_edgegateway`, `vcd_network_routed_v2`, `vcd_vapp` and `vcd_vapp_vm`.

Requires `tf-admin` or `tf-operator`. Viewers never see the Service Catalog.

### 2. Migration — NSX-V → NSX-T (`/migration`)

Moves an edge gateway from a legacy VCD (NSX-V backed) to a modern NSX-T edge, config and all.

1. An admin supplies the legacy VCD host and an API token. `POST /migration/auth-handle` stores the pair in Redis behind a short-lived opaque UUID — the token itself never reaches browser storage.
2. `migration/fetcher.py` pulls the raw edge XML from the legacy VCD.
3. `migration/normalizer.py` turns it into canonical JSON (parsed with `defusedxml`).
4. `migration/generator.py` renders that JSON into NSX-T HCL — app port profiles, NAT rules, firewall rules with IP sets, static routes — against the chosen target org/VDC/edge.
5. `GET /migration/target-check` warns if the target edge already carries conflicting config; `POST /migration/plan` and `/apply` execute it.
6. The result can be saved as a deployment.

NSX-V and NSX-T model NAT differently, and the generator handles the mapping (for DNAT, NSX-V's `original_address` becomes `external_address`; for SNAT it becomes `internal_address`).

### 3. Deployments (`/deployments`)

A **deployment** is a persisted, managed edge configuration. It carries the source it was migrated or imported from, the target org/VDC/edge, the generated HCL, and a summary.

- List, detail and editor pages. The editor works on a structured `DeploymentSpec` (IP sets, app port profiles, firewall rules, NAT rules, static routes) rather than raw text.
- `PUT /deployments/{id}/spec` rebuilds the HCL from the spec; `deployment_state_align.py` re-maps Terraform state addresses so a rebuild does not destroy and recreate resources.
- `GET /deployments/{id}/editor-data` and `deployment_spec_from_state.py` recover a spec from existing state, so imported edges are editable too.
- `POST /deployments/{id}/plan` and `/apply` run Terraform for that deployment; `tf_import.py` resolves pre-apply conflicts by importing resources that already exist in VCD.
- `GET|POST /deployments/{id}/state/…orphans` finds and cleans state entries whose VCD resource is gone.

Reading is open to all three roles; writing needs `tf-admin` or `tf-operator`.

### 4. Lifecycle — versions, drift, rollback, import

**Versions.** Every apply snapshots the HCL and state into MinIO under `deployments/<id>/v<N>/`. `state_hash.py` canonicalizes the state so an apply that changed nothing does not create a version. Access narrows as the data gets more sensitive: any role can list versions, writers can fetch a version's HCL, and only admins can download raw state or pin, unpin and create named snapshots.

**Drift.** An APScheduler job runs daily (default 03:00 `Asia/Almaty`) over every deployment: it plans against live VCD, classifies the result via `plan_parser.py` into additions / modifications / deletions, and writes a `DriftReport`. `drift_importer.py` can adopt unmanaged resources it finds. Deployments with drift get `needs_review = true`; a reviewer resolves the report, optionally promoting the drifted state into the deployment's HCL. Drift checks can also be triggered manually.

**Rollback.** Admin-only, two-phase: `POST /deployments/{id}/rollback/prepare` restores an old version into a workspace and produces a plan; `.../rollback/{prepare_op_id}/confirm` applies it. Nothing is applied without a human looking at the plan first.

**Import.** `GET /deployments/available-edges` lists NSX-T edges in VCD that the dashboard does not manage; an admin can import one, and the backend reconstructs a deployment (HCL + state + spec) from what is actually deployed.

## Roles

Three Keycloak realm roles, mapped from Active Directory groups:

| Role | Can do |
|---|---|
| `tf-viewer` | Read metadata, deployments, versions, drift reports |
| `tf-operator` | Everything a viewer can, plus plan / apply / destroy, edit deployments, run migrations, read deployment and version HCL, trigger drift checks |
| `tf-admin` | Everything, plus raw state download, pin / unpin versions, named snapshots, import existing edges, rollback, Settings |

The frontend hides what a role cannot use (`RequireRole`, conditional nav), and every endpoint enforces the same rule server-side.

## What Are the VCD Credentials For?

Two distinct credentials, for two purposes:

**`VCD_API_TOKEN`** — used by `VCDClient` (`backend/app/integrations/vcd_client.py`) against the VCD CloudAPI to populate form dropdowns: organizations, provider VDCs, VDCs, storage profiles, edge gateways, edge clusters, network pools and external networks. Results are cached in Redis for 5 minutes.

**`VCD_USER` / `VCD_PASSWORD`** — injected as `TF_VAR_vcd_user` / `TF_VAR_vcd_password` so the Terraform VCD provider can authenticate during plan and apply:

```hcl
provider "vcd" {
  url      = var.vcd_url
  user     = var.vcd_user      # from TF_VAR_vcd_user
  password = var.vcd_password  # from TF_VAR_vcd_password
  sysorg   = "System"
  org      = var.target_org
}
```

Neither value is ever written into an HCL file.

Legacy-VCD migration tokens are a third, separate thing: supplied per session by the operator, held only in Redis behind a handle, and never persisted.

## Security Posture

- **Secrets out of HCL** — credentials travel as `TF_VAR_*` environment variables only.
- **Redaction twice over** — `core/redact.py` strips AWS keys, `password=` / `secret=` pairs, bearer headers and URL-embedded basic-auth. It runs on a SQLAlchemy event hook before operation rows are written, and again in the streaming path so live WebSocket subscribers see the same redacted text.
- **WebSocket authorization** — browsers cannot set headers on a WS handshake, so the token arrives as a query parameter; the handler then checks the caller owns the operation or holds `tf-admin`.
- **JWT audience enforced** — tokens must carry `aud == KEYCLOAK_CLIENT_ID`.
- **CORS is explicit** — `*`, `null` and wildcard subdomains are rejected at config parse time.
- **`AUTH_DISABLED` guardrail** — the dev bypass refuses to start unless `TF_ENV=dev` and `DASHBOARD_HOSTNAME` is a localhost address; the frontend shows a warning banner when it is on.
- **Hardened infrastructure** — no database, Redis or MinIO ports published to the host; Redis requires a password and has `FLUSHALL`, `CONFIG` and `DEBUG` renamed away; required secrets fail the compose run if unset rather than defaulting.
- **Distributed locking** — a Redis `SET NX` lock per org (10-minute TTL, released via a compare-and-delete Lua script) means two people cannot run Terraform against the same org at once; the second gets a 409.
- **Attribution** — `aria_attribution.py` writes the acting Keycloak username into VCD resource descriptions, so the VCD-side audit trail names a person rather than the service account.

## Data Model

| Table | Holds |
|---|---|
| `operations` | Every plan / apply / destroy / rollback: type, status, user, target org, output, error, optional deployment link |
| `deployments` | Managed edge configs: source host + edge UUID, target org/VDC/edge, HCL, summary, `needs_review`, `last_drift_check` |
| `deployment_versions` | Per-deployment version rows: `version_num`, `state_hash`, MinIO keys for HCL and state, source, label, pin flag |
| `drift_reports` | Drift run results: additions / modifications / deletions as JSONB, reviewer, resolution, linked version |
| `templates` | Saved form configurations (table exists; no UI yet) |

Migrations live in `backend/alembic/versions/` (`0001` operations + templates, `0002` operation indexes, `0003` deployments). The backend container runs `alembic upgrade head` on start; `main.py` additionally calls `Base.metadata.create_all` at startup as a safety net.

## Getting Started

```bash
cp .env.example .env     # then fill in the required secrets
docker-compose up -d
```

`DB_PASSWORD`, `REDIS_PASSWORD`, `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` have no defaults — compose refuses to start without them.

For local development, run the backend with `uvicorn app.main:app --reload --port 8000` and the frontend with `npm run dev`. Backend tests need pytest installed separately (`pip install pytest pytest-asyncio`, then `python -m pytest tests/ -v`); there is no frontend test runner, so `npm run build` is the type-safety gate.

## Known Gaps

- The `operations` table is written on every Terraform run, but nothing reads it back — there is no list endpoint and no history page.
- The `templates` table exists with no endpoint and no save/load UI.
- No Terraform state viewer.
- `pytest` and `pytest-asyncio` are not pinned in `requirements.txt`.
- No frontend test framework is configured.
- `frontend/src/main.tsx.bak` is a stray backup file checked into the repo.
