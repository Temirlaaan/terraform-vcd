# Terraform VCD Dashboard — Project Overview

## What Is This Project?

**terraform-vcd** is a full-stack web application (dashboard) that provides a graphical UI for creating and managing **VMware Cloud Director (VCD)** infrastructure through **Terraform**. Instead of writing Terraform HCL files by hand, users fill out a form in the browser, the app generates the HCL code, and then executes `terraform plan` and `terraform apply` with real-time output streaming.

## Architecture

```
┌─────────────┐    ┌──────────────────┐    ┌──────────────┐
│  Frontend    │───▶│  Backend (API)   │───▶│  VCD API     │
│  React + TS  │    │  FastAPI/Python  │    │  (metadata)  │
│  Vite        │    │                  │    └──────────────┘
│  Zustand     │◀──▶│  TerraformRunner │───▶ terraform CLI
│  TanStack    │ WS │  HCL Generator   │       │
└─────────────┘    │  Redis Pub/Sub   │    ┌───▼──────────┐
                   └────────┬─────────┘    │ VCD Provider │
                            │              │ (create org, │
                   ┌────────▼─────────┐    │  VDC, etc.)  │
                   │  PostgreSQL      │    └──────────────┘
                   │  Redis           │
                   │  S3 (TF state)   │
                   └──────────────────┘
```

Four containers via Docker Compose: PostgreSQL, Redis, Backend, Frontend.

## Tech Stack

| Layer    | Technology                                                       |
| -------- | ---------------------------------------------------------------- |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Zustand, TanStack Query |
| Backend  | FastAPI, Python 3.11, async SQLAlchemy, httpx, Jinja2            |
| Auth     | Keycloak SSO (JWT + JWKS), RBAC with 3 roles                    |
| Infra    | PostgreSQL, Redis, S3/MinIO (TF state), Terraform 1.7.5 CLI     |

## Project Structure

```
terraform-vcd/
├── docker-compose.yml              # Multi-container orchestration
├── backend/
│   ├── Dockerfile                  # Python 3.11 + Terraform 1.7.5
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py                 # FastAPI app entry point
│   │   ├── config.py               # Environment settings
│   │   ├── database.py             # SQLAlchemy async setup
│   │   ├── api/routes/
│   │   │   ├── terraform.py        # Plan/apply endpoints
│   │   │   ├── metadata.py         # VCD metadata endpoints
│   │   │   └── ws.py               # WebSocket streaming
│   │   ├── auth/
│   │   │   ├── keycloak.py         # JWT validation
│   │   │   └── rbac.py             # Role-based access control
│   │   ├── models/                 # SQLAlchemy DB models
│   │   ├── schemas/                # Pydantic request/response schemas
│   │   ├── core/
│   │   │   ├── tf_runner.py        # Terraform CLI executor
│   │   │   ├── tf_workspace.py     # Workspace management
│   │   │   ├── hcl_generator.py    # Jinja2 HCL generation
│   │   │   ├── locking.py          # Redis distributed locks
│   │   │   └── cache.py            # Redis caching decorator
│   │   └── integrations/
│   │       └── vcd_client.py       # VCD REST API client
│   ├── templates/                  # Jinja2 HCL templates
│   │   ├── base.tf.j2              # Provider & backend config
│   │   ├── organization.tf.j2     # vcd_org resource
│   │   └── vdc.tf.j2              # vcd_org_vdc resource
│   └── alembic/                    # DB migrations
├── frontend/
│   ├── Dockerfile                  # Node 20 Alpine
│   ├── src/
│   │   ├── App.tsx                 # Root component
│   │   ├── components/
│   │   │   ├── Layout.tsx          # Main layout (sidebar + preview)
│   │   │   ├── Sidebar.tsx         # Configuration form
│   │   │   ├── HclPreview.tsx      # Generated HCL viewer
│   │   │   └── TerminalDrawer.tsx  # Real-time operation output
│   │   ├── auth/                   # Keycloak integration
│   │   ├── api/                    # Axios client + React Query hooks
│   │   ├── store/                  # Zustand state management
│   │   └── types/                  # TypeScript interfaces
│   └── vite.config.ts
```

## Managed VCD Resources

The app generates Terraform HCL for:

1. **`vcd_org`** — Organizations (name, description, enabled/disabled)
2. **`vcd_org_vdc`** — Virtual Data Centers (CPU/memory allocation, storage profiles, network pool, provisioning options)

## What Is the VCD API User For?

The VCD API service account (`terraform-svc`, configured via `VCD_USER` / `VCD_PASSWORD` env vars) serves two purposes:

### 1. Backend Metadata Queries (Read-Only)

The `VCDClient` (`backend/app/integrations/vcd_client.py`) authenticates against the VCD REST API and fetches metadata to populate the frontend form dropdowns:

- Organizations list
- Provider VDCs (physical resource pools)
- Virtual Data Centers (per-org)
- Storage Profiles (per-PVDC)
- Edge Gateways (per-org/vdc)
- External Networks

Results are cached in Redis for 5 minutes.

### 2. Terraform Provider Authentication

The same credentials are injected as `TF_VAR_vcd_user` / `TF_VAR_vcd_password` environment variables so the Terraform VCD provider can authenticate when running plan/apply:

```hcl
provider "vcd" {
  url      = var.vcd_url
  user     = var.vcd_user      # from TF_VAR_vcd_user
  password = var.vcd_password  # from TF_VAR_vcd_password
  org      = "System"
}
```

## End-to-End Logic Flow

1. **Authenticate** — User logs in via Keycloak SSO; JWT token attached to all API calls.
2. **Load Metadata** — Frontend fetches VCD metadata (`/api/v1/metadata/*`) to populate form dropdowns.
3. **Build Config** — User fills out the form (org name, VDC settings, storage profiles, etc.).
4. **Generate HCL** — POST `/api/v1/terraform/generate` → Jinja2 templates render HCL → displayed in preview panel.
5. **Plan** — POST `/api/v1/terraform/plan`:
   - Acquires a Redis distributed lock per org (`tf:lock:org:{name}`).
   - Creates workspace in `/tmp/tf-workspaces/{org}/{operation_id}/`.
   - Runs `terraform init` then `terraform plan -out=plan.bin`.
   - Streams output via Redis Pub/Sub → WebSocket → Terminal UI.
   - Records operation in PostgreSQL (status, output, errors).
6. **Apply** — POST `/api/v1/terraform/apply`:
   - Reuses the plan workspace, runs `terraform apply plan.bin`.
   - Same streaming and DB tracking pattern.

## Key Design Patterns

- **Separation of concerns**: Form state → HCL generation → Terraform execution → DB tracking
- **Async throughout**: FastAPI, httpx, asyncpg, Redis — all non-blocking I/O
- **Distributed locking**: Redis `SET NX` with 10-min TTL prevents concurrent operations on the same org (409 Conflict)
- **Real-time streaming**: Redis Pub/Sub + WebSocket for live Terraform log output
- **Credentials safety**: Secrets injected via `TF_VAR_*` env vars, never written into HCL files
- **RBAC**: Three roles — `tf-admin` (full), `tf-operator` (plan + apply), `tf-viewer` (read-only)
- **Caching**: VCD metadata cached 5 min in Redis to avoid excessive API calls

## Notes

- NSX-T and vSphere credentials are configured in `config.py` but not yet used in templates (placeholders for future expansion).
- Terraform state is stored in an S3-compatible backend (MinIO), not locally.
- The `HCLGenerator` uses a Jinja2 `slug` filter to convert human-readable names to valid Terraform identifiers (e.g., "My Org (prod)" → `my_org_prod`).
