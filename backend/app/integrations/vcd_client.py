"""Async VCD API client — read-only metadata fetching.

Uses httpx for async HTTP.  All public methods are decorated with
``@cached`` so the VCD API is not hammered on every frontend dropdown
load.  The cache TTL is 5 minutes (configurable).

VCD XML API conventions:
- Authenticate via ``POST /api/sessions`` with Basic auth.
- Pass the returned ``x-vcloud-authorization`` token on subsequent requests.
- Accept ``application/*+json`` to get JSON responses instead of XML.
"""

import logging

import httpx

from app.config import settings
from app.core.cache import cached

logger = logging.getLogger(__name__)

_JSON_ACCEPT = "application/*+json;version=38.1"
_CACHE_TTL = 300  # seconds


class VCDClient:
    """Lightweight async client for the VCD REST API."""

    def __init__(self) -> None:
        self._base = settings.vcd_url.rstrip("/")
        self._token: str | None = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _authenticate(self, client: httpx.AsyncClient) -> str:
        """POST /api/sessions — returns the session token."""
        logger.info("Authenticating to VCD API at %s", self._base)
        resp = await client.post(
            f"{self._base}/sessions",
            auth=(
                f"{settings.vcd_user}@{settings.vcd_org}",
                settings.vcd_password,
            ),
            headers={"Accept": _JSON_ACCEPT},
        )
        resp.raise_for_status()
        token = resp.headers.get("x-vcloud-authorization", "")
        self._token = token
        logger.info("VCD authentication successful")
        return token

    async def _client(self) -> httpx.AsyncClient:
        """Return a configured httpx client with a valid auth token."""
        client = httpx.AsyncClient(verify=settings.verify_ssl, timeout=30.0)
        if not self._token:
            await self._authenticate(client)
        client.headers.update(
            {
                "Accept": _JSON_ACCEPT,
                "x-vcloud-authorization": self._token or "",
            }
        )
        return client

    async def _get(self, path: str, params: dict | None = None) -> dict:
        """GET helper with automatic re-auth on 401."""
        client = await self._client()
        try:
            logger.debug("VCD GET %s params=%s", path, params)
            resp = await client.get(f"{self._base}{path}", params=params)
            if resp.status_code == 401:
                logger.warning("VCD token expired, re-authenticating")
                await self._authenticate(client)
                client.headers["x-vcloud-authorization"] = self._token or ""
                resp = await client.get(f"{self._base}{path}", params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error("VCD API error: %s %s -> %s", exc.request.method, exc.request.url, exc.response.status_code)
            raise
        finally:
            await client.aclose()

    # ------------------------------------------------------------------
    # Public read-only endpoints (all cached)
    # ------------------------------------------------------------------

    @cached(prefix="vcd:orgs", ttl=_CACHE_TTL)
    async def get_organizations(self) -> list[dict]:
        data = await self._get("/org")
        orgs: list[dict] = []
        for rec in data.get("org", data.get("record", [])):
            orgs.append(
                {
                    "name": rec.get("name", ""),
                    "display_name": rec.get("displayName", rec.get("name", "")),
                    "is_enabled": rec.get("isEnabled", True),
                }
            )
        return orgs

    @cached(prefix="vcd:vdcs", ttl=_CACHE_TTL)
    async def get_vdcs(self, org_name: str | None = None) -> list[dict]:
        params = {}
        if org_name:
            params["filter"] = f"orgName=={org_name}"
        data = await self._get(
            "/query", params={**params, "type": "orgVdc", "format": "records"}
        )
        vdcs: list[dict] = []
        for rec in data.get("record", []):
            vdcs.append(
                {
                    "name": rec.get("name", ""),
                    "org_name": rec.get("orgName", ""),
                    "allocation_model": rec.get("allocationModel"),
                    "is_enabled": rec.get("isEnabled", True),
                }
            )
        return vdcs

    @cached(prefix="vcd:edges", ttl=_CACHE_TTL)
    async def get_edge_gateways(
        self, org_name: str | None = None, vdc_name: str | None = None
    ) -> list[dict]:
        params: dict = {"type": "edgeGateway", "format": "records"}
        filters = []
        if org_name:
            filters.append(f"orgName=={org_name}")
        if vdc_name:
            filters.append(f"vdc=={vdc_name}")
        if filters:
            params["filter"] = ";".join(filters)
        data = await self._get("/query", params=params)
        edges: list[dict] = []
        for rec in data.get("record", []):
            edges.append(
                {
                    "name": rec.get("name", ""),
                    "org_name": rec.get("orgName", ""),
                    "vdc_name": rec.get("vdc", ""),
                    "gateway_type": rec.get("gatewayType"),
                }
            )
        return edges

    @cached(prefix="vcd:pvdcs", ttl=_CACHE_TTL)
    async def get_provider_vdcs(self) -> list[dict]:
        data = await self._get(
            "/query", params={"type": "providerVdc", "format": "records"}
        )
        pvdcs: list[dict] = []
        for rec in data.get("record", []):
            pvdcs.append(
                {
                    "name": rec.get("name", ""),
                    "is_enabled": rec.get("isEnabled", True),
                    "cpu_allocated_mhz": rec.get("cpuAllocationMhz"),
                    "memory_allocated_mb": rec.get("memoryAllocationMB"),
                }
            )
        return pvdcs

    @cached(prefix="vcd:storprof", ttl=_CACHE_TTL)
    async def get_storage_profiles(self, pvdc: str | None = None) -> list[dict]:
        params: dict = {"type": "providerVdcStorageProfile", "format": "records"}
        if pvdc:
            params["filter"] = f"providerVdc=={pvdc}"
        data = await self._get("/query", params=params)
        profiles: list[dict] = []
        for rec in data.get("record", []):
            profiles.append(
                {
                    "name": rec.get("name", ""),
                    "limit_mb": rec.get("storageTotalMB"),
                    "used_mb": rec.get("storageUsedMB"),
                    "is_default": rec.get("isDefault", False),
                }
            )
        return profiles

    @cached(prefix="vcd:extnet", ttl=_CACHE_TTL)
    async def get_external_networks(self) -> list[dict]:
        data = await self._get(
            "/query", params={"type": "externalNetwork", "format": "records"}
        )
        nets: list[dict] = []
        for rec in data.get("record", []):
            nets.append(
                {
                    "name": rec.get("name", ""),
                    "description": rec.get("description"),
                }
            )
        return nets


# Module-level singleton.
vcd_client = VCDClient()
