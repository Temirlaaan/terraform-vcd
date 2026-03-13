# Terraform VCD Dashboard — Claude Code Configuration

## Project Overview

terraform-vcd is a full-stack web dashboard for provisioning VMware Cloud Director infrastructure through Terraform. Users fill out a form, the app generates HCL via Jinja2 templates, then executes `terraform plan` and `terraform apply` with real-time WebSocket streaming.

## Tech Stack

- **Backend**: FastAPI (Python 3.11), async SQLAlchemy + asyncpg, Redis, Jinja2 HCL templates
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, Zustand, TanStack Query
- **Auth**: Keycloak SSO (JWT + JWKS), RBAC with 3 roles (tf-admin, tf-operator, tf-viewer)
- **Infra**: PostgreSQL 15, Redis 7, S3/MinIO (TF state), Terraform 1.7.5 CLI, Docker Compose
- **IaC Target**: VMware VCD (vcd_org, vcd_org_vdc resources via Terraform VCD provider)

## Project Structure

```
terraform-vcd/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI entry point
│   │   ├── config.py               # Pydantic Settings
│   │   ├── database.py             # SQLAlchemy async engine
│   │   ├── api/routes/
│   │   │   ├── terraform.py        # Plan/apply endpoints
│   │   │   ├── metadata.py         # VCD metadata (orgs, pvdcs, storage)
│   │   │   └── ws.py               # WebSocket log streaming
│   │   ├── auth/
│   │   │   ├── keycloak.py         # JWT/JWKS validation
│   │   │   └── rbac.py             # Role-based access
│   │   ├── core/
│   │   │   ├── tf_runner.py        # Terraform CLI subprocess
│   │   │   ├── tf_workspace.py     # Workspace lifecycle
│   │   │   ├── hcl_generator.py    # Jinja2 → HCL rendering
│   │   │   ├── locking.py          # Redis distributed locks
│   │   │   └── cache.py            # Redis cache decorator
│   │   ├── integrations/
│   │   │   └── vcd_client.py       # VCD CloudAPI client
│   │   ├── models/                 # SQLAlchemy models
│   │   └── schemas/                # Pydantic schemas
│   ├── templates/                  # Jinja2 HCL templates (.tf.j2)
│   ├── alembic/                    # DB migrations
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── components/             # Layout, Sidebar, HclPreview, TerminalDrawer
│   │   ├── api/                    # Axios client + React Query hooks
│   │   ├── auth/                   # Keycloak integration
│   │   ├── store/                  # Zustand state
│   │   └── types/                  # TypeScript interfaces
│   └── vite.config.ts
├── docker-compose.yml
└── .env.example
```

## Key Architecture Patterns

- **Credentials safety**: Secrets injected via `TF_VAR_*` env vars, NEVER in HCL files
- **Distributed locking**: Redis `SET NX` per org prevents concurrent terraform ops (409 Conflict)
- **Real-time streaming**: Redis Pub/Sub → WebSocket → Terminal UI for terraform output
- **Async throughout**: FastAPI, httpx, asyncpg, Redis — all non-blocking I/O
- **VCD metadata caching**: Redis TTL 5min via `@cached` decorator
- **RBAC**: tf-admin (full), tf-operator (plan+apply), tf-viewer (read-only)

## Resource Dependency Order

All VCD resources use NSX-T backed variants. Resources must be created in this order:

```
vcd_org → vcd_org_vdc → vcd_nsxt_edgegateway → vcd_network_routed_v2 → vcd_vapp → vcd_vapp_vm → vcd_nsxt_nat_rule → vcd_nsxt_firewall → vcd_nsxt_ip_set
```

Each resource may reference its parent via Terraform data source (e.g., edge gateway uses `data.vcd_org_vdc` for `owner_id`).

## Build & Run Commands

```bash
# Start all services
docker-compose up -d

# Backend only (dev)
cd backend && uvicorn app.main:app --reload --port 8000

# Frontend only (dev)
cd frontend && npm run dev

# DB migrations
cd backend && alembic upgrade head

# Create new migration
cd backend && alembic revision --autogenerate -m "description"

# Type check frontend
cd frontend && npx tsc --noEmit

# Run backend tests
cd backend && python -m pytest tests/ -v

# Run frontend tests
cd frontend && npm test
```

## Coding Conventions

### Python (Backend)

- Python 3.11, async/await everywhere
- FastAPI dependency injection for DB sessions, auth, roles
- Pydantic v2 models with `model_config = {"from_attributes": True}`
- Use `field_validator` for input sanitization (see `_validate_safe_name`)
- Logging with `logger = logging.getLogger(__name__)` — structured key=value format
- All Redis connections must be closed with `await redis.aclose()` in finally blocks
- No secrets in code — use `app.config.settings` and env vars only

### TypeScript (Frontend)

- React 18 functional components with hooks only
- Zustand for global state (useConfigStore)
- TanStack Query for server state (useQuery/useMutation)
- Tailwind CSS for styling — dark theme (slate-900/950 palette)
- Path aliases: `@/` maps to `src/`
- `cn()` utility (clsx + tailwind-merge) for conditional classes

### Terraform / HCL

- Templates in `backend/templates/*.tf.j2`
- `slug` filter converts names to terraform identifiers: "My Org" → "my_org"
- Provider credentials via `var.vcd_url`, `var.vcd_user`, `var.vcd_password`
- S3 backend for state (MinIO)

## Agent Delegation

When to use agents:
- `/plan` — Before implementing any new feature (Edge Gateway, Network, NAT rules)
- `/code-review` — After completing a feature, before committing
- `/security-scan` — After any auth/credentials changes
- `/tdd` — When adding new backend endpoints or core logic

## Security Rules (CRITICAL)

- NEVER hardcode VCD/Keycloak/NSX-T credentials in source code
- NEVER write secrets into HCL files — use TF_VAR_* env vars only
- NEVER commit .env files — they are gitignored
- Always validate user input through Pydantic schemas before passing to tf_runner
- Always use `_validate_safe_name()` regex for org/vdc names (prevent path traversal)
- Redis locks must use compare-and-delete (Lua script) for safe release
- WebSocket auth via query parameter token (browsers can't send headers on WS)

## Current Status & Roadmap

### Done
- [x] Organization (vcd_org) creation via form
- [x] VDC (vcd_org_vdc) creation via form
- [x] Real-time terraform output streaming
- [x] Keycloak SSO with RBAC
- [x] Redis distributed locking
- [x] VCD metadata caching

### Next
- [ ] Edge Gateway (vcd_nsxt_edgegateway) resource ← IN PROGRESS
- [ ] Org VDC Network (vcd_network_routed_v2) resource
- [ ] NAT rules (vcd_nsxt_nat_rule)
- [ ] Firewall rules (vcd_nsxt_firewall)
- [ ] Operation history page
- [ ] Template save/load (DB templates table exists, no UI yet)
- [ ] Destroy operation UI
- [ ] Terraform state viewer
