"""Render a ``DeploymentSpec`` into a ``main.tf`` HCL string.

Mirrors what ``app.migration.generator`` does for the migration flow,
but consumes the clean ``DeploymentSpec`` directly instead of the
NSX-V-specific normalized dict.

The rendered HCL contains *only* the resources block (variables +
resources). Provider and backend blocks are synthesised at workspace
setup time (see ``app.core.rollback._render_provider_tf`` and
``app.core.tf_workspace``), not here — ``state_key`` is a property of
the runtime workspace, not of the saved deployment.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.core.hcl_generator import _build_jinja_env
from app.schemas.deployment_spec import DeploymentSpec

logger = logging.getLogger(__name__)

DEPLOYMENT_TEMPLATES_DIR = (
    Path(__file__).resolve().parent.parent.parent / "templates" / "deployment"
)

_SECTION_TEMPLATES: list[str] = [
    "variables.tf.j2",
    "ip_sets.tf.j2",
    "app_port_profiles.tf.j2",
    "firewall.tf.j2",
    "nat.tf.j2",
    "static_routes.tf.j2",
]


def _slug(value: str) -> str:
    v = value.lower().strip()
    v = re.sub(r"[^a-z0-9]+", "_", v)
    v = v.strip("_")
    return v or "item"


def _assign_unique_slugs(
    items: list[Any], base_prefix: str
) -> list[str]:
    """Return a stable, collision-free slug for each item.

    Slugs are derived from the item ``name``; duplicates get ``_2``, ``_3``…
    Rename of a rule therefore renames its Terraform address — which means
    a destroy+create on next apply. That is a deliberate MVP trade-off:
    cleaner HCL over cross-rename stability. Flagged in the UI (see 6.3).
    """
    seen: dict[str, int] = {}
    out: list[str] = []
    for idx, item in enumerate(items):
        base = _slug(getattr(item, "name", "")) or f"{base_prefix}_{idx + 1}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        slug = base if count == 0 else f"{base}_{count + 1}"
        out.append(slug)
    return out


def _build_name_to_slug(items: list[Any], slugs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item, slug in zip(items, slugs):
        out[item.name] = slug
    return out


def _resolve_refs(names: list[str], name_to_slug: dict[str, str]) -> list[str]:
    """Map rule-referenced names back to resource slugs.

    Names that do not resolve to a known resource are silently dropped —
    they almost always indicate an IP set deleted in the UI while a rule
    still referenced it. We do not want to emit a broken HCL reference.
    Caller is expected to validate references before calling build_hcl
    if strictness is desired.
    """
    resolved: list[str] = []
    for name in names:
        slug = name_to_slug.get(name)
        if slug:
            resolved.append(slug)
        else:
            logger.warning("deployment_builder: unresolved reference %r dropped", name)
    return resolved


def build_hcl(spec: DeploymentSpec) -> str:
    """Render the spec into ``main.tf`` HCL text."""
    env = _build_jinja_env(DEPLOYMENT_TEMPLATES_DIR)

    ip_set_slugs = _assign_unique_slugs(spec.ip_sets, "ip_set")
    profile_slugs = _assign_unique_slugs(spec.app_port_profiles, "profile")
    nat_slugs = _assign_unique_slugs(spec.nat_rules, "nat")
    route_slugs = _assign_unique_slugs(spec.static_routes, "route")

    ip_set_name_to_slug = _build_name_to_slug(spec.ip_sets, ip_set_slugs)
    profile_name_to_slug = _build_name_to_slug(spec.app_port_profiles, profile_slugs)

    ip_sets_ctx = [
        {
            "slug": slug,
            "name": item.name,
            "description": item.description,
            "ip_addresses": item.ip_addresses,
        }
        for item, slug in zip(spec.ip_sets, ip_set_slugs)
    ]

    profiles_ctx = [
        {
            "slug": slug,
            "name": item.name,
            "description": item.description,
            "scope": item.scope,
            "app_ports": [
                {"protocol": p.protocol, "ports": p.ports} for p in item.app_ports
            ],
        }
        for item, slug in zip(spec.app_port_profiles, profile_slugs)
    ]

    firewall_ctx = [
        {
            "name": rule.name,
            "direction": rule.direction,
            "ip_protocol": rule.ip_protocol,
            "action": rule.action,
            "enabled": rule.enabled,
            "logging": rule.logging,
            "source_slugs": _resolve_refs(rule.source_ip_set_names, ip_set_name_to_slug),
            "destination_slugs": _resolve_refs(
                rule.destination_ip_set_names, ip_set_name_to_slug
            ),
            "app_port_profile_slugs": _resolve_refs(
                rule.app_port_profile_names, profile_name_to_slug
            ),
        }
        for rule in spec.firewall_rules
    ]

    nat_ctx = [
        {
            "slug": slug,
            "name": rule.name,
            "rule_type": rule.rule_type,
            "description": rule.description,
            "external_address": rule.external_address,
            "internal_address": rule.internal_address,
            "dnat_external_port": rule.dnat_external_port,
            "snat_destination_address": rule.snat_destination_address,
            "app_port_profile_slug": (
                profile_name_to_slug.get(rule.app_port_profile_name)
                if rule.app_port_profile_name
                else None
            ),
            "enabled": rule.enabled,
            "logging": rule.logging,
            "priority": rule.priority,
            "firewall_match": rule.firewall_match,
        }
        for rule, slug in zip(spec.nat_rules, nat_slugs)
    ]

    routes_ctx = [
        {
            "slug": slug,
            "name": route.name,
            "description": route.description,
            "network_cidr": route.network_cidr,
            "next_hops": [
                {"ip_address": h.ip_address, "admin_distance": h.admin_distance}
                for h in route.next_hops
            ],
        }
        for route, slug in zip(spec.static_routes, route_slugs)
    ]

    ctx: dict[str, Any] = {
        "target": spec.target.model_dump(),
        "ip_sets": ip_sets_ctx,
        "app_port_profiles": profiles_ctx,
        "firewall_rules": firewall_ctx,
        "nat_rules": nat_ctx,
        "static_routes": routes_ctx,
    }

    blocks: list[str] = []
    for tpl_name in _SECTION_TEMPLATES:
        tpl = env.get_template(tpl_name)
        rendered = tpl.render(**ctx)
        if rendered.strip():
            blocks.append(rendered)

    return "\n".join(blocks)


def summary_from_spec(spec: DeploymentSpec) -> dict[str, int]:
    """Return the ``summary`` payload persisted alongside a deployment row."""
    return {
        "firewall_rules_total": len(spec.firewall_rules),
        "firewall_rules_user": len(spec.firewall_rules),
        "firewall_rules_system": 0,
        "nat_rules_total": len(spec.nat_rules),
        "app_port_profiles_total": len(spec.app_port_profiles),
        "app_port_profiles_system": 0,
        "app_port_profiles_custom": len(spec.app_port_profiles),
        "static_routes_total": len(spec.static_routes),
    }
