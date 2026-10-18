"""Tests del PostmarkEmailAdapter: cliente HTTP, retry, build_postmark_adapter.

PostmarkEmailAdapter es un adapter global (no per-tenant), así que los tests
verifican que las credenciales de Auyan (Settings) se usan correctamente,
que el retry funciona sobre errores transitorios, y que el factory devuelve
None cuando no hay token configurado.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from apps.api.integrations.postmark import (
    PostmarkClient,
    PostmarkEmailAdapter,
    _is_transient,
    _TransientError,
    build_postmark_adapter,
)

# ---------------------------------------------------------------------------
# _is_transient
# ---------------------------------------------------------------------------


class TestIsTransient:
    def test_timeout_is_transient(self) -> None:
        assert _is_transient(httpx.TimeoutException("timeout"))

    def test_connect_error_is_transient(self) -> None:
        assert _is_transient(httpx.ConnectError("connection refused"))

    def test_transient_error_is_transient(self) -> None:
        assert _is_transient(_TransientError("http_503"))

    def test_value_error_not_transient(self) -> None:
        assert not _is_transient(ValueError("bad input"))

    def test_http_status_error_not_transient(self) -> None:
        req = httpx.Request("POST", "https://api.postmarkapp.com/email")
        resp = httpx.Response(422, request=req)
        assert not _is_transient(httpx.HTTPStatusError("unprocessable", request=req, response=resp))


# ---------------------------------------------------------------------------
# PostmarkClient.send_email — happy path
# ---------------------------------------------------------------------------


class TestPostmarkClientSendEmail:
    @pytest.mark.asyncio
    async def test_sends_correct_payload(self) -> None:
        client = PostmarkClient(server_token="test-token")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"MessageID": "abc123", "ErrorCode": 0}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockHTTP:
            MockHTTP.return_value.__aenter__ = AsyncMock(return_value=MockHTTP.return_value)
            MockHTTP.return_value.__aexit__ = AsyncMock(return_value=None)
            MockHTTP.return_value.post = AsyncMock(return_value=mock_resp)

            result = await client.send_email(
                to="cliente@ejemplo.com",
                from_field="Auyan <noreply@auyan.ai>",
                subject="Test",
                text_body="Hola",
                html_body="<p>Hola</p>",
                tag="test",
            )

        assert result["MessageID"] == "abc123"
        call_kwargs = MockHTTP.return_value.post.call_args
        payload = call_kwargs.kwargs["json"]
        assert payload["To"] == "cliente@ejemplo.com"
        assert payload["From"] == "Auyan <noreply@auyan.ai>"
        assert payload["Subject"] == "Test"
        assert payload["TextBody"] == "Hola"
        assert payload["HtmlBody"] == "<p>Hola</p>"
        assert payload["Tag"] == "test"

    @pytest.mark.asyncio
    async def test_omits_html_body_when_none(self) -> None:
        client = PostmarkClient(server_token="tk")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockHTTP:
            MockHTTP.return_value.__aenter__ = AsyncMock(return_value=MockHTTP.return_value)
            MockHTTP.return_value.__aexit__ = AsyncMock(return_value=None)
            MockHTTP.return_value.post = AsyncMock(return_value=mock_resp)

            await client.send_email(
                to="a@b.com",
                from_field="x",
                subject="s",
                text_body="t",
            )

        payload = MockHTTP.return_value.post.call_args.kwargs["json"]
        assert "HtmlBody" not in payload
        assert "Tag" not in payload

    @pytest.mark.asyncio
    async def test_uses_correct_auth_header(self) -> None:
        client = PostmarkClient(server_token="secret-token-xyz")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as MockHTTP:
            MockHTTP.return_value.__aenter__ = AsyncMock(return_value=MockHTTP.return_value)
            MockHTTP.return_value.__aexit__ = AsyncMock(return_value=None)
            MockHTTP.return_value.post = AsyncMock(return_value=mock_resp)

            await client.send_email(to="a@b.com", from_field="f", subject="s", text_body="t")

        headers = MockHTTP.return_value.post.call_args.kwargs["headers"]
        assert headers["X-Postmark-Server-Token"] == "secret-token-xyz"

    @pytest.mark.asyncio
    async def test_retries_on_503(self) -> None:
        """Verifica que se reintenta automáticamente en errores 5xx."""
        from tenacity import wait_none

        client = PostmarkClient(server_token="tk")

        resp_503 = MagicMock()
        resp_503.status_code = 503
        resp_503.raise_for_status = MagicMock()

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"MessageID": "ok"}
        resp_200.raise_for_status = MagicMock()

        with (
            patch("httpx.AsyncClient") as MockHTTP,
            patch("apps.api.integrations.postmark.wait_exponential", return_value=wait_none()),
        ):
            MockHTTP.return_value.__aenter__ = AsyncMock(return_value=MockHTTP.return_value)
            MockHTTP.return_value.__aexit__ = AsyncMock(return_value=None)
            MockHTTP.return_value.post = AsyncMock(side_effect=[resp_503, resp_200])

            result = await client.send_email(
                to="a@b.com", from_field="f", subject="s", text_body="t"
            )

        assert result["MessageID"] == "ok"
        assert MockHTTP.return_value.post.await_count == 2


# ---------------------------------------------------------------------------
# PostmarkEmailAdapter
# ---------------------------------------------------------------------------


class TestPostmarkEmailAdapter:
    @pytest.mark.asyncio
    async def test_send_email_builds_from_field(self) -> None:
        adapter = PostmarkEmailAdapter(
            server_token="tk",
            from_email="noreply@auyan.ai",
            from_name="Auyan",
        )

        with patch.object(adapter._client, "send_email", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {}
            await adapter.send_email(
                to="user@example.com",
                subject="Hello",
                text_body="Hi",
            )

        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["from_field"] == "Auyan <noreply@auyan.ai>"

    @pytest.mark.asyncio
    async def test_send_email_no_from_name(self) -> None:
        adapter = PostmarkEmailAdapter(
            server_token="tk",
            from_email="ops@auyan.ai",
            from_name="",
        )
        with patch.object(adapter._client, "send_email", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {}
            await adapter.send_email(to="x@y.com", subject="s", text_body="t")

        from_field = mock_send.call_args.kwargs["from_field"]
        assert from_field == " <ops@auyan.ai>"

    @pytest.mark.asyncio
    async def test_passes_tag(self) -> None:
        adapter = PostmarkEmailAdapter(server_token="tk", from_email="a@b.com")
        with patch.object(adapter._client, "send_email", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {}
            await adapter.send_email(
                to="x@y.com", subject="s", text_body="t", tag="escalation-fallback"
            )
        assert mock_send.call_args.kwargs["tag"] == "escalation-fallback"


# ---------------------------------------------------------------------------
# build_postmark_adapter
# ---------------------------------------------------------------------------


class TestBuildPostmarkAdapter:
    def test_returns_none_when_no_token(self) -> None:
        settings = MagicMock()
        settings.postmark_api_token = None
        assert build_postmark_adapter(settings) is None

    def test_returns_adapter_when_token_present(self) -> None:
        settings = MagicMock()
        token_mock = MagicMock()
        token_mock.get_secret_value.return_value = "real-token"
        settings.postmark_api_token = token_mock
        settings.postmark_from_email = "noreply@auyan.ai"
        settings.postmark_from_name = "Auyan"

        adapter = build_postmark_adapter(settings)

        assert adapter is not None
        assert isinstance(adapter, PostmarkEmailAdapter)
        assert adapter._from_email == "noreply@auyan.ai"
        assert adapter._from_name == "Auyan"
        assert adapter._client._token == "real-token"

    def test_two_calls_return_different_instances(self) -> None:
        settings = MagicMock()
        token_mock = MagicMock()
        token_mock.get_secret_value.return_value = "tk"
        settings.postmark_api_token = token_mock
        settings.postmark_from_email = "a@b.com"
        settings.postmark_from_name = "A"

        a = build_postmark_adapter(settings)
        b = build_postmark_adapter(settings)
        assert a is not b
