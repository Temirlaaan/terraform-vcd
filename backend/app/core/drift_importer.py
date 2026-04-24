"""Auto-import unmanaged VCD resources into a drift-sync workspace.

Given a workspace at the end of a drift cycle, compare VCD reality against
terraform state and synthesise HCL + ``terraform import`` for resources
that exist in VCD but not in state. Keeps drift sync idempotent: anything
a user creates directly in VCD becomes tracked on the next run.

Covered types:
  * vcd_nsxt_ip_set
  * vcd_nsxt_edgegateway_static_route
  * vcd_nsxt_nat_rule
  * vcd_nsxt_app_port_profile (scope=TENANT only)

Notes:
  * Resource names/addresses derive from VCD object names, slugified. If a
    conflict with an existing state resource name is detected we suffix
    with a short hash of the VCD URN.
  * Cross-references (e.g. NAT rule → app_port_profile) are embedded as
    literal URNs for simplicity — symbolic refs can be introduced later.
  * On per-resource failure we log and continue; the resource is left in
    the ``skipped`` bucket and the HCL block we tentatively appended is
    rolled back so the workspace remains consistent.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from app.core import tf_import
from app.core.tf_runner import TerraformRunner
from app.integrations.vcd_client import vcd_client

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Utilities
# ----------------------------------------------------------------------


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    v = (value or "").lower().strip()
    v = _SLUG_RE.sub("_", v).strip("_")
    return v or "resource"


def _hcl_escape(s: Any) -> str:
    v = "" if s is None else str(s)
    v = v.replace("\\", "\\\\").replace('"', '\\"')
    v = v.replace("\n", "\\n").replace("\r", "\\r").replace("$", "$$")
    return v


def _short_hash(urn: str) -> str:
    return hashlib.sha1(urn.encode()).hexdigest()[:8]


def _unique_tf_name(base: str, urn: str, taken: set[str]) -> str:
    name = _slug(base)
    if name not in taken:
        taken.add(name)
        return name
    suffix = _short_hash(urn)
    candidate = f"{name}_{suffix}"
    taken.add(candidate)
    return candidate


def _collect_managed_ids(state_json: dict[str, Any]) -> dict[str, set[str]]:
    """Return {resource_type: {urn, ...}} from a tfstate dict."""
    out: dict[str, set[str]] = {}
    for r in state_json.get("resources", []):
        if r.get("mode") != "managed":
            continue
        rtype = r.get("type")
        bucket = out.setdefault(rtype, set())
        for inst in r.get("instances", []):
            attrs = inst.get("attributes", {})
            rid = attrs.get("id")
            if rid:
                bucket.add(rid)
    return out


def _collect_managed_tf_names(state_json: dict[str, Any]) -> dict[str, set[str]]:
    """Return {resource_type: {tf_name, ...}} from state, for dedup."""
    out: dict[str, set[str]] = {}
    for r in state_json.get("resources", []):
        if r.get("mode") != "managed":
            continue
        rtype = r.get("type")
        rname = r.get("name")
        if rtype and rname:
            out.setdefault(rtype, set()).add(rname)
    return out


# ----------------------------------------------------------------------
# Per-type HCL renderers
# ----------------------------------------------------------------------


def _render_ip_set(tf_name: str, detail: dict) -> str:
    ips = detail.get("ipAddresses") or []
    desc = detail.get("description") or ""
    name = detail.get("name") or tf_name
    ip_literal = ", ".join(f'"{_hcl_escape(ip)}"' for ip in ips)
    return (
        f'\nresource "vcd_nsxt_ip_set" "{tf_name}" {{\n'
        f'  org             = var.target_org\n'
        f'  edge_gateway_id = var.target_edge_id\n'
        f'  name            = "{_hcl_escape(name)}"\n'
        f'  description     = "{_hcl_escape(desc)}"\n'
        f'  ip_addresses    = [{ip_literal}]\n'
        f'}}\n'
    )


def _render_static_route(tf_name: str, detail: dict) -> str:
    name = detail.get("name") or tf_name
    desc = detail.get("description") or ""
    cidr = detail.get("networkCidr") or detail.get("network_cidr") or ""
    next_hops = detail.get("nextHops") or []
    # Each next_hop → nested block.
    hops_hcl = ""
    for hop in next_hops:
        ip = hop.get("ipAddress") or ""
        admin_dist = hop.get("adminDistance") or 1
        hops_hcl += (
            f'  next_hop {{\n'
            f'    ip_address     = "{_hcl_escape(ip)}"\n'
            f'    admin_distance = {int(admin_dist)}\n'
            f'  }}\n'
        )
    return (
        f'\nresource "vcd_nsxt_edgegateway_static_route" "{tf_name}" {{\n'
        f'  org             = var.target_org\n'
        f'  edge_gateway_id = var.target_edge_id\n'
        f'  name            = "{_hcl_escape(name)}"\n'
        f'  description     = "{_hcl_escape(desc)}"\n'
        f'  network_cidr    = "{_hcl_escape(cidr)}"\n'
        f'{hops_hcl}'
        f'}}\n'
    )


def _render_nat_rule(tf_name: str, detail: dict) -> str:
    name = detail.get("name") or tf_name
    desc = detail.get("description") or ""
    rule_type = detail.get("ruleType") or detail.get("type") or "DNAT"
    ext = detail.get("externalAddresses") or ""
    intr = detail.get("internalAddresses") or ""
    dnat_port = detail.get("dnatExternalPort") or ""
    enabled = detail.get("enabled", True)
    logging_on = detail.get("logging", False)
    app_port_profile = detail.get("applicationPortProfile") or {}
    app_port_id = app_port_profile.get("id") if isinstance(app_port_profile, dict) else None

    lines = [
        f'\nresource "vcd_nsxt_nat_rule" "{tf_name}" {{',
        f'  org              = var.target_org',
        f'  edge_gateway_id  = var.target_edge_id',
        f'  name             = "{_hcl_escape(name)}"',
        f'  rule_type        = "{_hcl_escape(rule_type)}"',
        f'  external_address = "{_hcl_escape(ext)}"',
        f'  internal_address = "{_hcl_escape(intr)}"',
    ]
    if dnat_port:
        lines.append(f'  dnat_external_port = "{_hcl_escape(dnat_port)}"')
    if desc:
        lines.append(f'  description      = "{_hcl_escape(desc)}"')
    lines.append(f'  enabled          = {"true" if enabled else "false"}')
    lines.append(f'  logging          = {"true" if logging_on else "false"}')
    if app_port_id:
        lines.append(f'  app_port_profile_id = "{_hcl_escape(app_port_id)}"')
    lines.append("}\n")
    return "\n".join(lines)


def _render_app_port_profile(tf_name: str, detail: dict) -> str:
    """Render TENANT-scope app port profile.

    SYSTEM/PROVIDER profiles are imported as ``data`` blocks elsewhere —
    we refuse to auto-import them here.
    """
    name = detail.get("name") or tf_name
    desc = detail.get("description") or ""
    app_ports = detail.get("applicationPorts") or []
    # Emit one app_port block per application port entry.
    blocks = ""
    for ap in app_ports:
        proto = ap.get("protocol") or "TCP"
        ports_list = ap.get("destinationPorts") or []
        port_literal = ", ".join(f'"{_hcl_escape(p)}"' for p in ports_list)
        port_line = f'    port     = [{port_literal}]\n' if ports_list else ""
        blocks += (
            f'  app_port {{\n'
            f'    protocol = "{_hcl_escape(proto)}"\n'
            f'{port_line}'
            f'  }}\n'
        )
    return (
        f'\nresource "vcd_nsxt_app_port_profile" "{tf_name}" {{\n'
        f'  org         = var.target_org\n'
        f'  context_id  = var.target_vdc_id\n'
        f'  scope       = "TENANT"\n'
        f'  name        = "{_hcl_escape(name)}"\n'
        f'  description = "{_hcl_escape(desc)}"\n'
        f'{blocks}'
        f'}}\n'
    )


# ----------------------------------------------------------------------
# Detail fetchers (via VCD CloudAPI)
# ----------------------------------------------------------------------


async def _fetch_ip_set_detail(item: dict) -> dict | None:
    try:
        return await vcd_client._get(
            f"/cloudapi/1.0.0/firewallGroups/{item['id']}"
        )
    except Exception as exc:
        logger.warning("fetch ip_set detail failed for %s: %s", item.get("id"), exc)
        return None


async def _fetch_static_route_detail(edge_id: str, item: dict) -> dict | None:
    try:
        return await vcd_client._get(
            f"/cloudapi/1.0.0/edgeGateways/{edge_id}/routing/staticRoutes/{item['id']}"
        )
    except Exception as exc:
        logger.warning("fetch static_route detail failed for %s: %s", item.get("id"), exc)
        return None


async def _fetch_nat_rule_detail(edge_id: str, item: dict) -> dict | None:
    try:
        return await vcd_client._get(
            f"/cloudapi/1.0.0/edgeGateways/{edge_id}/nat/rules/{item['id']}"
        )
    except Exception as exc:
        logger.warning("fetch nat_rule detail failed for %s: %s", item.get("id"), exc)
        return None


async def _fetch_app_port_profile_detail(item: dict) -> dict | None:
    try:
        return await vcd_client._get(
            f"/cloudapi/1.0.0/applicationPortProfiles/{item['id']}"
        )
    except Exception as exc:
        logger.warning("fetch app_port_profile detail failed for %s: %s", item.get("id"), exc)
        return None


# ----------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------


async def import_unmanaged(
    runner: TerraformRunner,
    workspace: Path,
    *,
    target_org: str,
    target_vdc: str,
    target_vdc_id: str | None,
    target_edge_id: str,
    target_edge_name: str | None,
    state_json: dict[str, Any],
) -> dict[str, Any]:
    """Detect + import unmanaged resources. Returns summary.

    Summary shape::

      {
        "imported": [{"type": str, "name": str, "id": str}, ...],
        "skipped":  [{"type": str, "name": str, "id": str, "reason": str}, ...],
      }

    Side effects:
      * Appends resource blocks to ``workspace/main.tf``.
      * Calls ``terraform import`` per resource (backend S3 state updated).

    Does NOT snapshot or commit — caller handles that.
    """
    edge_name = target_edge_name or await tf_import._resolve_edge_name(target_edge_id)
    if not edge_name:
        logger.warning("import_unmanaged: cannot resolve edge name, skipping")
        return {"imported": [], "skipped": []}

    managed_ids = _collect_managed_ids(state_json)
    taken_tf_names = _collect_managed_tf_names(state_json)
    scope_path = f"{target_org}.{target_vdc}.{edge_name}"

    imported: list[dict] = []
    skipped: list[dict] = []

    hcl_path = workspace / "main.tf"
    hcl = hcl_path.read_text(encoding="utf-8")

    async def _do(
        rtype: str,
        item: dict,
        detail: dict | None,
        import_id: str,
        block_renderer,
    ) -> None:
        nonlocal hcl
        urn = item.get("id") or ""
        base_name = item.get("name") or rtype
        if detail is None:
            skipped.append({
                "type": rtype, "name": base_name, "id": urn,
                "reason": "fetch_detail_failed",
            })
            return
        tf_name = _unique_tf_name(
            base_name, urn, taken_tf_names.setdefault(rtype, set()),
        )
        block = block_renderer(tf_name, detail)
        # Tentatively append block, then try import. On import failure,
        # remove the block so workspace stays consistent.
        new_hcl = hcl.rstrip() + "\n" + block
        hcl_path.write_text(new_hcl, encoding="utf-8")
        addr = f"{rtype}.{tf_name}"
        r = await runner._exec(
            "import", "-no-color", "-input=false", addr, import_id,
            emit_exit=False,
        )
        if r.return_code != 0:
            hcl_path.write_text(hcl, encoding="utf-8")
            skipped.append({
                "type": rtype, "name": base_name, "id": urn,
                "reason": f"import_failed: {r.stderr[:200]}",
            })
            taken_tf_names[rtype].discard(tf_name)
            return
        hcl = new_hcl
        imported.append({
            "type": rtype, "name": base_name, "id": urn, "tf_name": tf_name,
        })

    # ------------------------------------------------------------------
    # ip_sets (edge-scoped)
    # ------------------------------------------------------------------
    vcd_sets = await tf_import._list_ip_sets(target_edge_id)
    for s in vcd_sets:
        if s.get("id") in managed_ids.get("vcd_nsxt_ip_set", set()):
            continue
        detail = await _fetch_ip_set_detail(s)
        import_id = f"{scope_path}.{s.get('name')}"
        await _do("vcd_nsxt_ip_set", s, detail, import_id, _render_ip_set)

    # ------------------------------------------------------------------
    # static_routes (edge-scoped, import by name)
    # ------------------------------------------------------------------
    vcd_routes = await tf_import._list_static_routes(target_edge_id)
    for r in vcd_routes:
        if r.get("id") in managed_ids.get(
            "vcd_nsxt_edgegateway_static_route", set()
        ):
            continue
        if not r.get("name"):
            skipped.append({
                "type": "vcd_nsxt_edgegateway_static_route",
                "name": "", "id": r.get("id", ""),
                "reason": "route_has_no_name_cannot_import",
            })
            continue
        detail = await _fetch_static_route_detail(target_edge_id, r) or r
        import_id = f"{scope_path}.{r['name']}"
        await _do(
            "vcd_nsxt_edgegateway_static_route", r, detail, import_id,
            _render_static_route,
        )

    # ------------------------------------------------------------------
    # nat_rules (edge-scoped, import by name)
    # ------------------------------------------------------------------
    vcd_nats = await tf_import._list_nat_rules(target_edge_id)
    for n in vcd_nats:
        if n.get("id") in managed_ids.get("vcd_nsxt_nat_rule", set()):
            continue
        if not n.get("name"):
            skipped.append({
                "type": "vcd_nsxt_nat_rule",
                "name": "", "id": n.get("id", ""),
                "reason": "nat_rule_has_no_name_cannot_import",
            })
            continue
        detail = await _fetch_nat_rule_detail(target_edge_id, n) or n
        import_id = f"{scope_path}.{n['name']}"
        await _do("vcd_nsxt_nat_rule", n, detail, import_id, _render_nat_rule)

    # ------------------------------------------------------------------
    # app_port_profiles (org-scoped, TENANT only)
    # ------------------------------------------------------------------
    if target_vdc_id:
        vcd_profiles = await tf_import._list_app_port_profiles(target_org)
        for p in vcd_profiles:
            if p.get("scope") != "TENANT":
                continue  # SYSTEM/PROVIDER belong as `data` blocks; skip.
            if p.get("id") in managed_ids.get(
                "vcd_nsxt_app_port_profile", set()
            ):
                continue
            if not p.get("name"):
                skipped.append({
                    "type": "vcd_nsxt_app_port_profile",
                    "name": "", "id": p.get("id", ""),
                    "reason": "profile_has_no_name_cannot_import",
                })
                continue
            detail = await _fetch_app_port_profile_detail(p) or p
            import_id = f"{target_org}.{target_vdc}.{p['name']}"
            await _do(
                "vcd_nsxt_app_port_profile", p, detail, import_id,
                _render_app_port_profile,
            )

    return {"imported": imported, "skipped": skipped}
