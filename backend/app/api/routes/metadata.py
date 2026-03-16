import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import AuthenticatedUser, require_roles
from app.integrations.vcd_client import vcd_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metadata", tags=["metadata"])

# All metadata endpoints are read-only — any authenticated role may access.
_any_role = require_roles("tf-admin", "tf-operator", "tf-viewer")


@router.get("/organizations")
async def list_organizations(user: AuthenticatedUser = Depends(_any_role)):
    """Return all VCD organisations (cached 5 min)."""
    try:
        orgs = await vcd_client.get_organizations()
    except Exception as exc:
        logger.error("VCD API error: %s", exc)
        raise HTTPException(status_code=502, detail="VCD API is unavailable. Try again later.")
    return {"items": orgs, "count": len(orgs)}


@router.get("/provider-vdcs")
async def list_provider_vdcs(user: AuthenticatedUser = Depends(_any_role)):
    """Return available Provider VDCs."""
    try:
        pvdcs = await vcd_client.get_provider_vdcs()
    except Exception as exc:
        logger.error("VCD API error: %s", exc)
        raise HTTPException(status_code=502, detail="VCD API is unavailable. Try again later.")
    return {"items": pvdcs, "count": len(pvdcs)}


@router.get("/storage-profiles")
async def list_storage_profiles(pvdc: str | None = Query(None), user: AuthenticatedUser = Depends(_any_role)):
    """Return storage profiles, optionally filtered by provider VDC."""
    try:
        profiles = await vcd_client.get_storage_profiles(pvdc=pvdc)
    except Exception as exc:
        logger.error("VCD API error: %s", exc)
        raise HTTPException(status_code=502, detail="VCD API is unavailable. Try again later.")
    return {"items": profiles, "count": len(profiles)}


@router.get("/vdcs")
async def list_vdcs(org: str | None = Query(None), user: AuthenticatedUser = Depends(_any_role)):
    """Return VDCs, optionally filtered by org name."""
    try:
        vdcs = await vcd_client.get_vdcs(org_name=org)
    except Exception as exc:
        logger.error("VCD API error: %s", exc)
        raise HTTPException(status_code=502, detail="VCD API is unavailable. Try again later.")
    return {"items": vdcs, "count": len(vdcs)}


@router.get("/edge-gateways")
async def list_edge_gateways(
    org: str | None = Query(None),
    vdc: str | None = Query(None),
    user: AuthenticatedUser = Depends(_any_role),
):
    """Return Edge Gateways, optionally filtered by org and/or vdc."""
    try:
        edges = await vcd_client.get_edge_gateways(org_name=org, vdc_name=vdc)
    except Exception as exc:
        logger.error("VCD API error: %s", exc)
        raise HTTPException(status_code=502, detail="VCD API is unavailable. Try again later.")
    return {"items": edges, "count": len(edges)}


@router.get("/network-pools")
async def list_network_pools(pvdc: str | None = Query(None), user: AuthenticatedUser = Depends(_any_role)):
    """Return network pools, optionally filtered by provider VDC name."""
    try:
        pools = await vcd_client.get_network_pools(pvdc=pvdc)
    except Exception as exc:
        logger.error("VCD API error: %s", exc)
        raise HTTPException(status_code=502, detail="VCD API is unavailable. Try again later.")
    return {"items": pools, "count": len(pools)}


@router.get("/external-networks")
async def list_external_networks(user: AuthenticatedUser = Depends(_any_role)):
    """Return external networks available for Edge Gateway uplinks."""
    try:
        nets = await vcd_client.get_external_networks()
    except Exception as exc:
        logger.error("VCD API error: %s", exc)
        raise HTTPException(status_code=502, detail="VCD API is unavailable. Try again later.")
    return {"items": nets, "count": len(nets)}
