"""Read an NSX-T edge gateway's configuration into a ``DeploymentSpec``.

This is the cloud-to-cloud bridge.  ``tf_import`` and ``drift_importer``
also read the CloudAPI, but they exist to bring resources into *Terraform
state* on the cloud they already live in.  Here we only want the shape of
the configuration, detached from any cloud: read an edge on VCD A, produce
a spec, point the spec at an edge on VCD B, and ``deployment_builder``
renders HCL for B.

Everything is driven by an explicit ``VCDClient``, never the module-level
singleton, because the whole point is reading a cloud that is not the one
Terraform will write to.

Names, not IDs, are the join key inside a spec (see ``DeploymentSpec``),
which is exactly what makes it portable: resource URNs are meaningless on
the other cloud, but "the IP set called dmz-hosts" survives the trip.
"""

from __future__ import annotations

import logging

from app.integrations.vcd_client import VCDClient
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


class EdgeReadError(RuntimeError):
    """The edge could not be read — surfaced to the operator, not swallowed."""


async def _paginated(vcd: VCDClient, path: str, params: dict | None = None) -> list[dict]:
    return await vcd._get_paginated(path, params=params)  # type: ignore[attr-defined]


async def _detail(vcd: VCDClient, path: str) -> dict:
    return await vcd._get(path)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
#  Per-resource readers
# ---------------------------------------------------------------------------

async def read_ip_sets(vcd: VCDClient, edge_id: str) -> list[IpSetSpec]:
    params = {"filter": f"(edgeGatewayId=={edge_id};typeValue==IP_SET)"}
    summaries = await _paginated(vcd, "/cloudapi/1.0.0/firewallGroups/summaries", params)
    out: list[IpSetSpec] = []
    for item in summaries:
        detail = await _detail(vcd, f"/cloudapi/1.0.0/firewallGroups/{item['id']}")
        out.append(IpSetSpec(
            name=detail.get("name") or "",
            description=detail.get("description") or "",
            ip_addresses=list(detail.get("ipAddresses") or []),
        ))
    return out


async def read_app_port_profiles(
    vcd: VCDClient, org_name: str
) -> tuple[list[AppPortProfileSpec], dict[str, str]]:
    """Return TENANT-scope profiles plus an id→name map covering every scope.

    The map is what lets NAT and firewall rules refer to profiles by name —
    including SYSTEM ones, which are not copied but do exist on both clouds.
    """
    id_to_name: dict[str, str] = {}
    tenant: list[AppPortProfileSpec] = []

    for scope in ("TENANT", "SYSTEM", "PROVIDER"):
        try:
            items = await _paginated(
                vcd,
                "/cloudapi/1.0.0/applicationPortProfiles",
                {"filter": f"(scope=={scope})"},
            )
        except Exception as exc:
            logger.warning("app port profiles scope=%s failed: %s", scope, exc)
            continue

        for p in items:
            pid, pname = p.get("id"), p.get("name")
            if pid and pname:
                id_to_name[pid] = pname
            if scope != "TENANT":
                continue
            if (p.get("orgRef") or {}).get("name") != org_name:
                continue
            tenant.append(AppPortProfileSpec(
                name=pname or "",
                description=p.get("description") or "",
                scope="TENANT",
                app_ports=[
                    AppPortEntry(
                        protocol=ap.get("protocol") or "TCP",
                        ports=list(ap.get("destinationPorts") or []),
                    )
                    for ap in (p.get("applicationPorts") or [])
                ],
            ))
    return tenant, id_to_name


async def read_nat_rules(
    vcd: VCDClient, edge_id: str, profile_names: dict[str, str]
) -> list[NatRuleSpec]:
    rules = await _paginated(vcd, f"/cloudapi/1.0.0/edgeGateways/{edge_id}/nat/rules")
    out: list[NatRuleSpec] = []
    for r in rules:
        profile = r.get("applicationPortProfile") or {}
        profile_id = profile.get("id") if isinstance(profile, dict) else None
        # Prefer the name the API already gave us; fall back to the lookup.
        profile_name = (
            profile.get("name") if isinstance(profile, dict) else None
        ) or profile_names.get(profile_id or "")

        out.append(NatRuleSpec(
            name=r.get("name") or "",
            rule_type=r.get("ruleType") or r.get("type") or "DNAT",
            description=r.get("description") or "",
            external_address=r.get("externalAddresses") or "",
            internal_address=r.get("internalAddresses") or "",
            dnat_external_port=str(r.get("dnatExternalPort") or ""),
            snat_destination_address=r.get("snatDestinationAddresses") or "",
            app_port_profile_name=profile_name,
            enabled=bool(r.get("enabled", True)),
            logging=bool(r.get("logging", False)),
            priority=int(r.get("priority") or 0),
        ))
    return out


async def read_static_routes(vcd: VCDClient, edge_id: str) -> list[StaticRouteSpec]:
    routes = await _paginated(
        vcd, f"/cloudapi/1.0.0/edgeGateways/{edge_id}/routing/staticRoutes"
    )
    out: list[StaticRouteSpec] = []
    for r in routes:
        out.append(StaticRouteSpec(
            name=r.get("name") or "",
            description=r.get("description") or "",
            network_cidr=r.get("networkCidr") or r.get("network_cidr") or "",
            next_hops=[
                NextHopSpec(
                    ip_address=h.get("ipAddress") or "",
                    admin_distance=int(h.get("adminDistance") or 1),
                )
                for h in (r.get("nextHops") or [])
            ],
        ))
    return out


async def read_firewall_rules(
    vcd: VCDClient,
    edge_id: str,
    ip_set_names: dict[str, str],
    profile_names: dict[str, str],
) -> list[FirewallRuleSpec]:
    payload = await _detail(vcd, f"/cloudapi/1.0.0/edgeGateways/{edge_id}/firewall/rules")
    rules = payload.get("userDefinedRules") or payload.get("values") or []

    def _names(groups: list[dict]) -> list[str]:
        out = []
        for g in groups or []:
            name = g.get("name") or ip_set_names.get(g.get("id") or "")
            if name:
                out.append(name)
        return out

    out: list[FirewallRuleSpec] = []
    for r in rules:
        profiles = []
        for p in r.get("applicationPortProfiles") or []:
            name = p.get("name") or profile_names.get(p.get("id") or "")
            if name:
                profiles.append(name)

        out.append(FirewallRuleSpec(
            name=r.get("name") or "",
            action=r.get("actionValue") or r.get("action") or "ALLOW",
            direction=r.get("direction") or "IN_OUT",
            ip_protocol=r.get("ipProtocol") or "IPV4",
            enabled=bool(r.get("enabled", True)),
            logging=bool(r.get("logging", False)),
            source_ip_set_names=_names(r.get("sourceFirewallGroups") or []),
            destination_ip_set_names=_names(r.get("destinationFirewallGroups") or []),
            app_port_profile_names=profiles,
        ))
    return out


# ---------------------------------------------------------------------------
#  Public entry point
# ---------------------------------------------------------------------------

async def read_edge_spec(
    vcd: VCDClient,
    org_name: str,
    vdc_name: str,
    vdc_id: str,
    edge_id: str,
    edge_name: str | None = None,
) -> DeploymentSpec:
    """Read one edge gateway on ``vcd`` into a cloud-independent spec.

    The returned spec still carries the *source* target block; retarget it
    with ``retarget`` before rendering HCL for another cloud.
    """
    try:
        ip_sets = await read_ip_sets(vcd, edge_id)
        profiles, profile_names = await read_app_port_profiles(vcd, org_name)
        nat_rules = await read_nat_rules(vcd, edge_id, profile_names)
        static_routes = await read_static_routes(vcd, edge_id)
        ip_set_names = {s.name: s.name for s in ip_sets}
        firewall_rules = await read_firewall_rules(
            vcd, edge_id, ip_set_names, profile_names
        )
    except Exception as exc:
        logger.error(
            "edge read failed cloud=%s edge=%s: %s", vcd.cache_scope, edge_id, exc
        )
        raise EdgeReadError(f"Could not read edge {edge_id}: {exc}") from exc

    spec = DeploymentSpec(
        target=TargetSpec(
            org=org_name,
            vdc=vdc_name,
            vdc_id=vdc_id,
            edge_id=edge_id,
            edge_name=edge_name,
        ),
        ip_sets=ip_sets,
        app_port_profiles=profiles,
        firewall_rules=firewall_rules,
        nat_rules=nat_rules,
        static_routes=static_routes,
    )
    logger.info(
        "edge read cloud=%s edge=%s ip_sets=%d profiles=%d fw=%d nat=%d routes=%d",
        vcd.cache_scope, edge_id, len(ip_sets), len(profiles),
        len(firewall_rules), len(nat_rules), len(static_routes),
    )
    return spec


def retarget(spec: DeploymentSpec, target: TargetSpec) -> DeploymentSpec:
    """Return a copy of ``spec`` aimed at a different edge gateway.

    Only the target block changes — every resource inside refers to things
    by name, so nothing else needs rewriting.
    """
    return spec.model_copy(update={"target": target}, deep=True)
