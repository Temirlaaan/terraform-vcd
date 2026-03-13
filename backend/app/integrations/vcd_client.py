"""Async VCD CloudAPI client — read-only metadata fetching.

Uses the CloudAPI (``/cloudapi/1.0.0/...``) with OAuth token exchange
(``POST /oauth/provider/token``).  All public methods are decorated with
``@cached`` so the VCD API is not hammered on every frontend dropdown
load.  The cache TTL is 5 minutes.
"""

import asyncio
import logging
import time
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.core.cache import cached

logger = logging.getLogger(__name__)

_CACHE_TTL = 300  # seconds


class VCDClient:
    """Lightweight async client for the VCD CloudAPI."""

    def __init__(self) -> None:
        self._base = settings.vcd_url.rstrip("/")
        self._api_version = settings.vcd_api_version
        self._api_token = settings.vcd_api_token
        self._bearer_token: str | None = None
        self._token_expires_at: float = 0
        self._token_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Auth — OAuth token exchange
    # ------------------------------------------------------------------

    async def _get_bearer_token(
        self, client: httpx.AsyncClient, force_refresh: bool = False
    ) -> str:
        """Exchange VCD API refresh token for a short-lived Bearer token.

        Uses an asyncio.Lock to prevent concurrent token exchanges when
        multiple requests hit the client simultaneously.
        """
        async with self._token_lock:
            now = time.time()
            if (
                not force_refresh
                and self._bearer_token
                and now < self._token_expires_at - 300
            ):
                return self._bearer_token

            parts = urlparse(self._base)
            token_url = f"{parts.scheme}://{parts.netloc}/oauth/provider/token"

            logger.info("Exchanging API token for Bearer token at %s", token_url)
            resp = await client.post(
                token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._api_token,
                },
                headers={"Accept": "application/json"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            self._bearer_token = data["access_token"]
            self._token_expires_at = now + int(data.get("expires_in", 3600))
            logger.info("VCD Bearer token obtained, expires in %ss", data.get("expires_in"))
            return self._bearer_token

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": f"application/json;version={self._api_version}",
            "Authorization": f"Bearer {self._bearer_token}",
        }

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: dict | None = None) -> dict | list:
        """GET helper with automatic re-auth on 401."""
        async with httpx.AsyncClient(verify=settings.verify_ssl, timeout=30.0) as client:
            await self._get_bearer_token(client)
            url = f"{self._base}{path}"

            logger.debug("VCD GET %s params=%s", url, params)
            resp = await client.get(url, headers=self._headers(), params=params)

            if resp.status_code == 401:
                logger.warning("VCD token expired, refreshing")
                await self._get_bearer_token(client, force_refresh=True)
                resp = await client.get(url, headers=self._headers(), params=params)

            resp.raise_for_status()
            return resp.json()

    async def _get_paginated(
        self, path: str, params: dict | None = None, page_size: int = 128
    ) -> list[dict]:
        """Fetch all pages from a CloudAPI list endpoint."""
        all_items: list[dict] = []
        page = 1
        base_params = dict(params or {})

        while True:
            paged_params = {**base_params, "pageSize": page_size, "page": page}
            data = await self._get(path, params=paged_params)

            if isinstance(data, dict):
                items = data.get("values", [])
            elif isinstance(data, list):
                items = data
            else:
                break

            if not items:
                break

            all_items.extend(items)

            if len(items) < page_size:
                break

            page += 1
            if page > 100:
                logger.warning("Safety limit reached at page %d", page)
                break

        return all_items

    # ------------------------------------------------------------------
    # Public read-only endpoints (all cached)
    # ------------------------------------------------------------------

    @cached(prefix="vcd:orgs", ttl=_CACHE_TTL)
    async def get_organizations(self) -> list[dict]:
        items = await self._get_paginated("/cloudapi/1.0.0/orgs")
        orgs: list[dict] = []
        for rec in items:
            orgs.append(
                {
                    "name": rec.get("name", ""),
                    "display_name": rec.get("displayName", rec.get("name", "")),
                    "id": rec.get("id", ""),
                    "is_enabled": rec.get("isEnabled", True),
                }
            )
        return orgs

    @cached(prefix="vcd:pvdcs", ttl=_CACHE_TTL)
    async def get_provider_vdcs(self) -> list[dict]:
        items = await self._get_paginated("/cloudapi/1.0.0/providerVdcs")
        pvdcs: list[dict] = []
        for rec in items:
            pvdcs.append(
                {
                    "name": rec.get("name", ""),
                    "id": rec.get("id", ""),
                    "is_enabled": rec.get("isEnabled", True),
                }
            )
        return pvdcs

    @cached(prefix="vcd:vdcs", ttl=_CACHE_TTL)
    async def get_vdcs(self, org_name: str | None = None) -> list[dict]:
        params = {}
        if org_name:
            params["filter"] = f"(orgName=={org_name})"
        items = await self._get_paginated("/cloudapi/1.0.0/vdcs", params=params)
        vdcs: list[dict] = []
        for rec in items:
            org = rec.get("org", {})
            vdcs.append(
                {
                    "name": rec.get("name", ""),
                    "id": rec.get("id", ""),
                    "org_name": org.get("name", ""),
                    "allocation_model": rec.get("allocationModel"),
                    "is_enabled": rec.get("isEnabled", True),
                }
            )
        return vdcs

    @cached(prefix="vcd:edges", ttl=_CACHE_TTL)
    async def get_edge_gateways(
        self, org_name: str | None = None, vdc_name: str | None = None
    ) -> list[dict]:
        params = {}
        filters = []
        if org_name:
            filters.append(f"orgName=={org_name}")
        if vdc_name:
            filters.append(f"orgVdc.name=={vdc_name}")
        if filters:
            params["filter"] = f"({';'.join(filters)})"
        items = await self._get_paginated("/cloudapi/1.0.0/edgeGateways", params=params)
        edges: list[dict] = []
        for rec in items:
            org_vdc = rec.get("orgVdc", {})
            edges.append(
                {
                    "name": rec.get("name", ""),
                    "id": rec.get("id", ""),
                    "vdc_name": org_vdc.get("name", ""),
                    "gateway_type": rec.get("gatewayType"),
                }
            )
        return edges

    @cached(prefix="vcd:storprof", ttl=_CACHE_TTL)
    async def get_storage_profiles(self, pvdc: str | None = None) -> list[dict]:
        params: dict = {}
        if pvdc:
            params["filter"] = f"(providerVdc=={pvdc})"
        items = await self._get_paginated(
            "/cloudapi/1.0.0/pvdcStoragePolicies", params=params
        )
        profiles: list[dict] = []
        for rec in items:
            profiles.append(
                {
                    "name": rec.get("name", ""),
                    "id": rec.get("id", ""),
                    "is_enabled": rec.get("isEnabled", True),
                }
            )
        return profiles

    @cached(prefix="vcd:extnet", ttl=_CACHE_TTL)
    async def get_external_networks(self) -> list[dict]:
        items = await self._get_paginated("/cloudapi/1.0.0/externalNetworks")
        nets: list[dict] = []
        for rec in items:
            nets.append(
                {
                    "name": rec.get("name", ""),
                    "id": rec.get("id", ""),
                    "description": rec.get("description"),
                }
            )
        return nets


# Module-level singleton.
vcd_client = VCDClient()
