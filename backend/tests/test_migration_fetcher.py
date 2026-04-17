"""Tests for app.migration.fetcher — legacy VCD XML fetcher with OAuth auth."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.migration.fetcher import LegacyVcdFetcher


# -----------------------------------------------------------------------
#  Fixtures & helpers
# -----------------------------------------------------------------------


@pytest.fixture
def fetcher():
    return LegacyVcdFetcher(
        host="https://vcd01.t-cloud.kz",
        api_token="test-refresh-token",
    )


def _make_response(
    status_code: int = 200,
    text: str = "<xml/>",
    headers: dict | None = None,
    json_data: dict | None = None,
) -> AsyncMock:
    """Create a mock httpx.Response."""
    resp = AsyncMock()
    resp.status_code = status_code
    resp.text = text
    resp.headers = headers or {}
    resp.json = MagicMock(return_value=json_data or {})
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    return resp


def _make_login_response(
    access_token: str = "bearer-token-123",
    expires_in: int = 3600,
) -> AsyncMock:
    """Create a mock OAuth token exchange response."""
    return _make_response(
        json_data={"access_token": access_token, "expires_in": expires_in},
    )


def _make_async_client():
    """Create a mock httpx.AsyncClient context manager."""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=_make_response())
    client.get = AsyncMock(return_value=_make_response())
    return client


# -----------------------------------------------------------------------
#  Init
# -----------------------------------------------------------------------


class TestLegacyVcdFetcherInit:
    def test_host_trailing_slash_stripped(self):
        f = LegacyVcdFetcher("https://vcd.test/", "tok")
        assert f._base == "https://vcd.test"

    def test_default_api_version(self):
        f = LegacyVcdFetcher("https://vcd.test", "tok")
        assert f._api_version == "36.3"

    def test_custom_api_version(self):
        f = LegacyVcdFetcher("https://vcd.test", "tok", api_version="37.0")
        assert f._api_version == "37.0"

    def test_initial_token_is_none(self):
        f = LegacyVcdFetcher("https://vcd.test", "tok")
        assert f._bearer_token is None

    def test_default_verify_ssl_false(self):
        f = LegacyVcdFetcher("https://vcd.test", "tok")
        assert f._verify_ssl is False

    def test_custom_verify_ssl(self):
        f = LegacyVcdFetcher("https://vcd.test", "tok", verify_ssl=True)
        assert f._verify_ssl is True


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
#  Login (OAuth token exchange)
# -----------------------------------------------------------------------


class TestLegacyVcdFetcherLogin:
    async def test_login_extracts_access_token_from_json(self, fetcher):
        login_resp = _make_login_response(access_token="abc-token-123")
        mock_client = _make_async_client()
        mock_client.post = AsyncMock(return_value=login_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            await fetcher.login()

        assert fetcher._bearer_token == "abc-token-123"

    async def test_login_url_uses_oauth_endpoint(self, fetcher):
        login_resp = _make_login_response()
        mock_client = _make_async_client()
        mock_client.post = AsyncMock(return_value=login_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            await fetcher.login()

        call_args = mock_client.post.call_args
        url = call_args[0][0] if call_args[0] else call_args[1]["url"]
        assert url == "https://vcd01.t-cloud.kz/oauth/provider/token"

    async def test_login_sends_form_encoded_refresh_token(self, fetcher):
        login_resp = _make_login_response()
        mock_client = _make_async_client()
        mock_client.post = AsyncMock(return_value=login_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            await fetcher.login()

        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["data"]["grant_type"] == "refresh_token"
        assert call_kwargs["data"]["refresh_token"] == "test-refresh-token"

    async def test_login_accept_header_json(self, fetcher):
        login_resp = _make_login_response()
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

    async def test_login_sets_token_expiry_from_response(self, fetcher):
        login_resp = _make_login_response(expires_in=7200)
        mock_client = _make_async_client()
        mock_client.post = AsyncMock(return_value=login_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            await fetcher.login()

        assert fetcher._token_expires_at > 0

    async def test_login_missing_access_token_raises(self, fetcher):
        resp = _make_response(json_data={"token_type": "bearer"})
        mock_client = _make_async_client()
        mock_client.post = AsyncMock(return_value=resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="access_token"):
                await fetcher.login()

    async def test_login_url_strips_path(self):
        """Token URL should use scheme+netloc only, stripping any path."""
        f = LegacyVcdFetcher("https://vcd.test/tenant/org1", "tok")
        login_resp = _make_login_response()
        mock_client = _make_async_client()
        mock_client.post = AsyncMock(return_value=login_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            await f.login()

        url = mock_client.post.call_args[0][0]
        assert url == "https://vcd.test/oauth/provider/token"


# -----------------------------------------------------------------------
#  _get_xml
# -----------------------------------------------------------------------


class TestLegacyVcdFetcherGetXml:
    async def test_get_xml_returns_text(self, fetcher):
        fetcher._bearer_token = "tok"
        fetcher._token_expires_at = 9999999999

        xml_resp = _make_response(text="<firewall><enabled>true</enabled></firewall>")
        mock_client = _make_async_client()
        mock_client.get = AsyncMock(return_value=xml_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            result = await fetcher._get_xml("/network/edges/123/firewall/config")

        assert result == "<firewall><enabled>true</enabled></firewall>"

    async def test_get_xml_constructs_full_url(self, fetcher):
        fetcher._bearer_token = "tok"
        fetcher._token_expires_at = 9999999999

        mock_client = _make_async_client()

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            await fetcher._get_xml("/network/edges/abc/firewall/config")

        call_args = mock_client.get.call_args
        url = call_args[0][0] if call_args[0] else call_args[1]["url"]
        assert url == "https://vcd01.t-cloud.kz/network/edges/abc/firewall/config"

    async def test_get_xml_raises_on_error(self, fetcher):
        fetcher._bearer_token = "tok"
        fetcher._token_expires_at = 9999999999

        error_resp = _make_response(status_code=404)
        mock_client = _make_async_client()
        mock_client.get = AsyncMock(return_value=error_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await fetcher._get_xml("/bad/path")

    async def test_get_xml_retry_on_401(self, fetcher):
        fetcher._bearer_token = "old-tok"
        fetcher._token_expires_at = 9999999999

        # First GET returns 401, login refreshes, second GET succeeds
        resp_401 = _make_response(status_code=401)
        resp_401.raise_for_status = MagicMock()  # No-op for 401 check
        resp_ok = _make_response(text="<ok/>")
        login_resp = _make_login_response(access_token="new-tok")

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
        fetcher._token_expires_at = 9999999999

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
        fetcher._token_expires_at = 9999999999

        mock_client = _make_async_client()
        mock_client.get = AsyncMock(return_value=_make_response(text="<xml/>"))

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            await fetcher.fetch_edge_snapshot("b6b3181a")

        urls = [call[0][0] for call in mock_client.get.call_args_list]
        assert any("/api/admin/edgeGateway/b6b3181a" in u for u in urls)
        assert any("/network/edges/b6b3181a/firewall/config" in u for u in urls)
        assert any("/network/edges/b6b3181a/nat/config" in u for u in urls)
        assert any("/network/edges/b6b3181a/routing/config" in u for u in urls)

    async def test_auto_login_if_no_token(self, fetcher):
        assert fetcher._bearer_token is None

        login_resp = _make_login_response(access_token="fresh-tok")
        xml_resp = _make_response(text="<data/>")

        mock_client = _make_async_client()
        mock_client.post = AsyncMock(return_value=login_resp)
        mock_client.get = AsyncMock(return_value=xml_resp)

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            result = await fetcher.fetch_edge_snapshot("uuid-1")

        assert mock_client.post.called
        assert fetcher._bearer_token == "fresh-tok"
        assert all(v == "<data/>" for v in result.values())

    async def test_all_values_are_strings(self, fetcher):
        fetcher._bearer_token = "tok"
        fetcher._token_expires_at = 9999999999

        mock_client = _make_async_client()
        mock_client.get = AsyncMock(return_value=_make_response(text="<test/>"))

        with patch("app.migration.fetcher.httpx.AsyncClient", return_value=mock_client):
            result = await fetcher.fetch_edge_snapshot("uuid")

        for key, value in result.items():
            assert isinstance(key, str)
            assert isinstance(value, str)

    async def test_ssl_verification_disabled(self, fetcher):
        fetcher._bearer_token = "tok"
        fetcher._token_expires_at = 9999999999

        with patch("app.migration.fetcher.httpx.AsyncClient") as MockClient:
            mock_instance = _make_async_client()
            mock_instance.get = AsyncMock(return_value=_make_response(text="<xml/>"))
            MockClient.return_value = mock_instance

            await fetcher.fetch_edge_snapshot("uuid")

            call_kwargs = MockClient.call_args[1]
            assert call_kwargs.get("verify") is False
