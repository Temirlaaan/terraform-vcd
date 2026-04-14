"""Canonical JSON → HCL generator for NSX-V to NSX-T edge migration.

Renders Jinja2 templates from normalized JSON (produced by normalizer.py)
to generate Terraform HCL for NSX-T resources: IP sets, app port profiles,
firewall, NAT rules, and static routes.
"""

import hashlib
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.core.hcl_generator import _build_jinja_env

logger = logging.getLogger(__name__)

MIGRATION_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates" / "migration"

_SECTION_TEMPLATES: list[str] = [
    "variables.tf.j2",
    "ip_sets.tf.j2",
    "app_port_profiles.tf.j2",
    "firewall.tf.j2",
    "nat.tf.j2",
    "static_routes.tf.j2",
]


def _ip_set_hash(ip_addresses: list[str]) -> str:
    """Generate a short stable hash from a sorted list of IP addresses."""
    key = ",".join(sorted(ip_addresses))
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def _collect_ip_sets(firewall_rules: list[dict]) -> list[dict]:
    """Collect and deduplicate IP sets from firewall rules.

    Groups rules that share the exact same set of IP addresses into
    a single IP set resource. Returns a list of IP set dicts with:
      - name: stable identifier like "ipset_a1b2c3"
      - display_name: human-readable name for VCD
      - ip_addresses: sorted list of IPs/CIDRs
      - used_by: list of {rule_id, direction} dicts
    """
    # key: frozenset of IPs → ip_set dict
    seen: dict[frozenset[str], dict] = {}

    for rule in firewall_rules:
        if rule.get("is_system", False):
            continue

        for direction, endpoint_key in [("src", "source"), ("dst", "destination")]:
            endpoint = rule.get(endpoint_key, {})
            ips = endpoint.get("ip_addresses", [])
            if not ips:
                continue

            ip_key = frozenset(ips)
            if ip_key not in seen:
                sorted_ips = sorted(ips)
                short_hash = _ip_set_hash(sorted_ips)
                seen[ip_key] = {
                    "name": f"ipset_{short_hash}",
                    "display_name": f"ipset_{short_hash}",
                    "ip_addresses": sorted_ips,
                    "used_by": [],
                }

            seen[ip_key]["used_by"].append({
                "rule_id": rule["original_id"],
                "direction": direction,
            })

    return list(seen.values())


def _build_rule_ip_set_map(ip_sets: list[dict]) -> dict[str, dict[str, str]]:
    """Build a map: rule_id → {src: ip_set_name, dst: ip_set_name}."""
    result: dict[str, dict[str, str]] = {}
    for ip_set in ip_sets:
        for ref in ip_set["used_by"]:
            rule_id = ref["rule_id"]
            direction = ref["direction"]
            if rule_id not in result:
                result[rule_id] = {}
            result[rule_id][direction] = ip_set["name"]
    return result


def _enrich_nat_rules(nat: dict) -> dict:
    """Add is_system_profile flag to each NAT rule based on profile lookup.

    Returns a new dict (does not mutate the input).
    """
    nat = deepcopy(nat)

    # Build lookup: profile_key → is_system_defined
    profile_lookup: dict[str, bool] = {}
    for prof in nat.get("required_app_port_profiles", []):
        profile_lookup[prof["key"]] = prof["is_system_defined"]

    for rule in nat.get("rules", []):
        key = rule.get("app_port_profile_key", "")
        if rule.get("needs_app_port_profile") and key:
            rule["is_system_profile"] = profile_lookup.get(key, False)
        else:
            rule["is_system_profile"] = False

    return nat


class MigrationHCLGenerator:
    """Renders migration HCL from normalized edge snapshot JSON."""

    def __init__(self, templates_dir: Path | None = None) -> None:
        self._env = _build_jinja_env(templates_dir or MIGRATION_TEMPLATES_DIR)

    def generate(
        self,
        normalized: dict,
        target_org: str,
        target_vdc: str,
        target_edge_id: str,
    ) -> str:
        """Generate complete migration HCL.

        Args:
            normalized: canonical JSON from normalize_edge_snapshot()
            target_org: target organization name in VCD 10.6
            target_vdc: target VDC name
            target_edge_id: target NSX-T edge gateway URN

        Returns:
            Combined HCL string with all migration resources.
        """
        firewall = deepcopy(normalized.get("firewall", {}))
        nat = _enrich_nat_rules(normalized.get("nat", {}))
        routing = normalized.get("routing", {})

        # Collect and deduplicate IP sets from firewall rules
        ip_sets = _collect_ip_sets(firewall.get("rules", []))
        ip_set_map = _build_rule_ip_set_map(ip_sets)

        # Annotate firewall rules with their IP set names for template use
        for rule in firewall.get("rules", []):
            rule_map = ip_set_map.get(rule["original_id"], {})
            rule["_source_ip_set_name"] = rule_map.get("src", "")
            rule["_dest_ip_set_name"] = rule_map.get("dst", "")

        ctx: dict[str, Any] = {
            "target_org_name": target_org,
            "target_vdc_name": target_vdc,
            "target_edge_id": target_edge_id,
            "firewall": firewall,
            "nat": nat,
            "routing": routing,
            "ip_sets": ip_sets,
        }

        blocks: list[str] = []
        for template_name in _SECTION_TEMPLATES:
            tpl = self._env.get_template(template_name)
            rendered = tpl.render(**ctx)
            if rendered.strip():
                blocks.append(rendered)

        return "\n".join(blocks)
