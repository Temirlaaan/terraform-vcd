"""Parse a ``terraform.tfstate`` into a ``DeploymentSpec`` for editing.

Walks the state, groups resources by type, resolves URN references
(``source_ids`` / ``destination_ids`` / ``app_port_profile_ids``) back
to the resource ``name`` so the UI can edit by label.

Unknown resource types are skipped silently — they would reappear in
HCL untouched because the builder only emits resources present in the
spec. (That is deliberate: the first manual-deployment milestone covers
IP sets, app port profiles, firewall, NAT, and static routes — the same
surface the migration flow generates.)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.aria_attribution import strip as _strip_attr
from app.schemas.deployment_spec import (
    AppPortEntry,
    AppPortProfileSpec,
    DeploymentSpec,
    FirewallRuleSpec,
    IpSetSpec,
    NatRuleSpec,
    NextHopSpec,
    StaticRouteSpec,
    TargetSpec,
)

logger = logging.getLogger(__name__)


def _iter_managed_resources(state_json: dict[str, Any]):
    """Yield (type, name, attributes) tuples from both raw and show-json formats."""
    # terraform show -json
    values = state_json.get("values")
    if values and isinstance(values, dict):
        root = values.get("root_module", {})
        for r in root.get("resources", []):
            if r.get("mode") != "managed":
                continue
            yield r.get("type"), r.get("name"), r.get("values", {}) or {}
        return
    # raw tfstate
    for r in state_json.get("resources", []):
        if r.get("mode") != "managed":
            continue
        instances = r.get("instances", [])
        if not instances:
            continue
        yield r.get("type"), r.get("name"), instances[0].get("attributes", {}) or {}


def _build_urn_to_name(
    ip_sets: list[tuple[str, dict]],
    app_port_profiles: list[tuple[str, dict]],
) -> dict[str, str]:
    """Map VCD URN (stored in state ``id``) → the resource ``name``.

    The firewall rule ``source_ids`` / ``destination_ids`` / NAT
    ``app_port_profile_id`` reference URNs; the UI works with names.
    """
    out: dict[str, str] = {}
    for name, attrs in ip_sets:
        urn = attrs.get("id")
        if urn:
            out[urn] = attrs.get("name") or name
    for name, attrs in app_port_profiles:
        urn = attrs.get("id")
        if urn:
            out[urn] = attrs.get("name") or name
    return out


def _resolve_names(ids: list[str] | None, urn_map: dict[str, str]) -> list[str]:
    if not ids:
        return []
    out: list[str] = []
    for urn in ids:
        mapped = urn_map.get(urn)
        if mapped:
            out.append(mapped)
        else:
            # Preserve the raw URN so nothing is silently lost on save.
            out.append(urn)
    return out


def parse_state(state_json: dict[str, Any], target: TargetSpec) -> DeploymentSpec:
    """Convert a state dict into an editable ``DeploymentSpec``.

    ``target`` is passed in because it is not always recoverable from
    state alone (state may reference ``var.target_edge_id`` etc.).
    """
    ip_sets_raw: list[tuple[str, dict]] = []
    app_profiles_raw: list[tuple[str, dict]] = []
    firewall_attrs: dict | None = None
    static_routes_raw: list[tuple[str, dict]] = []
    nat_rules_raw: list[tuple[str, dict]] = []

    for rtype, rname, attrs in _iter_managed_resources(state_json):
        if rtype == "vcd_nsxt_ip_set":
            ip_sets_raw.append((rname, attrs))
        elif rtype == "vcd_nsxt_app_port_profile":
            app_profiles_raw.append((rname, attrs))
        elif rtype == "vcd_nsxt_firewall":
            # Only one firewall resource per edge — last wins if multiple.
            firewall_attrs = attrs
        elif rtype == "vcd_nsxt_edgegateway_static_route":
            static_routes_raw.append((rname, attrs))
        elif rtype == "vcd_nsxt_nat_rule":
            nat_rules_raw.append((rname, attrs))

    urn_map = _build_urn_to_name(ip_sets_raw, app_profiles_raw)

    ip_sets = [
        IpSetSpec(
            name=attrs.get("name", rname),
            description=_strip_attr(attrs.get("description") or ""),
            ip_addresses=list(attrs.get("ip_addresses") or []),
        )
        for rname, attrs in ip_sets_raw
    ]

    app_port_profiles = [
        AppPortProfileSpec(
            name=attrs.get("name", rname),
            description=_strip_attr(attrs.get("description") or ""),
            scope=attrs.get("scope") or "TENANT",
            app_ports=[
                AppPortEntry(
                    protocol=(p.get("protocol") or "TCP").upper(),
                    ports=list(p.get("port") or []),
                )
                for p in (attrs.get("app_port") or [])
            ],
        )
        for rname, attrs in app_profiles_raw
    ]

    firewall_rules: list[FirewallRuleSpec] = []
    if firewall_attrs:
        for rule in firewall_attrs.get("rule") or []:
            firewall_rules.append(
                FirewallRuleSpec(
                    name=rule.get("name") or "rule",
                    action=(rule.get("action") or "ALLOW").upper(),
                    direction=(rule.get("direction") or "IN_OUT").upper(),
                    ip_protocol=(rule.get("ip_protocol") or "IPV4").upper(),
                    enabled=bool(rule.get("enabled", True)),
                    logging=bool(rule.get("logging", False)),
                    source_ip_set_names=_resolve_names(rule.get("source_ids"), urn_map),
                    destination_ip_set_names=_resolve_names(
                        rule.get("destination_ids"), urn_map
                    ),
                    app_port_profile_names=_resolve_names(
                        rule.get("app_port_profile_ids"), urn_map
                    ),
                )
            )

    nat_rules: list[NatRuleSpec] = []
    for rname, attrs in nat_rules_raw:
        app_profile_name = None
        ap_id = attrs.get("app_port_profile_id")
        if ap_id:
            app_profile_name = urn_map.get(ap_id, ap_id)
        nat_rules.append(
            NatRuleSpec(
                name=attrs.get("name", rname),
                rule_type=(attrs.get("rule_type") or "DNAT").upper(),
                description=_strip_attr(attrs.get("description") or ""),
                external_address=attrs.get("external_address") or "",
                internal_address=attrs.get("internal_address") or "",
                dnat_external_port=attrs.get("dnat_external_port") or "",
                snat_destination_address=attrs.get("snat_destination_address") or "",
                app_port_profile_name=app_profile_name,
                enabled=bool(attrs.get("enabled", True)),
                logging=bool(attrs.get("logging", False)),
                priority=int(attrs.get("priority") or 0),
                firewall_match=(attrs.get("firewall_match") or "MATCH_INTERNAL_ADDRESS")
                .upper(),
            )
        )

    static_routes: list[StaticRouteSpec] = []
    for rname, attrs in static_routes_raw:
        hops = []
        for hop in attrs.get("next_hop") or []:
            hops.append(
                NextHopSpec(
                    ip_address=hop.get("ip_address") or "",
                    admin_distance=int(hop.get("admin_distance") or 1),
                )
            )
        static_routes.append(
            StaticRouteSpec(
                name=attrs.get("name", rname),
                description=_strip_attr(attrs.get("description") or ""),
                network_cidr=attrs.get("network_cidr") or "",
                next_hops=hops,
            )
        )

    return DeploymentSpec(
        target=target,
        ip_sets=ip_sets,
        app_port_profiles=app_port_profiles,
        firewall_rules=firewall_rules,
        nat_rules=nat_rules,
        static_routes=static_routes,
    )


def parse_state_text(state_text: str, target: TargetSpec) -> DeploymentSpec:
    return parse_state(json.loads(state_text), target)
