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


def _netmask_to_cidr(ip: str, netmask: str) -> str:
    """Convert IP + netmask to CIDR notation (network address).

    Example: "10.10.0.1", "255.255.255.0" → "10.10.0.0/24"
    """
    ip_parts = [int(x) for x in ip.split(".")]
    mask_parts = [int(x) for x in netmask.split(".")]
    network_parts = [ip_parts[i] & mask_parts[i] for i in range(4)]
    prefix_len = sum(bin(m).count("1") for m in mask_parts)
    return f"{'.'.join(str(p) for p in network_parts)}/{prefix_len}"


def _resolve_internal_networks(edge_meta: dict) -> list[str]:
    """Extract CIDRs for all 'internal' interfaces from edge metadata.

    In NSX-V, vnicGroupId=internal means all routed (internal) interfaces
    on the edge gateway. We resolve their subnets to CIDRs.
    """
    cidrs: list[str] = []
    for iface in edge_meta.get("interfaces", []):
        if iface.get("type", "").lower() != "internal":
            continue
        for subnet in iface.get("subnets", []):
            gateway = subnet.get("gateway", "")
            netmask = subnet.get("netmask", "")
            if gateway and netmask:
                cidrs.append(_netmask_to_cidr(gateway, netmask))
    return cidrs


def _collect_ip_sets(firewall_rules: list[dict], edge_meta: dict | None = None) -> list[dict]:
    """Collect and deduplicate IP sets from firewall rules.

    Groups rules that share the exact same set of IP addresses into
    a single IP set resource. Returns a list of IP set dicts with:
      - name: stable identifier like "ipset_a1b2c3"
      - display_name: human-readable name for VCD
      - ip_addresses: sorted list of IPs/CIDRs
      - used_by: list of {rule_id, direction} dicts

    When edge_meta is provided, resolves vnicGroupId=internal to the
    CIDRs of all internal (routed) interfaces on the edge gateway.
    """
    internal_cidrs = _resolve_internal_networks(edge_meta) if edge_meta else []

    # key: frozenset of IPs → ip_set dict
    seen: dict[frozenset[str], dict] = {}

    for rule in firewall_rules:
        if rule.get("is_system", False):
            continue

        for direction, endpoint_key in [("src", "source"), ("dst", "destination")]:
            endpoint = rule.get(endpoint_key, {})
            ips = list(endpoint.get("ip_addresses", []))

            # Resolve vnicGroupId references
            vnic_groups = endpoint.get("vnic_group_ids", [])
            for vnic_id in vnic_groups:
                vnic_lower = vnic_id.lower()
                if vnic_lower == "internal":
                    if internal_cidrs:
                        ips.extend(internal_cidrs)
                    else:
                        logger.warning(
                            "Rule %s uses vnicGroupId=internal but no internal "
                            "interfaces found in edge metadata. "
                            "Manual migration required for this rule.",
                            rule["original_id"],
                        )
                elif "vse" not in vnic_lower:
                    # external, vnic-0, vnic-1 etc. — not automatically resolvable
                    logger.warning(
                        "Rule %s uses unsupported vnicGroupId=%s. "
                        "Skipping this endpoint reference — manual migration required.",
                        rule["original_id"],
                        vnic_id,
                    )

            if not ips:
                continue

            ip_key = frozenset(ips)
            if ip_key not in seen:
                sorted_ips = sorted(ips)
                short_hash = _ip_set_hash(sorted_ips)
                display = "ipset_internal" if vnic_groups and any(
                    v.lower() == "internal" for v in vnic_groups
                ) else f"ipset_{short_hash}"
                seen[ip_key] = {
                    "name": f"ipset_{short_hash}",
                    "display_name": display,
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


def _collect_firewall_app_port_profiles(
    firewall_rules: list[dict],
) -> tuple[list[dict], dict[str, list[str]]]:
    """Collect and deduplicate app port profiles from firewall rule applications.

    Each (protocol, port) pair becomes one atomic profile. Multiple services
    in a single rule produce multiple profile references in app_port_profile_ids.

    Returns:
        profiles: list of profile dicts (same format as NAT profiles)
        rule_profile_map: rule_id → list of profile keys
    """
    from app.migration.normalizer import (
        SYSTEM_PROFILES,
        _build_app_port_profile_key,
        _resolve_system_profile,
    )

    profiles: dict[str, dict] = {}
    rule_profile_map: dict[str, list[str]] = {}

    for rule in firewall_rules:
        if rule.get("is_system", False):
            continue

        services = rule.get("application", [])
        if not services:
            continue

        rule_id = rule["original_id"]
        rule_profile_map[rule_id] = []

        for svc in services:
            protocol = svc.get("protocol", "")
            port = svc.get("port", "")

            if not protocol:
                continue

            # ICMP has no port — use "any" as key component
            if protocol.lower() in ("icmp", "icmpv4", "icmpv6"):
                port = "any"

            key = _build_app_port_profile_key(protocol, port)
            rule_profile_map[rule_id].append(key)

            if key not in profiles:
                system_name = _resolve_system_profile(key)
                is_system = system_name is not None

                # Map NSX-V protocol names to NSX-T names
                nsxt_protocol = protocol.upper()
                if nsxt_protocol == "ICMP":
                    nsxt_protocol = "ICMPv4"

                custom_name = (
                    None
                    if is_system
                    else f"ttc_fw_{protocol.lower()}_{port.replace('-', '_')}"
                )
                profiles[key] = {
                    "key": key,
                    "protocol": nsxt_protocol,
                    "ports": port,
                    "is_system_defined": is_system,
                    "system_defined_name": system_name,
                    "custom_name": custom_name,
                    "used_by_rule_ids": [],
                    "source": "firewall",
                }
            profiles[key]["used_by_rule_ids"].append(rule_id)

    return list(profiles.values()), rule_profile_map


def _merge_app_port_profiles(
    nat_profiles: list[dict],
    fw_profiles: list[dict],
) -> list[dict]:
    """Merge NAT and firewall app port profiles, deduplicating by key."""
    merged: dict[str, dict] = {}
    for prof in nat_profiles:
        key = prof["key"]
        merged[key] = prof.copy()
        merged[key].setdefault("source", "nat")

    for prof in fw_profiles:
        key = prof["key"]
        if key in merged:
            # Profile already exists from NAT — merge used_by_rule_ids
            existing = merged[key]
            for rid in prof["used_by_rule_ids"]:
                if rid not in existing["used_by_rule_ids"]:
                    existing["used_by_rule_ids"].append(rid)
        else:
            merged[key] = prof.copy()

    return list(merged.values())


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

        edge_meta = normalized.get("edge", {})

        # Collect and deduplicate IP sets from firewall rules
        ip_sets = _collect_ip_sets(firewall.get("rules", []), edge_meta=edge_meta)
        ip_set_map = _build_rule_ip_set_map(ip_sets)

        # Collect app port profiles from firewall rules
        fw_profiles, fw_profile_map = _collect_firewall_app_port_profiles(
            firewall.get("rules", []),
        )

        # Merge firewall profiles with NAT profiles (dedup by key)
        nat_profiles = nat.get("required_app_port_profiles", [])
        all_profiles = _merge_app_port_profiles(nat_profiles, fw_profiles)

        # Annotate firewall rules with their IP set names and profile keys
        for rule in firewall.get("rules", []):
            rule_id = rule["original_id"]
            rule_map = ip_set_map.get(rule_id, {})
            rule["_source_ip_set_name"] = rule_map.get("src", "")
            rule["_dest_ip_set_name"] = rule_map.get("dst", "")
            rule["_app_port_profile_keys"] = fw_profile_map.get(rule_id, [])

        # Build profile lookup for template: key → {is_system, slug}
        profile_lookup: dict[str, dict] = {}
        for prof in all_profiles:
            profile_lookup[prof["key"]] = {
                "is_system_defined": prof["is_system_defined"],
            }

        ctx: dict[str, Any] = {
            "target_org_name": target_org,
            "target_vdc_name": target_vdc,
            "target_edge_id": target_edge_id,
            "firewall": firewall,
            "nat": nat,
            "routing": routing,
            "ip_sets": ip_sets,
            "all_profiles": all_profiles,
            "profile_lookup": profile_lookup,
        }

        blocks: list[str] = []
        for template_name in _SECTION_TEMPLATES:
            tpl = self._env.get_template(template_name)
            rendered = tpl.render(**ctx)
            if rendered.strip():
                blocks.append(rendered)

        return "\n".join(blocks)
