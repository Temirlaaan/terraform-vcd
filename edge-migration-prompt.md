# Edge Migration Feature — VCD 10.4 NSX-V → VCD 10.6 NSX-T

Add a new "Edge Migration" feature to the existing Terraform VCD Dashboard that
migrates NSX-V edge gateway configurations (firewall, NAT, static routes) from
legacy VCD 10.4 into new NSX-T edges in VCD 10.6, by generating HCL and applying
it via the existing Terraform runner.

## Context

This project already has:

- FastAPI backend at `backend/app/` with Terraform runner, Redis locking,
  PostgreSQL operations history, WebSocket log streaming, Keycloak auth
- React + TypeScript frontend at `frontend/src/` with Service Catalog UI
- Working "Basic Tenant (Org + VDC)" template end-to-end
- Jinja2 HCL generator at `backend/app/core/hcl_generator.py` + `backend/templates/`
- VCD CloudAPI client at `backend/app/integrations/vcd_client.py` (read-only
  metadata, auto-caching with Redis)

**Do NOT reinvent:** reuse `TerraformWorkspace`, `TerraformRunner`, `acquire_org_lock`,
the WebSocket log stream at `/ws/terraform/{operation_id}`, the existing
`vcd_client` metadata client, Keycloak auth via `require_roles`, the existing
shared form components (`FormInput`, `FormSelect`, etc).

## Architecture

Three-layer pipeline inside a new `backend/app/migration/` module:

1. **Fetch** — pull raw XML from legacy VCD 10.4 NSX-V endpoints (via VCD proxy)
2. **Normalize** — parse XML into a canonical JSON schema (source of truth)
3. **Generate** — render HCL via Jinja2 from the normalized JSON

Then the existing Terraform runner takes over: workspace → init → plan → apply
with live log streaming.

## Backend — new module `backend/app/migration/`

### 1. `fetcher.py` — Fetch raw XML from legacy VCD

```python
class LegacyVcdFetcher:
    def __init__(self, host: str, user: str, password: str, api_version: str = "36.3"): ...
    async def login(self) -> None: ...  # POST /cloudapi/1.0.0/sessions/provider
    async def fetch_edge_snapshot(self, edge_uuid: str) -> dict[str, str]: ...
        # Returns: { "edge_metadata.xml": "...", "firewall_config.xml": "...",
        #           "nat_config.xml": "...", "routing_config.xml": "..." }
```

Endpoints to hit (all via VCD proxy):

- `GET /api/admin/edgeGateway/{uuid}` — edge metadata (XML, get interfaces, backing type)
- `GET /network/edges/{uuid}/firewall/config` — full firewall (user + system + default)
- `GET /network/edges/{uuid}/nat/config` — full NAT rules
- `GET /network/edges/{uuid}/routing/config` — static routes + default route

Required headers: `Accept: application/*+xml;version=36.3`, Bearer token from
session login. Use `httpx.AsyncClient(verify=False)` — provider VCD commonly has
self-signed certs.

IPsec and LoadBalancer: **do NOT fetch** — PSK masked in response, Avi migration
is separate concern. Leave placeholder comment for future.

### 2. `normalizer.py` — XML → canonical JSON

Canonical schema (keep stable, HCL generator depends on it):

```json
{
  "schema_version": 1,
  "source": {
    "vcd_host": "vcd01.t-cloud.kz",
    "vcd_version": "10.4",
    "edge_name": "TTC_Telco_EDGE",
    "edge_urn": "urn:vcloud:gateway:b6b3181a-...",
    "backing_type": "NSXV_BACKED",
    "snapshot_at": "2026-04-14T...Z"
  },
  "edge": {
    "name": "TTC_Telco_EDGE",
    "interfaces": [{"name": "Internet", "type": "uplink", "subnets": []}]
  },
  "firewall": {
    "enabled": true,
    "default_action_source": "ALLOW",
    "default_action_target": null,
    "rules": [
      {
        "original_id": "135393",
        "name": "New Rule",
        "rule_type": "user",
        "is_system": false,
        "enabled": true,
        "action": "ALLOW",
        "logging": false,
        "source": {"ip_addresses": [], "grouping_object_ids": [], "vnic_group_ids": [], "exclude": false},
        "destination": {"ip_addresses": [], "grouping_object_ids": [], "vnic_group_ids": [], "exclude": false},
        "application": [{"protocol": "tcp", "port": "443"}]
      }
    ]
  },
  "nat": {
    "enabled": true,
    "rules": [
      {
        "original_id": "200825",
        "action": "DNAT",
        "description": "Access to SSH",
        "enabled": true,
        "logging": false,
        "original_address": "37.208.43.38",
        "translated_address": "10.10.0.19",
        "original_port": "443",
        "translated_port": "443",
        "protocol": "tcp",
        "needs_app_port_profile": true,
        "app_port_profile_key": "tcp_443"
      }
    ],
    "required_app_port_profiles": [
      {
        "key": "tcp_443",
        "protocol": "TCP",
        "ports": "443",
        "is_system_defined": true,
        "system_defined_name": "HTTPS",
        "custom_name": null,
        "used_by_rule_ids": ["200825"]
      },
      {
        "key": "udp_9000-10999",
        "protocol": "UDP",
        "ports": "9000-10999",
        "is_system_defined": false,
        "custom_name": "ttc_nat_udp_9000_10999",
        "used_by_rule_ids": ["233621"]
      }
    ]
  },
  "routing": {
    "static_routes": [
      {
        "network": "10.121.42.0/24",
        "next_hop": "172.24.0.253",
        "mtu": 1500,
        "description": "",
        "admin_distance": 1
      }
    ]
  }
}
```

Key normalization rules:

- `action`: `accept` → `ALLOW`, `deny` → `DROP`
- `rule_type`: `user` → `is_system=false`; `internal_high`, `default_policy` → `is_system=true`
- Dedupe NAT's required app port profiles by `(protocol, port)` tuple
- Known system-defined profiles: `tcp_80=HTTP`, `tcp_443=HTTPS`, `tcp_22=SSH`,
  `udp_53=DNS-UDP`, `tcp_53=DNS`, `tcp_3389=RDP`, `tcp_5060=SIP`, `udp_5060=SIP-UDP`,
  `icmp_any=ICMP ALL` — for the rest generate custom profiles
- Skip `vnic` field from static routes entirely (NSX-T doesn't use it)
- Skip default route (set via edge uplink in target VCD)
- Skip firewall rules with `vnicGroupId` containing `vse` (self-traffic handled
  automatically by NSX-T)

### 3. `generator.py` — normalized JSON → HCL via Jinja2

Use the **same** `jinja2.Environment` pattern as existing `hcl_generator.py`
(with `slug` and `hcl_escape` filters). Templates go in
`backend/templates/migration/`.

Generate into a single workspace:

**`variables.tf.j2`:**

```hcl
variable "vcd_url" { type = string }
variable "vcd_user" { type = string; sensitive = true }
variable "vcd_password" { type = string; sensitive = true }
variable "target_org" { type = string; default = "{{ target_org_name }}" }
variable "target_vdc" { type = string; default = "{{ target_vdc_name }}" }
variable "target_edge_id" { type = string; default = "{{ target_edge_id }}" }
```

**`app_port_profiles.tf.j2`** — one block per required profile:

```hcl
{% for prof in nat.required_app_port_profiles %}
{% if prof.is_system_defined %}
data "vcd_nsxt_app_port_profile" "{{ prof.key | slug }}" {
  name  = "{{ prof.system_defined_name }}"
  scope = "SYSTEM"
}
{% else %}
resource "vcd_nsxt_app_port_profile" "{{ prof.key | slug }}" {
  name        = "{{ prof.custom_name }}"
  scope       = "TENANT"
  org         = var.target_org
  context_id  = var.target_edge_id
  description = "Migrated from VCD 10.4, used by rules: {{ prof.used_by_rule_ids | join(', ') }}"
  app_port {
    protocol = "{{ prof.protocol }}"
    port     = ["{{ prof.ports }}"]
  }
}
{% endif %}
{% endfor %}
```

**`firewall.tf.j2`** — single `vcd_nsxt_firewall` block with all user rules
(skip `is_system=true`). Map fields as:

- source.ip_addresses → `source_ids` wrapped as `vcd_nsxt_ip_set` (or use
  `source_ids = []` with inline IPs when simple — check VCD provider 3.12 docs)
- For MVP: use dynamic `vcd_nsxt_ip_set` resources for source/destination
  when `len(ip_addresses) > 0`

**`nat.tf.j2`** — one `vcd_nsxt_nat_rule` per rule:

```hcl
{% for rule in nat.rules if rule.enabled %}
resource "vcd_nsxt_nat_rule" "rule_{{ rule.original_id }}" {
  org               = var.target_org
  edge_gateway_id   = var.target_edge_id
  name              = "{{ rule.description or 'rule_' + rule.original_id }}"
  rule_type         = "{{ rule.action }}"
  external_address  = "{{ rule.original_address if rule.action == 'DNAT' else rule.translated_address }}"
  internal_address  = "{{ rule.translated_address if rule.action == 'DNAT' else rule.original_address }}"
  {% if rule.action == 'DNAT' and rule.translated_port and rule.translated_port != 'any' %}
  dnat_external_port = "{{ rule.original_port }}"
  {% endif %}
  {% if rule.needs_app_port_profile %}
  app_port_profile_id = {% if rule.is_system_profile %}data{% else %}resource{% endif %}.vcd_nsxt_app_port_profile.{{ rule.app_port_profile_key | slug }}.id
  {% endif %}
  logging = {{ rule.logging | lower }}
  enabled = {{ rule.enabled | lower }}
  {% if rule.description %}description = "{{ rule.description | hcl_escape }}"{% endif %}
}
{% endfor %}
```

**`static_routes.tf.j2`** — per-route `vcd_nsxt_edgegateway_static_route`:

```hcl
{% for route in routing.static_routes %}
resource "vcd_nsxt_edgegateway_static_route" "route_{{ loop.index }}" {
  edge_gateway_id = var.target_edge_id
  name            = "migrated_route_{{ loop.index }}"
  description     = "{{ route.description | default('') | hcl_escape }}"
  network_cidr    = "{{ route.network }}"
  next_hop {
    ip_address     = "{{ route.next_hop }}"
    admin_distance = {{ route.admin_distance | default(1) }}
  }
}
{% endfor %}
```

### 4. `models.py` — Pydantic schemas

```python
class MigrationFetchRequest(BaseModel):
    source_vcd_host: str       # vcd01.t-cloud.kz
    source_user: str
    source_password: str
    source_edge_uuid: str      # e.g. b6b3181a-...

class MigrationGenerateRequest(BaseModel):
    normalized_json: dict
    target_org_name: str
    target_vdc_name: str
    target_edge_id: str        # urn:vcloud:gateway:... in VCD 10.6

class MigrationApplyRequest(BaseModel):
    migration_id: UUID
```

### 5. DB model — `migration.py`

New table `migrations`:

- id (UUID), source_vcd_host, source_edge_uuid, source_edge_name
- target_org_name, target_vdc_name, target_edge_id
- status enum: FETCHED, GENERATED, APPLIED, FAILED
- normalized_json (JSONB), generated_hcl (TEXT)
- created_by, created_at
- plan_operation_id, apply_operation_id (FK to operations.id, nullable)

Alembic migration: `backend/alembic/versions/0003_create_migrations_table.py`.

### 6. Routes — `backend/app/api/routes/migration.py`

```
POST /api/v1/migration/fetch        → returns normalized JSON + warnings
POST /api/v1/migration/generate     → stores migration record, returns HCL preview
POST /api/v1/migration/apply        → creates workspace, runs plan, returns operation_id
GET  /api/v1/migration              → list all migrations (with filtering)
GET  /api/v1/migration/{id}         → get single migration
```

All endpoints guarded by `require_roles("tf-admin", "tf-operator")` except GET
which allows `tf-viewer` too. Register router in `backend/app/main.py`.

**Apply flow** — reuse `TerraformWorkspace` pattern from
`backend/app/api/routes/terraform.py` (see `_run_plan_task`):

1. Create workspace directory
2. Render ALL generated `.tf` files + base provider block (reuse `base.tf.j2`)
   into `main.tf` or split files
3. Acquire Redis lock on `target_org_name`
4. Background task: `terraform init` → `terraform plan` → update operation record
5. WebSocket log channel works out of the box via existing `log_channel(operation_id)`

The Apply endpoint here should do plan+apply in sequence since the whole
migration is one unit (unlike the catalog flow where plan/apply are separate user
actions). Or do plan first, return operation_id, and have a separate
`/api/v1/migration/{id}/confirm-apply` that runs apply — both are valid, pick
plan-then-wait-for-confirm for safety.

## Frontend — new pages

### 1. New Service Catalog card

Edit `frontend/src/pages/CatalogPage.tsx` — add a fourth card:

```tsx
{
  title: "Edge Migration (NSX-V → NSX-T)",
  description: "Migrate firewall, NAT, and static routes from a VCD 10.4 NSX-V edge gateway into a new NSX-T edge in VCD 10.6.",
  icons: [Shield, ArrowRightLeft],
  badge: "Migration",
  to: "/migration",
}
```

### 2. `frontend/src/pages/MigrationPage.tsx`

Two-step wizard, similar layout to `ProvisionPage.tsx` (left form, right
preview):

**Step 1 — Source:**

- Source VCD host (text input, default `vcd01.t-cloud.kz`)
- Source user (text)
- Source password (password input)
- Source edge UUID (text, placeholder = `b6b3181a-2596-44c5-9991-c4c54c050bcb`)
- Button: `Fetch & Analyze`

On click → POST `/api/v1/migration/fetch` → show analysis:

- Edge name (`TTC_Telco_EDGE`)
- Count: "14 firewall rules (12 user + 2 system, 2 will be skipped)"
- Count: "29 NAT rules requiring 14 app port profiles (6 system-defined, 8 custom)"
- Count: "5 static routes"
- Warnings list (if any)

**Step 2 — Target (dropdowns populated from existing metadata hooks):**

- Target Organization — dropdown using `useOrganizations()`
- Target VDC — dropdown using `useVdcs(org)` (cascaded)
- Target Edge Gateway — dropdown using `useEdgeGateways(org, vdc)`,
  filtered to `gateway_type === 'NSXT_BACKED'`
- (Read-only display:) External IP that will be preserved: `37.208.43.38`
- Button: `Preview HCL` → POST `/api/v1/migration/generate`

**Step 3 — Preview + Apply:**

- Right panel shows generated HCL (reuse the syntax-highlighting pattern from
  `HclPreview.tsx`, but fed from API response not client-side generation)
- Bottom action bar: `Run Plan` button → POST `/api/v1/migration/apply`
  (plan mode) → `operation_id` → open `TerminalDrawer` with WebSocket stream
  (reuse existing component)
- After plan succeeds, show `Confirm Apply` button

### 3. API hooks — extend `frontend/src/api/hooks.ts`

```typescript
export function useMigrationFetch() { /* useMutation for POST /migration/fetch */ }
export function useMigrationGenerate() { /* useMutation for POST /migration/generate */ }
export function useMigrationApply() { /* useMutation for POST /migration/apply */ }
export function useMigrations() { /* useQuery for GET /migration */ }
```

### 4. Zustand store — `frontend/src/store/useMigrationStore.ts`

Separate from `useConfigStore` (different domain). Holds:

- Source credentials (not persisted!)
- Normalized analysis result
- Target selections
- Current migration ID
- Generated HCL

## Testing

Add tests under `backend/tests/`:

- `test_migration_normalizer.py` — parse sample XMLs (use the 4 XML strings from
  the requirements spec below as fixtures), assert JSON structure
- `test_migration_generator.py` — take a normalized JSON, assert generated HCL
  contains expected resources, no legacy fields, proper app port profile dedup
- `test_migration_routes.py` — mock VCD HTTP, test endpoint auth & flow

## Reference Data for Fixtures

Use actual data from `TTC_Telco_EDGE` (edge UUID
`b6b3181a-2596-44c5-9991-c4c54c050bcb`). Sample fixtures should include:

**Firewall sample** (ID 135393, user rule with multiple IPs in source):

```xml
<firewallRule>
  <id>135393</id><name>New Rule</name><ruleType>user</ruleType>
  <enabled>true</enabled><loggingEnabled>false</loggingEnabled><action>accept</action>
  <source>
    <exclude>false</exclude>
    <ipAddress>10.121.24.3/32</ipAddress>
    <ipAddress>10.121.44.0/24</ipAddress>
    <ipAddress>10.121.43.0/24</ipAddress>
  </source>
</firewallRule>
```

**NAT port range sample** (ID 233621, 3cx-rtp):

```xml
<natRule>
  <ruleId>233621</ruleId><description>3cx-rtp</description>
  <ruleType>user</ruleType><action>dnat</action><enabled>true</enabled>
  <originalAddress>37.208.43.84</originalAddress>
  <translatedAddress>10.121.10.18</translatedAddress>
  <originalPort>9000-10999</originalPort>
  <translatedPort>9000-10999</translatedPort>
  <protocol>udp</protocol>
</natRule>
```

Static route sample (5 routes all via vnic 2 → strip vnic, keep rest).

## Deliverables Checklist

- [ ] `backend/app/migration/{__init__,fetcher,normalizer,generator,models,routes}.py`
- [ ] `backend/app/models/migration.py` (SQLAlchemy model)
- [ ] `backend/alembic/versions/0003_create_migrations_table.py`
- [ ] `backend/templates/migration/{app_port_profiles,firewall,nat,static_routes,variables}.tf.j2`
- [ ] Router registered in `backend/app/main.py`
- [ ] Tests in `backend/tests/test_migration_*.py`
- [ ] Frontend: `MigrationPage.tsx`, `useMigrationStore.ts`, new catalog card, hooks
- [ ] Wire `/migration` route in `frontend/src/App.tsx`

## Non-Goals / Out of Scope

- Migrating IPsec VPN (PSK is masked in legacy API)
- Migrating Load Balancer (NSX-V native LB → Avi in NSX-T is a separate tool)
- Creating the target NSX-T edge itself (user creates it in VCD 10.6 beforehand,
  then selects it from the dropdown)
- Migrating VMs or Org VDC networks (out of scope for this feature)
- OSPF/BGP routing (only static routes)
- Default route migration (set via edge uplink at edge creation time)

## Constraints

- Python 3.11, FastAPI, SQLAlchemy 2.0 async, Pydantic v2
- React 18, TypeScript strict, Tailwind (reuse `clr-*` design tokens)
- No new dependencies beyond `httpx` (already in `requirements.txt`) —
  use stdlib `xml.etree.ElementTree` for XML parsing
- Follow existing code style: no emojis, type hints everywhere in Python,
  `const` in TypeScript, no `any`
- SSL verification disabled for legacy VCD connection only (self-signed certs
  are common in customer VCDs)
- Provider credentials for target VCD come from the existing `TF_VAR_*` env
  injection in `tf_runner.py` — do NOT add them to the generated HCL literally
