# E2E Migration Test: ttc-abp-edge

Edge migration test for `ttc-abp-edge` (NSX-V) to NSX-T edge gateway in dev VCD 10.6.

- Source: ttc-abp-edge (legacy VCD 10.4, NSX-V)
- Target: Org=TTC, VDC=test-vdc-01, Edge=cf619cf8-8a59-48aa-bfaa-b316b714a271
- Date: 2026-04-16

## Expected resources

| Type | Count | Details |
|------|-------|---------|
| vcd_nsxt_ip_set | 4 | ipset_internal, ipset_ca0f9ebc, ipset_623dc243, ipset_f31b6dfc |
| data.vcd_nsxt_app_port_profile | 2 | DNS-UDP (SYSTEM), DNS (SYSTEM) |
| vcd_nsxt_firewall | 1 | 3 rule blocks inside |
| vcd_nsxt_edgegateway_static_route | 11 | routes 1-11 |
| **Total resources to add** | **16** | data sources are read-only, not counted |

## Step 1: Prepare workspace

```bash
cd backend/migration_test_workspaces/ttc_abp_edge_20260416/
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — fill in real vcd_url, vcd_user, vcd_password
```

## Step 2: Init

```bash
terraform init
```

Expected: `Terraform has been successfully initialized!`

## Step 3: Validate

```bash
terraform validate
```

Expected: `Success! The configuration is valid.`

If warnings/errors appear, paste the full output into chat for diagnosis.

## Step 4: Plan

```bash
terraform plan -out=plan.bin
```

Expected output summary:
```
Plan: 16 to add, 0 to change, 0 to destroy.
```

Breakdown:
- 4 vcd_nsxt_ip_set
- 1 vcd_nsxt_firewall (contains 3 rule blocks)
- 11 vcd_nsxt_edgegateway_static_route

Review the plan:
```bash
terraform show plan.bin
```

## Step 5: Apply

```bash
terraform apply plan.bin
```

Expected: `Apply complete! Resources: 16 added, 0 changed, 0 destroyed.`

## Step 6: Verification checklist

### A. Firewall rules (VCD 10.6 UI -> Org TTC -> test-vdc-01 -> Edge -> Firewall)

| # | Check | Expected | Result |
|---|-------|----------|--------|
| A1 | Total rule count | Exactly 3 user rules + default rule | [ ] PASS / [ ] FAIL |
| A2 | Rule 1 name | `migrated_137250_dns` | [ ] PASS / [ ] FAIL |
| A3 | Rule 1 source | ipset_internal (3 CIDRs) | [ ] PASS / [ ] FAIL |
| A4 | Rule 1 destination | ipset_ca0f9ebc (4 addresses) | [ ] PASS / [ ] FAIL |
| A5 | Rule 1 services | DNS + DNS-UDP | [ ] PASS / [ ] FAIL |
| A6 | Rule 1 action | ALLOW | [ ] PASS / [ ] FAIL |
| A7 | Rule 2 name | `migrated_rule_133145` | [ ] PASS / [ ] FAIL |
| A8 | Rule 2 source | ipset_623dc243 (4 CIDRs) | [ ] PASS / [ ] FAIL |
| A9 | Rule 2 destination | ANY | [ ] PASS / [ ] FAIL |
| A10 | Rule 2 services | ANY | [ ] PASS / [ ] FAIL |
| A11 | Rule 2 action | ALLOW | [ ] PASS / [ ] FAIL |
| A12 | Rule 3 name | `migrated_rule_137251` | [ ] PASS / [ ] FAIL |
| A13 | Rule 3 source | ANY | [ ] PASS / [ ] FAIL |
| A14 | Rule 3 destination | ipset_f31b6dfc (172.20.10.83/32) | [ ] PASS / [ ] FAIL |
| A15 | Rule 3 services | ANY | [ ] PASS / [ ] FAIL |
| A16 | Rule 3 action | ALLOW | [ ] PASS / [ ] FAIL |
| A17 | Rule order | dns -> 133145 -> 137251 (top to bottom) | [ ] PASS / [ ] FAIL |

### B. IP Sets (VCD 10.6 UI -> Edge -> IP Sets)

| # | Check | Expected | Result |
|---|-------|----------|--------|
| B1 | ipset_internal | 10.127.28.0/28, 10.127.28.64/28, 10.255.255.248/30 | [ ] PASS / [ ] FAIL |
| B2 | ipset_ca0f9ebc | 10.127.28.1, 10.127.28.65, 10.255.255.249, 172.20.10.84 | [ ] PASS / [ ] FAIL |
| B3 | ipset_623dc243 | 10.157.52.0/27, 10.40.40.0/24, 172.20.10.83/32, 172.20.7.60/30 | [ ] PASS / [ ] FAIL |
| B4 | ipset_f31b6dfc | 172.20.10.83/32 | [ ] PASS / [ ] FAIL |
| B5 | Total IP set count | Exactly 4 | [ ] PASS / [ ] FAIL |

### C. App Port Profiles

| # | Check | Expected | Result |
|---|-------|----------|--------|
| C1 | SYSTEM profiles | DNS and DNS-UDP exist in SYSTEM scope (pre-existing) | [ ] PASS / [ ] FAIL |
| C2 | TENANT profiles | No new TENANT profiles created | [ ] PASS / [ ] FAIL |

### D. Static Routes (VCD 10.6 UI -> Edge -> Routing -> Static Routes)

| # | Check | Expected | Result |
|---|-------|----------|--------|
| D1 | Route count | Exactly 11 | [ ] PASS / [ ] FAIL |
| D2 | 10.40.40.0/24 | next_hop=172.20.7.61, admin_distance=1 | [ ] PASS / [ ] FAIL |
| D3 | 10.121.42.0/24 | next_hop=172.22.0.1, admin_distance=1 | [ ] PASS / [ ] FAIL |
| D4 | 10.155.12.0/24 | next_hop=172.20.7.61, admin_distance=1 | [ ] PASS / [ ] FAIL |
| D5 | 10.157.20.0/27 | next_hop=172.22.0.1, admin_distance=1 | [ ] PASS / [ ] FAIL |
| D6 | 10.157.28.0/27 | next_hop=172.22.0.1, admin_distance=1 | [ ] PASS / [ ] FAIL |
| D7 | 10.157.36.0/27 | next_hop=172.22.0.1, admin_distance=1 | [ ] PASS / [ ] FAIL |
| D8 | 10.157.44.0/27 | next_hop=172.22.0.1, admin_distance=1 | [ ] PASS / [ ] FAIL |
| D9 | 10.157.52.0/27 | next_hop=172.22.0.1, admin_distance=1 | [ ] PASS / [ ] FAIL |
| D10 | 10.157.60.0/27 | next_hop=172.22.0.1, admin_distance=1 | [ ] PASS / [ ] FAIL |
| D11 | 10.157.68.0/27 | next_hop=172.22.0.1, admin_distance=1 | [ ] PASS / [ ] FAIL |
| D12 | 172.20.10.72/29 | next_hop=172.20.10.83, admin_distance=1 | [ ] PASS / [ ] FAIL |
| D13 | No default route | 0.0.0.0/0 must NOT be present | [ ] PASS / [ ] FAIL |

### E. Traffic tests (from test VM in internal network)

| # | Test | Expected | Command | Result |
|---|------|----------|---------|--------|
| E1 | DNS to 10.127.28.1 | PASS (rule dns allows UDP/53+TCP/53) | `nslookup example.com 10.127.28.1` | [ ] PASS / [ ] FAIL |
| E2 | HTTP to 10.127.28.1 | BLOCK (dns rule is DNS-only, no other rule matches, default deny) | `curl -m5 http://10.127.28.1` | [ ] PASS / [ ] FAIL |
| E3 | Route via 172.22.0.1 | Uses correct uplink | `traceroute 10.157.28.1` | [ ] PASS / [ ] FAIL |

## Step 7: Rollback

### Clean destroy

```bash
terraform destroy
```

This removes all 16 managed resources (4 IP sets, 1 firewall, 11 static routes).
The edge gateway itself is NOT managed by this workspace and will NOT be affected.

### Important notes

- Any manual changes made via UI after apply will NOT be reverted by destroy
- Destroy only removes resources tracked in terraform.tfstate
- The edge gateway (cf619cf8-...) was created outside terraform and is safe

### State recovery (if state is lost/corrupted)

If terraform.tfstate is lost, import resources back:

```bash
# IP Sets: import by edge_gateway_id.ip_set_id
terraform import vcd_nsxt_ip_set.ipset_3465e8c8 \
  urn:vcloud:gateway:cf619cf8-8a59-48aa-bfaa-b316b714a271.IP_SET_ID

terraform import vcd_nsxt_ip_set.ipset_ca0f9ebc \
  urn:vcloud:gateway:cf619cf8-8a59-48aa-bfaa-b316b714a271.IP_SET_ID

terraform import vcd_nsxt_ip_set.ipset_623dc243 \
  urn:vcloud:gateway:cf619cf8-8a59-48aa-bfaa-b316b714a271.IP_SET_ID

terraform import vcd_nsxt_ip_set.ipset_f31b6dfc \
  urn:vcloud:gateway:cf619cf8-8a59-48aa-bfaa-b316b714a271.IP_SET_ID

# Firewall: import by edge_gateway_id (single resource per edge)
terraform import vcd_nsxt_firewall.migrated \
  urn:vcloud:gateway:cf619cf8-8a59-48aa-bfaa-b316b714a271

# Static routes: import by edge_gateway_id.route_id
terraform import vcd_nsxt_edgegateway_static_route.route_1 \
  urn:vcloud:gateway:cf619cf8-8a59-48aa-bfaa-b316b714a271.ROUTE_ID

# ... repeat for route_2 through route_11
```

To find actual IDs, use VCD API:
```bash
# IP Sets
curl -k -H "Authorization: Bearer $TOKEN" \
  "https://VCD_HOST/cloudapi/1.0.0/edgeGateways/urn:vcloud:gateway:cf619cf8-.../ipSets"

# Static routes
curl -k -H "Authorization: Bearer $TOKEN" \
  "https://VCD_HOST/cloudapi/1.0.0/edgeGateways/urn:vcloud:gateway:cf619cf8-.../routing/staticRoutes"
```
