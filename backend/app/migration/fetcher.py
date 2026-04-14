"""Fetch raw XML config from a legacy VCD 10.4 NSX-V edge gateway.

Connects to the legacy VCD provider API, authenticates via Basic Auth,
and downloads edge gateway metadata, firewall, NAT, and routing configs
as raw XML strings. These are then passed to normalizer.py for parsing.

SSL verification is disabled by default because legacy VCD instances
commonly use self-signed certificates.
"""

import logging
import time

import httpx

logger = logging.getLogger(__name__)

_SESSION_TTL = 1800  # 30 minutes — typical VCD provider session lifetime


class LegacyVcdFetcher:
    """Fetches raw XML config from a legacy VCD 10.4 NSX-V edge gateway."""

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        api_version: str = "36.3",
    ) -> None:
        self._base = host.rstrip("/")
        self._user = user
        self._password = password
        self._api_version = api_version
        self._bearer_token: str | None = None
        self._token_expires_at: float = 0

    def _headers(self) -> dict[str, str]:
        """Build request headers for XML API calls."""
        return {
            "Accept": f"application/*+xml;version={self._api_version}",
            "Authorization": f"Bearer {self._bearer_token}",
        }

    async def login(self) -> None:
        """Authenticate via POST /cloudapi/1.0.0/sessions/provider.

        Uses HTTP Basic Auth (user:password). The bearer token is returned
        in the ``x-vmware-vcloud-access-token`` response header.

        Raises:
            httpx.HTTPStatusError: If login fails (401, 403, etc.)
            ValueError: If the response does not contain a token.
        """
        login_url = f"{self._base}/cloudapi/1.0.0/sessions/provider"

        logger.info("Logging in to legacy VCD at %s", self._base)
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            resp = await client.post(
                login_url,
                auth=(self._user, self._password),
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()

        token = resp.headers.get("x-vmware-vcloud-access-token")
        if not token:
            raise ValueError(
                "Legacy VCD login succeeded but no token in response headers"
            )

        self._bearer_token = token
        self._token_expires_at = time.time() + _SESSION_TTL
        logger.info("Legacy VCD login successful")

    async def _ensure_authenticated(self) -> None:
        """Login if token is missing or expired."""
        if not self._bearer_token or time.time() >= self._token_expires_at:
            await self.login()

    async def _get_xml(self, path: str) -> str:
        """GET a VCD API path and return the raw XML response text.

        Automatically retries once on 401 by re-authenticating.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses (after retry).
        """
        url = f"{self._base}{path}"

        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            logger.debug("Legacy VCD GET %s", url)
            resp = await client.get(url, headers=self._headers())

            if resp.status_code == 401:
                logger.warning("Legacy VCD token expired, re-authenticating")
                await self.login()
                resp = await client.get(url, headers=self._headers())

            resp.raise_for_status()
            return resp.text

    async def fetch_edge_snapshot(self, edge_uuid: str) -> dict[str, str]:
        """Fetch all 4 XML documents for the given edge gateway.

        Args:
            edge_uuid: The UUID of the NSX-V edge gateway
                       (e.g. ``b6b3181a-2596-44c5-9991-c4c54c050bcb``).

        Returns:
            Dict with keys ``edge_metadata.xml``, ``firewall_config.xml``,
            ``nat_config.xml``, ``routing_config.xml`` — all raw XML strings.
        """
        await self._ensure_authenticated()

        logger.info("Fetching edge snapshot for %s", edge_uuid)

        edge_metadata = await self._get_xml(
            f"/api/admin/edgeGateway/{edge_uuid}"
        )
        firewall_config = await self._get_xml(
            f"/network/edges/{edge_uuid}/firewall/config"
        )
        nat_config = await self._get_xml(
            f"/network/edges/{edge_uuid}/nat/config"
        )
        routing_config = await self._get_xml(
            f"/network/edges/{edge_uuid}/routing/config"
        )

        logger.info("Edge snapshot fetched successfully for %s", edge_uuid)

        return {
            "edge_metadata.xml": edge_metadata,
            "firewall_config.xml": firewall_config,
            "nat_config.xml": nat_config,
            "routing_config.xml": routing_config,
        }
