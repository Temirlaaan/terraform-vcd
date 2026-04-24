"""Pre-apply conflict resolution via terraform import.

Before `terraform plan`, scans the rendered HCL, queries VCD for existing
resources with matching names/CIDRs, and imports them into Terraform state.

vmware/vcd provider import ID formats:
  vcd_nsxt_edgegateway_static_route: org.vdc.edge.route_name
  vcd_nsxt_ip_set:                   org.vdc-or-group.edge.ip_set_name
  vcd_nsxt_nat_rule:                 org.vdc-or-group.edge.rule_name
  vcd_nsxt_app_port_profile:         org.profile_name (TENANT scope)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.tf_runner import TerraformRunner
from app.integrations.vcd_client import vcd_client

logger = logging.getLogger(__name__)


@dataclass
class HclResource:
    tf_type: str
    tf_label: str
    vcd_name: str | None
    network_cidr: str | None = None

    @property
    def address(self) -> str:
        return f"{self.tf_type}.{self.tf_label}"


_IMPORTABLE_TYPES = {
    "vcd_nsxt_ip_set",
    "vcd_nsxt_app_port_profile",
    "vcd_nsxt_edgegateway_static_route",
    "vcd_nsxt_nat_rule",
}

_RESOURCE_RE = re.compile(
    r'resource\s+"(?P<type>[^"]+)"\s+"(?P<label>[^"]+)"\s*\{(?P<body>[^{}]*(?:\{[^{}]*\}[^{}]*)*)\}',
    re.DOTALL,
)
_NAME_RE = re.compile(r'^\s*name\s*=\s*"([^"]+)"', re.MULTILINE)
_CIDR_RE = re.compile(r'^\s*network_cidr\s*=\s*"([^"]+)"', re.MULTILINE)
_VAR_DEFAULT_RE = re.compile(
    r'variable\s+"(?P<name>[^"]+)"\s*\{[^}]*default\s*=\s*"(?P<val>[^"]+)"',
    re.DOTALL,
)


def parse_hcl_resources(hcl: str) -> list[HclResource]:
    results: list[HclResource] = []
    for m in _RESOURCE_RE.finditer(hcl):
        tf_type = m.group("type")
        if tf_type not in _IMPORTABLE_TYPES:
            continue
        body = m.group("body")
        name_m = _NAME_RE.search(body)
        cidr_m = _CIDR_RE.search(body)
        results.append(
            HclResource(
                tf_type=tf_type,
                tf_label=m.group("label"),
                vcd_name=name_m.group(1) if name_m else None,
                network_cidr=cidr_m.group(1) if cidr_m else None,
            )
        )
    return results


def parse_hcl_var_defaults(hcl: str) -> dict[str, str]:
    return {m.group("name"): m.group("val") for m in _VAR_DEFAULT_RE.finditer(hcl)}


# ------------------------------------------------------------------
# VCD listings
# ------------------------------------------------------------------

async def _list_ip_sets(edge_id: str) -> list[dict]:
    params = {"filter": f"(edgeGatewayId=={edge_id};typeValue==IP_SET)"}
    try:
        return await vcd_client._get_paginated(  # type: ignore[attr-defined]
            "/cloudapi/1.0.0/firewallGroups/summaries", params=params
        )
    except Exception as exc:
        logger.warning("IP sets list failed: %s", exc)
        return []


async def _list_app_port_profiles(org_name: str) -> list[dict]:
    params = {"filter": f"(scope==TENANT)"}
    try:
        items = await vcd_client._get_paginated(  # type: ignore[attr-defined]
            "/cloudapi/1.0.0/applicationPortProfiles", params=params
        )
    except Exception as exc:
        logger.warning("Port profiles list failed: %s", exc)
        return []
    out = []
    for p in items:
        org_ref = p.get("orgRef") or {}
        if org_ref.get("name") == org_name:
            out.append(p)
    return out


async def _list_static_routes(edge_id: str) -> list[dict]:
    try:
        return await vcd_client._get_paginated(  # type: ignore[attr-defined]
            f"/cloudapi/1.0.0/edgeGateways/{edge_id}/routing/staticRoutes"
        )
    except Exception as exc:
        logger.warning("Static routes list failed: %s", exc)
        return []


async def _list_nat_rules(edge_id: str) -> list[dict]:
    try:
        return await vcd_client._get_paginated(  # type: ignore[attr-defined]
            f"/cloudapi/1.0.0/edgeGateways/{edge_id}/nat/rules"
        )
    except Exception as exc:
        logger.warning("NAT rules list failed: %s", exc)
        return []


async def _resolve_edge_name(edge_id: str) -> str | None:
    try:
        params = {"filter": f"(id=={edge_id})"}
        items = await vcd_client._get_paginated(  # type: ignore[attr-defined]
            "/cloudapi/1.0.0/edgeGateways", params=params
        )
    except Exception as exc:
        logger.warning("Edge name resolve failed for %s: %s", edge_id, exc)
        return None
    for e in items:
        if e.get("id") == edge_id:
            return e.get("name")
    return None


# ------------------------------------------------------------------
# Pair building
# ------------------------------------------------------------------

@dataclass
class ImportPair:
    address: str
    import_id: str
    reason: str


async def resolve_imports(
    resources: list[HclResource],
    target_edge_id: str,
    target_org: str,
    target_vdc: str | None,
) -> list[ImportPair]:
    pairs: list[ImportPair] = []

    by_type: dict[str, list[HclResource]] = {}
    for r in resources:
        by_type.setdefault(r.tf_type, []).append(r)

    edge_name = await _resolve_edge_name(target_edge_id)
    if not edge_name and (
        by_type.get("vcd_nsxt_edgegateway_static_route")
        or by_type.get("vcd_nsxt_ip_set")
        or by_type.get("vcd_nsxt_nat_rule")
    ):
        logger.warning(
            "Cannot resolve edge name for %s — skipping edge-scoped imports",
            target_edge_id,
        )

    scope_path = f"{target_org}.{target_vdc}.{edge_name}" if (target_vdc and edge_name) else None

    # Static routes: match by CIDR, import ID uses VCD name
    if by_type.get("vcd_nsxt_edgegateway_static_route") and scope_path:
        existing = await _list_static_routes(target_edge_id)
        by_cidr: dict[str, dict] = {}
        for e in existing:
            cidr = e.get("networkCidr") or e.get("network_cidr")
            if cidr:
                by_cidr[cidr] = e
        for r in by_type["vcd_nsxt_edgegateway_static_route"]:
            match = by_cidr.get(r.network_cidr) if r.network_cidr else None
            if match and match.get("name"):
                pairs.append(ImportPair(
                    address=r.address,
                    import_id=f"{scope_path}.{match['name']}",
                    reason=f"static route for {r.network_cidr} exists as '{match['name']}'",
                ))

    # IP sets: match by name
    if by_type.get("vcd_nsxt_ip_set") and scope_path:
        existing = await _list_ip_sets(target_edge_id)
        by_name = {e.get("name"): e for e in existing}
        for r in by_type["vcd_nsxt_ip_set"]:
            if r.vcd_name and r.vcd_name in by_name:
                pairs.append(ImportPair(
                    address=r.address,
                    import_id=f"{scope_path}.{r.vcd_name}",
                    reason=f"IP set '{r.vcd_name}' exists",
                ))

    # NAT rules: match by name
    if by_type.get("vcd_nsxt_nat_rule") and scope_path:
        existing = await _list_nat_rules(target_edge_id)
        by_name = {e.get("name"): e for e in existing}
        for r in by_type["vcd_nsxt_nat_rule"]:
            if r.vcd_name and r.vcd_name in by_name:
                pairs.append(ImportPair(
                    address=r.address,
                    import_id=f"{scope_path}.{r.vcd_name}",
                    reason=f"NAT rule '{r.vcd_name}' exists",
                ))

    # App port profiles: org scope, name-based import
    if by_type.get("vcd_nsxt_app_port_profile") and target_vdc:
        existing = await _list_app_port_profiles(target_org)
        by_name = {e.get("name"): e for e in existing}
        for r in by_type["vcd_nsxt_app_port_profile"]:
            if r.vcd_name and r.vcd_name in by_name:
                pairs.append(ImportPair(
                    address=r.address,
                    import_id=f"{target_org}.{target_vdc}.{r.vcd_name}",
                    reason=f"port profile '{r.vcd_name}' exists",
                ))

    return pairs


# ------------------------------------------------------------------
# Execution
# ------------------------------------------------------------------

async def run_preapply_imports(
    work_dir: Path,
    target_edge_id: str,
    target_org: str,
    operation_id: str | None = None,
) -> tuple[int, list[str]]:
    main_tf = work_dir / "main.tf"
    if not main_tf.exists():
        return 0, ["main.tf not found in workspace"]

    hcl = main_tf.read_text(encoding="utf-8")
    resources = parse_hcl_resources(hcl)
    if not resources:
        return 0, []

    vars_ = parse_hcl_var_defaults(hcl)
    target_vdc = vars_.get("target_vdc")
    hcl_org = vars_.get("target_org") or target_org

    logger.info(
        "Phase 2: %d importable resources, vdc=%s org=%s edge=%s",
        len(resources), target_vdc, hcl_org, target_edge_id,
    )

    pairs = await resolve_imports(resources, target_edge_id, hcl_org, target_vdc)
    if not pairs:
        logger.info("Phase 2: no existing VCD conflicts")
        return 0, []

    logger.info("Phase 2: %d imports to run", len(pairs))

    runner = TerraformRunner(work_dir, operation_id=operation_id)

    state_list = await runner._exec("state", "list", "-no-color", emit_exit=False)
    managed = set(state_list.stdout.strip().splitlines()) if state_list.success else set()

    errors: list[str] = []
    imported = 0
    skipped = 0
    for pair in pairs:
        if pair.address in managed:
            skipped += 1
            continue
        logger.info("import: %s <- %s (%s)", pair.address, pair.import_id, pair.reason)
        result = await runner._exec(
            "import", "-no-color", pair.address, pair.import_id, emit_exit=False,
        )
        if result.success:
            imported += 1
        else:
            msg = f"import failed for {pair.address} ({pair.import_id}): {result.stderr[:500]}"
            logger.warning(msg)
            errors.append(msg)

    if skipped:
        logger.info("Phase 2: skipped %d already-managed resources", skipped)

    return imported, errors
