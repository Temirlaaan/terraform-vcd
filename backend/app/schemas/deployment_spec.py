"""Clean rule-spec used by the manual deployment editor.

Shape is UI-friendly: rules reference IP sets and app port profiles by
their ``name`` (not by VCD URN), so the FE can edit without dealing with
Terraform/VCD IDs. The builder that turns this spec into HCL is
responsible for resolving names → resource references.

The same shape is also produced by
``app.core.deployment_spec_from_state.parse_state`` so an existing
deployment can be opened for editing with all current rules pre-filled.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _first_duplicate(names: list[str]) -> str | None:
    seen: set[str] = set()
    for n in names:
        if n in seen:
            return n
        seen.add(n)
    return None


class TargetSpec(BaseModel):
    # Migration-created deployments can carry empty vdc_id (never populated
    # by the original flow); the editor fills it in as soon as the target
    # picker resolves a VDC. Only edge_id is strictly required at
    # HCL-build time.
    org: str = ""
    vdc: str = ""
    vdc_id: str = ""
    edge_id: str = ""
    edge_name: str | None = None


class IpSetSpec(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    ip_addresses: list[str] = Field(default_factory=list)


class AppPortEntry(BaseModel):
    protocol: Literal["TCP", "UDP", "ICMPv4", "ICMPv6"] = "TCP"
    ports: list[str] = Field(default_factory=list)


class AppPortProfileSpec(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    scope: Literal["TENANT", "PROVIDER", "SYSTEM"] = "TENANT"
    app_ports: list[AppPortEntry] = Field(default_factory=list)


class FirewallRuleSpec(BaseModel):
    name: str = Field(..., min_length=1)
    action: Literal["ALLOW", "DROP", "REJECT"] = "ALLOW"
    direction: Literal["IN", "OUT", "IN_OUT"] = "IN_OUT"
    ip_protocol: Literal["IPV4", "IPV6", "IPV4_IPV6"] = "IPV4"
    enabled: bool = True
    logging: bool = False
    source_ip_set_names: list[str] = Field(default_factory=list)
    destination_ip_set_names: list[str] = Field(default_factory=list)
    app_port_profile_names: list[str] = Field(default_factory=list)


class NatRuleSpec(BaseModel):
    name: str = Field(..., min_length=1)
    rule_type: Literal["DNAT", "SNAT", "REFLEXIVE", "NO_DNAT", "NO_SNAT"] = "DNAT"
    description: str = ""
    external_address: str = ""
    internal_address: str = ""
    dnat_external_port: str = ""
    snat_destination_address: str = ""
    app_port_profile_name: str | None = None
    enabled: bool = True
    logging: bool = False
    priority: int = 0
    firewall_match: Literal[
        "MATCH_INTERNAL_ADDRESS", "MATCH_EXTERNAL_ADDRESS", "BYPASS"
    ] = "MATCH_INTERNAL_ADDRESS"


class NextHopSpec(BaseModel):
    ip_address: str
    admin_distance: int = 1


class StaticRouteSpec(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    network_cidr: str
    next_hops: list[NextHopSpec] = Field(default_factory=list)


class DeploymentSpec(BaseModel):
    """Full editable deployment config.

    Produced by the state parser for prefill, and consumed by the HCL
    builder (see phase 6.2) to regenerate main.tf. Order of entries is
    preserved so the UI list is stable across reloads.
    """

    target: TargetSpec
    ip_sets: list[IpSetSpec] = Field(default_factory=list)
    app_port_profiles: list[AppPortProfileSpec] = Field(default_factory=list)
    firewall_rules: list[FirewallRuleSpec] = Field(default_factory=list)
    nat_rules: list[NatRuleSpec] = Field(default_factory=list)
    static_routes: list[StaticRouteSpec] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _unique_names(self) -> "DeploymentSpec":
        """Names must be unique per category.

        VCD enforces unique names per scope for ip sets and app port
        profiles; firewall and nat rule names must also be unique for
        predictable Terraform address slugs. Rules referencing a
        duplicated name would pick one of the two arbitrarily after
        ``_slug`` renames the second to ``name_2`` — a silent
        correctness bug. Reject on save instead.
        """
        for field, label in [
            ("ip_sets", "IP set"),
            ("app_port_profiles", "App port profile"),
            ("firewall_rules", "Firewall rule"),
            ("nat_rules", "NAT rule"),
            ("static_routes", "Static route"),
        ]:
            names = [item.name for item in getattr(self, field)]
            dup = _first_duplicate(names)
            if dup is not None:
                raise ValueError(
                    f"{label} name must be unique: {dup!r} appears more than once"
                )
        return self


class EditorData(BaseModel):
    """Response body for GET /deployments/{id}/editor-data."""

    deployment_id: str
    kind: str
    has_state: bool
    spec: DeploymentSpec
