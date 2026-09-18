"""Cloud-to-cloud migration: NSX-T edge on one VCD → NSX-T edge on another.

Distinct from ``migration.py``, which translates NSX-V (XML, legacy VCD)
into NSX-T.  Here both ends already speak NSX-T, so nothing is translated:
we read the source edge into a ``DeploymentSpec``, point that spec at the
destination edge, and render HCL with the same builder the editor uses.

The two clouds are ``primary`` (``VCD_*``) and ``secondary``
(``SECONDARY_VCD_*``).  Either may be the source or the destination.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.auth import AuthenticatedUser, require_roles
from app.config import settings
from app.core.deployment_builder import build_hcl, summary_from_spec
from app.core.edge_reader import EdgeReadError, read_edge_spec, retarget
from app.core.ip_remap import apply_mapping, collect_addresses
from app.integrations.vcd_client import PRIMARY, SECONDARY, get_vcd_client
from app.schemas.deployment_spec import DeploymentSpec, TargetSpec

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cloud-migration", tags=["cloud-migration"])

_READ_ROLES = require_roles("tf-admin", "tf-operator", "tf-viewer")
_WRITE_ROLES = require_roles("tf-admin", "tf-operator")


# ---------------------------------------------------------------------------
#  Schemas
# ---------------------------------------------------------------------------

class CloudInfo(BaseModel):
    id: str
    label: str
    url: str
    configured: bool


class CloudList(BaseModel):
    items: list[CloudInfo]


class PreviewRequest(BaseModel):
    """Everything needed to read one edge and aim it at another."""

    source_cloud: str = Field(..., pattern=f"^({PRIMARY}|{SECONDARY})$")
    source_org: str = Field(..., min_length=1)
    source_vdc: str = Field("", description="Display only — not used for reading")
    source_vdc_id: str = Field("", description="Display only — not used for reading")
    source_edge_id: str = Field(..., min_length=1)
    source_edge_name: str | None = None

    target_cloud: str = Field(..., pattern=f"^({PRIMARY}|{SECONDARY})$")
    target_org: str = Field(..., min_length=1)
    target_vdc: str = Field(..., min_length=1)
    target_vdc_id: str = Field(..., min_length=1)
    target_edge_id: str = Field(..., min_length=1)
    target_edge_name: str | None = None

    ip_mapping: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Old address -> new address. The destination cloud allocates its "
            "own public IPs, so NAT rules and IP sets naming the source "
            "address have to be rewritten."
        ),
    )

    @model_validator(mode="after")
    def _check_distinct(self) -> "PreviewRequest":
        if self.source_cloud == self.target_cloud and (
            self.source_edge_id == self.target_edge_id
        ):
            raise ValueError("Source and destination are the same edge on the same cloud")
        return self


class AddressUse(BaseModel):
    address: str
    kind: str
    occurrences: int
    used_by: list[str]


class PreviewResponse(BaseModel):
    hcl: str
    summary: dict
    warnings: list[str]
    spec: DeploymentSpec
    # Addresses found in the source, so the UI can offer a remap table
    # instead of making someone grep the generated HCL.
    addresses: list[AddressUse]


# ---------------------------------------------------------------------------
#  Endpoints
# ---------------------------------------------------------------------------

@router.get("/clouds", response_model=CloudList)
async def list_clouds(
    user: AuthenticatedUser = Depends(_READ_ROLES),  # noqa: ARG001
) -> CloudList:
    """Which clouds this installation can talk to.

    The secondary is reported even when unconfigured so the UI can explain
    why it is greyed out instead of silently hiding it.
    """
    items = [
        CloudInfo(
            id=PRIMARY,
            label="Primary VCD",
            url=settings.vcd_url,
            configured=bool(settings.vcd_url),
        ),
        CloudInfo(
            id=SECONDARY,
            label=settings.secondary_vcd_label,
            url=settings.secondary_vcd_url,
            configured=bool(settings.secondary_vcd_url),
        ),
    ]
    return CloudList(items=items)


def _collect_warnings(spec: DeploymentSpec) -> list[str]:
    """Things that will not survive the trip, surfaced before apply.

    Names are the join key across clouds, so anything nameless or
    referring to a profile we could not name is a real risk, not noise.
    """
    warnings: list[str] = []

    known_profiles = {p.name for p in spec.app_port_profiles}
    known_ip_sets = {s.name for s in spec.ip_sets}
    # Platform profiles are referenced through a data source rather than
    # recreated, so they are expected — but only if the destination has one
    # by the same name, which is worth saying out loud once.
    platform_profiles = {
        p.name for p in spec.app_port_profiles if p.scope != "TENANT"
    }
    if platform_profiles:
        warnings.append(
            "Looked up on the destination by name, not copied: "
            + ", ".join(sorted(platform_profiles))
            + ". The apply fails if the destination has no profile so named."
        )

    for r in spec.nat_rules:
        if not r.name:
            warnings.append("A NAT rule has no name — it cannot be matched on the destination")
        if r.app_port_profile_name and r.app_port_profile_name not in known_profiles:
            warnings.append(
                f"NAT rule {r.name!r} points at app port profile "
                f"{r.app_port_profile_name!r}, which was not found on the source — "
                "the rule would be created with no port restriction at all"
            )

    for r in spec.firewall_rules:
        for ref in r.source_ip_set_names + r.destination_ip_set_names:
            if ref not in known_ip_sets:
                warnings.append(
                    f"Firewall rule {r.name!r} references IP set {ref!r} "
                    "that was not read from the source edge"
                )
        for ref in r.app_port_profile_names:
            if ref not in known_profiles:
                warnings.append(
                    f"Firewall rule {r.name!r} references app port profile {ref!r}, "
                    "which was not found on the source — the rule would be created "
                    "without that port restriction"
                )

    if not any([spec.ip_sets, spec.nat_rules, spec.firewall_rules, spec.static_routes]):
        warnings.append("The source edge has no NAT, firewall, IP sets or static routes")

    # De-duplicate while keeping order — the same profile can trip many rules.
    seen: set[str] = set()
    return [w for w in warnings if not (w in seen or seen.add(w))]


@router.post("/preview", response_model=PreviewResponse)
async def preview(
    body: PreviewRequest,
    user: AuthenticatedUser = Depends(_WRITE_ROLES),
) -> PreviewResponse:
    """Read the source edge and render HCL aimed at the destination edge."""
    logger.info(
        "user=%s action=cloud_migration_preview src_cloud=%s src_edge=%s "
        "dst_cloud=%s dst_edge=%s ip_remaps=%d",
        user.username, body.source_cloud, body.source_edge_id,
        body.target_cloud, body.target_edge_id, len(body.ip_mapping),
    )

    try:
        source = get_vcd_client(body.source_cloud)
        get_vcd_client(body.target_cloud)  # fail early if destination is unconfigured
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        spec = await read_edge_spec(
            source,
            org_name=body.source_org,
            vdc_name=body.source_vdc,
            vdc_id=body.source_vdc_id,
            edge_id=body.source_edge_id,
            edge_name=body.source_edge_name,
        )
    except EdgeReadError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    # Addresses are reported from the source, before any rewriting, so the
    # table the operator sees matches what is actually on the source edge.
    addresses = collect_addresses(spec)

    try:
        spec = apply_mapping(spec, body.ip_mapping)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    aimed = retarget(spec, TargetSpec(
        org=body.target_org,
        vdc=body.target_vdc,
        vdc_id=body.target_vdc_id,
        edge_id=body.target_edge_id,
        edge_name=body.target_edge_name,
    ))

    hcl = build_hcl(aimed)
    # summary_from_spec() does not count IP sets — they matter here because
    # firewall rules reference them by name across clouds.
    summary = {**summary_from_spec(aimed), "ip_sets_total": len(aimed.ip_sets)}
    warnings = _collect_warnings(aimed)
    unmapped = [
        a["address"] for a in addresses
        if a["kind"] == "external" and a["address"] not in body.ip_mapping
    ]
    if unmapped:
        warnings.insert(0, (
            "Public address still pointing at the source cloud: "
            + ", ".join(unmapped)
            + ". The destination does not own it, so those NAT rules will not work."
        ))

    return PreviewResponse(
        hcl=hcl,
        summary=summary,
        warnings=warnings,
        spec=aimed,
        addresses=[AddressUse(**a) for a in addresses],
    )
