"""Append firewall-import helper to imports.py.

Renders ``vcd_nsxt_firewall`` block from VCD ``userDefinedRules`` and
runs ``terraform import`` against the edge URN. Called from the import
endpoint AFTER ip_set/profile imports so referenced URNs already exist
in state — the firewall block uses literal URN strings (provider
accepts those directly), so no slug resolution is required.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.core.drift_importer import _hcl_escape, _slug, _unique_tf_name
from app.core.tf_runner import TerraformRunner
from app.integrations.vcd_client import vcd_client

logger = logging.getLogger(__name__)


def _render_firewall_block(tf_name: str, rules: list[dict]) -> str:
    """Render a single ``vcd_nsxt_firewall`` resource with all user rules."""
    lines: list[str] = [
        f'\nresource "vcd_nsxt_firewall" "{tf_name}" {{',
        '  org             = var.target_org',
        '  edge_gateway_id = var.target_edge_id',
        '',
    ]
    for r in rules:
        name = r.get("name") or f"rule_{r.get('id', '')[:8]}"
        # ``actionValue`` (35.2+) supersedes ``action`` but VCD returns
        # both — prefer the newer field.
        action = r.get("actionValue") or r.get("action") or "ALLOW"
        direction = r.get("direction") or "IN_OUT"
        ip_protocol = r.get("ipProtocol") or "IPV4"
        enabled = r.get("enabled", True)
        logging_on = r.get("logging", False)

        src_groups = r.get("sourceFirewallGroups") or []
        dst_groups = r.get("destinationFirewallGroups") or []
        app_profiles = r.get("applicationPortProfiles") or []

        src_ids = [g.get("id") for g in src_groups if g.get("id")]
        dst_ids = [g.get("id") for g in dst_groups if g.get("id")]
        app_ids = [p.get("id") for p in app_profiles if p.get("id")]

        lines.append("  rule {")
        lines.append(f'    name        = "{_hcl_escape(name)}"')
        lines.append(f'    direction   = "{_hcl_escape(direction)}"')
        lines.append(f'    ip_protocol = "{_hcl_escape(ip_protocol)}"')
        lines.append(f'    action      = "{_hcl_escape(action)}"')
        lines.append(f'    enabled     = {"true" if enabled else "false"}')
        lines.append(f'    logging     = {"true" if logging_on else "false"}')
        if src_ids:
            literal = ", ".join(f'"{_hcl_escape(s)}"' for s in src_ids)
            lines.append(f'    source_ids  = [{literal}]')
        if dst_ids:
            literal = ", ".join(f'"{_hcl_escape(s)}"' for s in dst_ids)
            lines.append(f'    destination_ids = [{literal}]')
        if app_ids:
            literal = ", ".join(f'"{_hcl_escape(s)}"' for s in app_ids)
            lines.append(f'    app_port_profile_ids = [{literal}]')
        lines.append("  }")
        lines.append("")
    lines.append("}\n")
    return "\n".join(lines)


async def import_firewall_for_edge(
    runner: TerraformRunner,
    workspace: Path,
    *,
    target_org: str,
    target_vdc: str,
    target_edge_id: str,
    target_edge_name: str | None,
    state_json: dict[str, Any],
) -> dict[str, Any]:
    """Fetch firewall rules from VCD and import as a single resource.

    Returns ``{"imported": [...], "skipped": [...]}`` matching the
    ``import_unmanaged`` shape so callers can merge the summary.

    No-op if state already tracks a ``vcd_nsxt_firewall`` resource (we
    don't want to clobber an existing one — the daily drift sync handles
    rule-level diffs separately).
    """
    summary: dict[str, list[dict]] = {"imported": [], "skipped": []}

    already_managed = any(
        r.get("type") == "vcd_nsxt_firewall"
        for r in state_json.get("resources", [])
        if r.get("mode") == "managed"
    )
    if already_managed:
        return summary

    try:
        data = await vcd_client._get(
            f"/cloudapi/1.0.0/edgeGateways/{target_edge_id}/firewall/rules"
        )
    except Exception as exc:
        logger.warning(
            "import_firewall: fetch rules failed for %s: %s", target_edge_id, exc
        )
        summary["skipped"].append({
            "type": "vcd_nsxt_firewall",
            "name": "userDefinedRules",
            "id": target_edge_id,
            "reason": f"fetch_failed: {exc}",
        })
        return summary

    rules = []
    if isinstance(data, dict):
        rules = data.get("userDefinedRules") or []
    if not rules:
        logger.info("import_firewall: no user-defined rules on %s", target_edge_id)
        return summary

    taken: set[str] = set()
    tf_name = _unique_tf_name(_slug("imported_firewall"), target_edge_id, taken)

    block = _render_firewall_block(tf_name, rules)
    main_tf = workspace / "main.tf"
    original = main_tf.read_text(encoding="utf-8")
    main_tf.write_text(original.rstrip() + "\n" + block, encoding="utf-8")

    # vcd_nsxt_firewall import id format = "<org>.<vdc>.<edge_name>"
    # (NOT the edge URN — provider resolves names internally).
    edge_name = target_edge_name
    if not edge_name:
        try:
            from app.core.tf_import import _resolve_edge_name
            edge_name = await _resolve_edge_name(target_edge_id)
        except Exception:
            edge_name = None
    if not edge_name:
        main_tf.write_text(original, encoding="utf-8")
        summary["skipped"].append({
            "type": "vcd_nsxt_firewall",
            "name": tf_name,
            "id": target_edge_id,
            "reason": "edge_name_unresolved",
        })
        return summary

    import_id = f"{target_org}.{target_vdc}.{edge_name}"
    addr = f"vcd_nsxt_firewall.{tf_name}"
    r = await runner._exec(
        "import", "-no-color", "-input=false", addr, import_id,
        emit_exit=False,
    )
    if r.return_code != 0:
        # Roll back the HCL append so workspace stays consistent.
        main_tf.write_text(original, encoding="utf-8")
        err_blob = (r.stderr or "")[:300] or (r.stdout or "")[-300:]
        summary["skipped"].append({
            "type": "vcd_nsxt_firewall",
            "name": tf_name,
            "id": import_id,
            "reason": f"import_failed: {err_blob}",
        })
        logger.warning(
            "import_firewall: terraform import failed addr=%s id=%s err=%s",
            addr, import_id, err_blob,
        )
        return summary

    summary["imported"].append({
        "type": "vcd_nsxt_firewall",
        "name": "userDefinedRules",
        "id": import_id,
        "tf_name": tf_name,
        "rules": len(rules),
    })
    logger.info(
        "import_firewall: imported %d rules as %s for id=%s",
        len(rules), addr, import_id,
    )
    return summary
