"""API routes for edge migration (NSX-V → NSX-T)."""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.auth import AuthenticatedUser, require_roles
from app.migration.fetcher import LegacyVcdFetcher
from app.migration.generator import MigrationHCLGenerator
from app.migration.normalizer import normalize_edge_snapshot
from app.schemas.migration import MigrationRequest, MigrationResponse, MigrationSummary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/migration", tags=["migration"])

_generator = MigrationHCLGenerator()


def _build_summary(normalized: dict) -> MigrationSummary:
    """Extract summary counts from normalized JSON."""
    fw = normalized.get("firewall", {})
    fw_rules = fw.get("rules", [])
    user_rules = [r for r in fw_rules if not r.get("is_system", False)]
    system_rules = [r for r in fw_rules if r.get("is_system", False)]

    nat = normalized.get("nat", {})
    profiles = nat.get("required_app_port_profiles", [])
    system_profiles = [p for p in profiles if p.get("is_system_defined", False)]

    routing = normalized.get("routing", {})

    return MigrationSummary(
        firewall_rules_total=len(fw_rules),
        firewall_rules_user=len(user_rules),
        firewall_rules_system=len(system_rules),
        nat_rules_total=len(nat.get("rules", [])),
        app_port_profiles_total=len(profiles),
        app_port_profiles_system=len(system_profiles),
        app_port_profiles_custom=len(profiles) - len(system_profiles),
        static_routes_total=len(routing.get("static_routes", [])),
    )


@router.post("/generate", response_model=MigrationResponse)
async def generate_migration_hcl(
    body: MigrationRequest,
    user: AuthenticatedUser = Depends(require_roles("tf-admin", "tf-operator")),
) -> MigrationResponse:
    """Fetch edge config from legacy VCD, normalize, and generate HCL.

    Full pipeline: fetch XML → normalize → generate HCL → return.
    """
    logger.info(
        "user=%s action=migration_generate edge_uuid=%s host=%s",
        user.username, body.edge_uuid, body.host,
    )

    # 1. Fetch raw XML from legacy VCD
    fetcher = LegacyVcdFetcher(
        host=body.host,
        user=body.user,
        password=body.password,
        verify_ssl=body.verify_ssl,
    )
    try:
        raw_xmls = await fetcher.fetch_edge_snapshot(body.edge_uuid)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 401 or status == 403:
            logger.warning("Legacy VCD auth failed: %s", status)
            raise HTTPException(
                status_code=401,
                detail="Authentication failed on legacy VCD. Check credentials.",
            )
        logger.error("Legacy VCD request failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Legacy VCD returned HTTP {status}. Check host and edge UUID.",
        )
    except httpx.ConnectError:
        logger.error("Cannot connect to legacy VCD at %s", body.host)
        raise HTTPException(
            status_code=502,
            detail=f"Cannot connect to legacy VCD at {body.host}.",
        )
    except ValueError as exc:
        logger.error("Legacy VCD login error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    # 2. Normalize XML → canonical JSON
    try:
        normalized = normalize_edge_snapshot(raw_xmls)
    except Exception as exc:
        logger.error("XML normalization failed: %s", exc)
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse edge gateway XML: {exc}",
        )

    # 3. Generate HCL
    try:
        hcl = _generator.generate(
            normalized,
            target_org=body.target_org,
            target_vdc=body.target_vdc,
            target_edge_id=body.target_edge_id,
        )
    except Exception as exc:
        logger.error("HCL generation failed: %s", exc)
        raise HTTPException(
            status_code=422,
            detail="HCL generation failed. Check normalized data.",
        )

    edge_name = normalized.get("edge", {}).get("name", "")
    summary = _build_summary(normalized)

    logger.info(
        "user=%s action=migration_generate edge_name=%s rules=%d nat=%d routes=%d",
        user.username, edge_name,
        summary.firewall_rules_user, summary.nat_rules_total, summary.static_routes_total,
    )

    return MigrationResponse(hcl=hcl, edge_name=edge_name, summary=summary)
