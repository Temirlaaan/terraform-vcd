"""Fetch raw XML config from a legacy VCD NSX-V edge gateway.

Connects to the legacy VCD API, authenticates via OAuth token exchange
(``POST /oauth/provider/token``), and downloads edge gateway metadata,
firewall, NAT, and routing configs as raw XML strings.  These are then
passed to normalizer.py for parsing.

SSL verification is disabled by default because legacy VCD instances
commonly use self-signed certificates.
"""

import logging
import time
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class LegacyVcdFetcher:
    """Fetches raw XML config from a legacy VCD NSX-V edge gateway."""

    def __init__(
        self,
        host: str,
        api_token: str,
        api_version: str = "36.3",
        verify_ssl: bool = False,
    ) -> None:
        self._base = host.rstrip("/")
        self._api_token = api_token
        self._api_version = api_version
        self._verify_ssl = verify_ssl
        self._bearer_token: str | None = None
        self._token_expires_at: float = 0

    def _headers(self) -> dict[str, str]:
        """Build request headers for XML API calls."""
        return {
            "Accept": f"application/*+xml;version={self._api_version}",
            "Authorization": f"Bearer {self._bearer_token}",
        }

    async def login(self) -> None:
        """Exchange API refresh token for a short-lived Bearer token.

        Uses the OAuth ``/oauth/provider/token`` endpoint with
        ``grant_type=refresh_token``.  Mirrors the pattern in
        ``vcd_client.py:_get_bearer_token()``.

        Raises:
            httpx.HTTPStatusError: If token exchange fails.
            ValueError: If the response does not contain an access_token.
        """
        parts = urlparse(self._base)
        token_url = f"{parts.scheme}://{parts.netloc}/oauth/provider/token"

        logger.info("Exchanging API token at %s", token_url)
        async with httpx.AsyncClient(verify=self._verify_ssl, timeout=30.0) as client:
            resp = await client.post(
                token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._api_token,
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code >= 400:
                logger.error(
                    "Legacy VCD token exchange failed: status=%d body=%s",
                    resp.status_code, resp.text[:500],
                )
            resp.raise_for_status()

        data = resp.json()
        access_token = data.get("access_token")
        if not access_token:
            raise ValueError(
                "Legacy VCD token exchange succeeded but no access_token in response"
            )

        self._bearer_token = access_token
        self._token_expires_at = time.time() + int(data.get("expires_in", 3600))
        logger.info(
            "Legacy VCD Bearer token obtained, expires in %ss",
            data.get("expires_in"),
        )

    async def _ensure_authenticated(self) -> None:
        """Login if token is missing or about to expire (5 min safety margin)."""
        if not self._bearer_token or time.time() >= self._token_expires_at - 300:
            await self.login()

    async def _get_xml(self, path: str) -> str:
        """GET a VCD API path and return the raw XML response text.

        Automatically retries once on 401 by re-authenticating.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses (after retry).
        """
        url = f"{self._base}{path}"

        async with httpx.AsyncClient(verify=self._verify_ssl, timeout=30.0) as client:
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
