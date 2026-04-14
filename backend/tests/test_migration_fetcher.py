"""Tests for app.migration.fetcher — legacy VCD 10.4 XML fetcher."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.migration.fetcher import LegacyVcdFetcher


# -----------------------------------------------------------------------
#  Fixtures
# -----------------------------------------------------------------------


@pytest.fixture
def fetcher():
    return LegacyVcdFetcher(
        host="https://vcd01.t-cloud.kz",
        user="admin@System",
        password="secret",
    )


def _make_response(
    status_code: int = 200,
    text: str = "<xml/>",
    headers: dict | None = None,
) -> AsyncMock:
    """Create a mock httpx.Response."""
    resp = AsyncMock()
    resp.status_code = status_code
    resp.text = text
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    return resp


def _make_async_client(responses: list | None = None, default_response=None):
    """Create a mock httpx.AsyncClient context manager.

    If responses is provided, client.get/post return them in order.
    If default_response is provided, all calls return it.
    """
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    if responses is not None:
        client.post = AsyncMock(return_value=responses[0] if responses else _make_response())
        if len(responses) > 1:
            client.get = AsyncMock(side_effect=responses[1:])
        else:
            client.get = AsyncMock(return_value=_make_response())
    elif default_response is not None:
        client.post = AsyncMock(return_value=default_response)
        client.get = AsyncMock(return_value=default_response)
    else:
        client.post = AsyncMock(return_value=_make_response())
        client.get = AsyncMock(return_value=_make_response())

    return client


# -----------------------------------------------------------------------
#  Init
# -----------------------------------------------------------------------


class TestLegacyVcdFetcherInit:
    def test_host_trailing_slash_stripped(self):
        f = LegacyVcdFetcher("https://vcd.test/", "u", "p")
        assert f._base == "https://vcd.test"

    def test_default_api_version(self):
        f = LegacyVcdFetcher("https://vcd.test", "u", "p")
        assert f._api_version == "36.3"

    def test_custom_api_version(self):
        f = LegacyVcdFetcher("https://vcd.test", "u", "p", api_version="37.0")
        assert f._api_version == "37.0"

    def test_initial_token_is_none(self):
        f = LegacyVcdFetcher("https://vcd.test", "u", "p")
        assert f._bearer_token is None


# -----------------------------------------------------------------------
#  Headers
# -----------------------------------------------------------------------


class TestLegacyVcdFetcherHeaders:
    def test_headers_contain_xml_accept(self, fetcher):
        fetcher._bearer_token = "test-token"
        headers = fetcher._headers()
        assert "application/*+xml" in headers["Accept"]

    def test_headers_contain_bearer_token(self, fetcher):
        fetcher._bearer_token = "my-token-123"
        headers = fetcher._headers()
        assert headers["Authorization"] == "Bearer my-token-123"

    def test_headers_api_version(self, fetcher):
        fetcher._bearer_token = "t"
        headers = fetcher._headers()
        assert "36.3" in headers["Accept"]


# -----------------------------------------------------------------------
#  Login
# -----------------------------------------------------------------------


class TestLegacyVcdFetcherLogin:
    async def test_login_extracts_token_from_header(self, fetcher):
        login_resp = _make_response(
            headers={"x-vmware-vcloud-access-token": "abc-token-123"}
        )
        mock_client = _make_async_client()
        mock_client.post = AsyncMock(return_value=login_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            await fetcher.login()

        assert fetcher._bearer_token == "abc-token-123"

    async def test_login_url_constructed_correctly(self, fetcher):
        login_resp = _make_response(
            headers={"x-vmware-vcloud-access-token": "tok"}
        )
        mock_client = _make_async_client()
        mock_client.post = AsyncMock(return_value=login_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            await fetcher.login()

        call_args = mock_client.post.call_args
        url = call_args[0][0] if call_args[0] else call_args[1]["url"]
        assert url == "https://vcd01.t-cloud.kz/cloudapi/1.0.0/sessions/provider"

    async def test_login_sends_basic_auth(self, fetcher):
        login_resp = _make_response(
            headers={"x-vmware-vcloud-access-token": "tok"}
        )
        mock_client = _make_async_client()
        mock_client.post = AsyncMock(return_value=login_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            await fetcher.login()

        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs.get("auth") == ("admin@System", "secret")

    async def test_login_accept_header_json(self, fetcher):
        login_resp = _make_response(
            headers={"x-vmware-vcloud-access-token": "tok"}
        )
        mock_client = _make_async_client()
        mock_client.post = AsyncMock(return_value=login_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            await fetcher.login()

        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["headers"]["Accept"] == "application/json"

    async def test_login_failure_raises(self, fetcher):
        login_resp = _make_response(status_code=401)
        mock_client = _make_async_client()
        mock_client.post = AsyncMock(return_value=login_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await fetcher.login()

    async def test_login_sets_token_expiry(self, fetcher):
        login_resp = _make_response(
            headers={"x-vmware-vcloud-access-token": "tok"}
        )
        mock_client = _make_async_client()
        mock_client.post = AsyncMock(return_value=login_resp)

        before = time.time()
        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            await fetcher.login()

        assert fetcher._token_expires_at > before

    async def test_login_missing_token_header_raises(self, fetcher):
        login_resp = _make_response(headers={})
        mock_client = _make_async_client()
        mock_client.post = AsyncMock(return_value=login_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="token"):
                await fetcher.login()


# -----------------------------------------------------------------------
#  _get_xml
# -----------------------------------------------------------------------


class TestLegacyVcdFetcherGetXml:
    async def test_get_xml_returns_text(self, fetcher):
        fetcher._bearer_token = "tok"
        fetcher._token_expires_at = time.time() + 1000

        xml_resp = _make_response(text="<firewall><enabled>true</enabled></firewall>")
        mock_client = _make_async_client()
        mock_client.get = AsyncMock(return_value=xml_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            result = await fetcher._get_xml("/network/edges/123/firewall/config")

        assert result == "<firewall><enabled>true</enabled></firewall>"

    async def test_get_xml_constructs_full_url(self, fetcher):
        fetcher._bearer_token = "tok"
        fetcher._token_expires_at = time.time() + 1000

        mock_client = _make_async_client()

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            await fetcher._get_xml("/network/edges/abc/firewall/config")

        call_args = mock_client.get.call_args
        url = call_args[0][0] if call_args[0] else call_args[1]["url"]
        assert url == "https://vcd01.t-cloud.kz/network/edges/abc/firewall/config"

    async def test_get_xml_raises_on_error(self, fetcher):
        fetcher._bearer_token = "tok"
        fetcher._token_expires_at = time.time() + 1000

        error_resp = _make_response(status_code=404)
        mock_client = _make_async_client()
        mock_client.get = AsyncMock(return_value=error_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await fetcher._get_xml("/bad/path")

    async def test_get_xml_retry_on_401(self, fetcher):
        fetcher._bearer_token = "old-tok"
        fetcher._token_expires_at = time.time() + 1000

        # First GET returns 401, login refreshes, second GET succeeds
        resp_401 = _make_response(status_code=401)
        # Override raise_for_status to not raise on 401 (we check status_code)
        resp_401.raise_for_status = MagicMock()  # No-op for 401 check
        resp_ok = _make_response(text="<ok/>")
        login_resp = _make_response(headers={"x-vmware-vcloud-access-token": "new-tok"})

        mock_client = _make_async_client()
        mock_client.get = AsyncMock(side_effect=[resp_401, resp_ok])
        mock_client.post = AsyncMock(return_value=login_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            result = await fetcher._get_xml("/some/path")

        assert result == "<ok/>"
        assert fetcher._bearer_token == "new-tok"


# -----------------------------------------------------------------------
#  fetch_edge_snapshot
# -----------------------------------------------------------------------


class TestLegacyVcdFetcherFetchEdgeSnapshot:
    async def test_returns_four_xml_keys(self, fetcher):
        fetcher._bearer_token = "tok"
        fetcher._token_expires_at = time.time() + 1000

        mock_client = _make_async_client()
        mock_client.get = AsyncMock(return_value=_make_response(text="<xml/>"))

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            result = await fetcher.fetch_edge_snapshot("edge-uuid-123")

        assert set(result.keys()) == {
            "edge_metadata.xml",
            "firewall_config.xml",
            "nat_config.xml",
            "routing_config.xml",
        }

    async def test_correct_endpoint_paths(self, fetcher):
        fetcher._bearer_token = "tok"
        fetcher._token_expires_at = time.time() + 1000

        mock_client = _make_async_client()
        mock_client.get = AsyncMock(return_value=_make_response(text="<xml/>"))

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            await fetcher.fetch_edge_snapshot("b6b3181a")

        # Check all 4 GET calls
        urls = [call[0][0] for call in mock_client.get.call_args_list]
        assert any("/api/admin/edgeGateway/b6b3181a" in u for u in urls)
        assert any("/network/edges/b6b3181a/firewall/config" in u for u in urls)
        assert any("/network/edges/b6b3181a/nat/config" in u for u in urls)
        assert any("/network/edges/b6b3181a/routing/config" in u for u in urls)

    async def test_auto_login_if_no_token(self, fetcher):
        assert fetcher._bearer_token is None

        login_resp = _make_response(
            headers={"x-vmware-vcloud-access-token": "fresh-tok"}
        )
        xml_resp = _make_response(text="<data/>")

        mock_client = _make_async_client()
        mock_client.post = AsyncMock(return_value=login_resp)
        mock_client.get = AsyncMock(return_value=xml_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            result = await fetcher.fetch_edge_snapshot("uuid-1")

        # Login should have been called
        assert mock_client.post.called
        assert fetcher._bearer_token == "fresh-tok"
        assert all(v == "<data/>" for v in result.values())

    async def test_all_values_are_strings(self, fetcher):
        fetcher._bearer_token = "tok"
        fetcher._token_expires_at = time.time() + 1000

        mock_client = _make_async_client()
        mock_client.get = AsyncMock(return_value=_make_response(text="<test/>"))

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            result = await fetcher.fetch_edge_snapshot("uuid")

        for key, value in result.items():
            assert isinstance(key, str)
            assert isinstance(value, str)

    async def test_ssl_verification_disabled(self, fetcher):
        fetcher._bearer_token = "tok"
        fetcher._token_expires_at = time.time() + 1000

        with patch("app.migration.fetcher.httpx.AsyncClient") as MockClient:
            mock_instance = _make_async_client()
            mock_instance.get = AsyncMock(return_value=_make_response(text="<xml/>"))
            MockClient.return_value = mock_instance

            await fetcher.fetch_edge_snapshot("uuid")

            # Check that AsyncClient was created with verify=False
            call_kwargs = MockClient.call_args[1]
            assert call_kwargs.get("verify") is False
