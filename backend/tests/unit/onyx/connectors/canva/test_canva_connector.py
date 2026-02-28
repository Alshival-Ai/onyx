from __future__ import annotations

import time
from unittest.mock import MagicMock
from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.parse import urlparse

from onyx.connectors.canva.connector import CanvaConnector


def test_canva_oauth_authorization_url_uses_pkce() -> None:
    with patch("onyx.connectors.canva.connector.CANVA_CLIENT_ID", "canva-client-id"):
        additional_kwargs = CanvaConnector.augment_oauth_additional_kwargs({})
        auth_url = CanvaConnector.oauth_authorization_url(
            base_domain="https://example.com",
            state="test-state",
            additional_kwargs=additional_kwargs,
        )

    parsed = urlparse(auth_url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "www.canva.com"
    assert query["client_id"] == ["canva-client-id"]
    assert query["response_type"] == ["code"]
    assert query["state"] == ["test-state"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["design:meta:read folder:read"]
    assert query["redirect_uri"] == ["https://example.com/connector/oauth/callback/canva"]
    assert query["code_challenge"][0]


def test_canva_oauth_code_to_token_formats_expiration() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "design:meta:read folder:read",
    }

    with (
        patch("onyx.connectors.canva.connector.CANVA_CLIENT_ID", "canva-client-id"),
        patch(
            "onyx.connectors.canva.connector.CANVA_CLIENT_SECRET",
            "canva-client-secret",
        ),
        patch(
            "onyx.connectors.canva.connector.request_with_retries",
            return_value=mock_response,
        ) as mock_request_with_retries,
    ):
        before = int(time.time())
        token_data = CanvaConnector.oauth_code_to_token(
            base_domain="https://example.com",
            code="auth-code",
            additional_kwargs={"code_verifier": "verifier"},
        )
        after = int(time.time())

    assert token_data["access_token"] == "new-access-token"
    assert token_data["refresh_token"] == "new-refresh-token"
    assert before + 3600 <= token_data["expires_at"] <= after + 3600

    _, kwargs = mock_request_with_retries.call_args
    assert kwargs["method"] == "POST"
    assert kwargs["url"] == "https://api.canva.com/rest/v1/oauth/token"
    assert kwargs["data"]["grant_type"] == "authorization_code"
    assert kwargs["data"]["code"] == "auth-code"
    assert kwargs["data"]["code_verifier"] == "verifier"


def test_canva_format_token_data_handles_string_expires_in() -> None:
    before = int(time.time())
    formatted = CanvaConnector._format_token_data(  # type: ignore[attr-defined]
        {"access_token": "t", "expires_in": "60"}
    )
    after = int(time.time())

    assert before + 60 <= formatted["expires_at"] <= after + 60


def test_canva_load_credentials_refreshes_expiring_token() -> None:
    connector = CanvaConnector()
    expired_credentials = {
        "access_token": "old-access-token",
        "refresh_token": "old-refresh-token",
        "expires_at": int(time.time()) - 10,
    }

    with patch.object(
        connector,
        "_refresh_access_token",
        return_value={
            "access_token": "fresh-access-token",
            "refresh_token": "fresh-refresh-token",
            "expires_at": int(time.time()) + 3600,
            "expires_in": 3600,
        },
    ) as mock_refresh:
        updated_credentials = connector.load_credentials(expired_credentials)

    assert mock_refresh.called
    assert updated_credentials is not None
    assert updated_credentials["access_token"] == "fresh-access-token"
    assert connector.access_token == "fresh-access-token"
    assert connector.refresh_token == "fresh-refresh-token"


def test_canva_build_document_uses_fallback_design_url() -> None:
    connector = CanvaConnector()
    document = connector._build_document_from_design(  # type: ignore[attr-defined]
        {"id": "DAGsHh12345", "title": "Brand Guide"}
    )

    assert document is not None
    assert document.sections[0].link == "https://www.canva.com/design/DAGsHh12345/view"
