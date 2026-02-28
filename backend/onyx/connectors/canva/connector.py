import base64
import hashlib
import secrets
import time
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import Any
from urllib.parse import urlencode
from urllib.parse import urlparse

from onyx.configs.app_configs import CANVA_CLIENT_ID
from onyx.configs.app_configs import CANVA_CLIENT_SECRET
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    datetime_from_utc_timestamp,
)
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_oauth_callback_uri,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import OAuthConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import TextSection
from onyx.utils.retry_wrapper import request_with_retries

_CANVA_API_BASE = "https://api.canva.com/rest/v1"
_CANVA_OAUTH_AUTHORIZE_URL = "https://www.canva.com/api/oauth/authorize"
_CANVA_TOKEN_URL = f"{_CANVA_API_BASE}/oauth/token"
_CANVA_OAUTH_SCOPE = "design:meta:read folder:read"
_TOKEN_REFRESH_BUFFER_SECONDS = 60


def _normalize_folder_id(folder_id_or_url: str) -> str:
    normalized = folder_id_or_url.strip()
    if "://" not in normalized:
        return normalized

    parsed = urlparse(normalized)
    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        return normalized

    return path_parts[-1]


def _strip_and_filter(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    return [
        _normalize_folder_id(value)
        for value in values
        if value and _normalize_folder_id(value)
    ]


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _design_fallback_url(design_id: str) -> str:
    return f"https://www.canva.com/design/{design_id}/view"


class CanvaConnector(LoadConnector, PollConnector, OAuthConnector):
    def __init__(
        self,
        folder_ids: list[str] | None = None,
        query: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.folder_ids = _dedupe_preserve_order(_strip_and_filter(folder_ids))
        self.query = query.strip() if query and query.strip() else None
        self.batch_size = batch_size
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.expires_at: int | None = None

    @classmethod
    def oauth_id(cls) -> DocumentSource:
        return DocumentSource.CANVA

    @staticmethod
    def _generate_pkce_code_verifier() -> str:
        # RFC 7636 allows 43-128 URL-safe characters.
        code_verifier = secrets.token_urlsafe(64).rstrip("=")
        if len(code_verifier) < 43:
            code_verifier += "a" * (43 - len(code_verifier))
        return code_verifier[:128]

    @staticmethod
    def _pkce_code_challenge(code_verifier: str) -> str:
        digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")

    @staticmethod
    def _basic_auth_header() -> str:
        if not CANVA_CLIENT_ID:
            raise ValueError("CANVA_CLIENT_ID environment variable must be set")
        if not CANVA_CLIENT_SECRET:
            raise ValueError("CANVA_CLIENT_SECRET environment variable must be set")

        client_credentials = f"{CANVA_CLIENT_ID}:{CANVA_CLIENT_SECRET}".encode(
            "utf-8"
        )
        return base64.b64encode(client_credentials).decode("utf-8")

    @classmethod
    def augment_oauth_additional_kwargs(
        cls,
        additional_kwargs: dict[str, str],
    ) -> dict[str, str]:
        updated_kwargs = dict(additional_kwargs)
        updated_kwargs["code_verifier"] = cls._generate_pkce_code_verifier()
        return updated_kwargs

    @classmethod
    def oauth_authorization_url(
        cls,
        base_domain: str,
        state: str,
        additional_kwargs: dict[str, str],
    ) -> str:
        if not CANVA_CLIENT_ID:
            raise ValueError("CANVA_CLIENT_ID environment variable must be set")

        code_verifier = additional_kwargs.get("code_verifier")
        if not code_verifier:
            raise ValueError("Missing PKCE code_verifier for Canva OAuth flow")

        query_params = urlencode(
            {
                "code_challenge": cls._pkce_code_challenge(code_verifier),
                "code_challenge_method": "S256",
                "scope": _CANVA_OAUTH_SCOPE,
                "response_type": "code",
                "client_id": CANVA_CLIENT_ID,
                "state": state,
                "redirect_uri": get_oauth_callback_uri(base_domain, "canva"),
            }
        )
        return f"{_CANVA_OAUTH_AUTHORIZE_URL}?{query_params}"

    @classmethod
    def oauth_code_to_token(
        cls,
        base_domain: str,
        code: str,
        additional_kwargs: dict[str, str],
    ) -> dict[str, Any]:
        code_verifier = additional_kwargs.get("code_verifier")
        if not code_verifier:
            raise ValueError("Missing PKCE code_verifier for Canva token exchange")

        response = request_with_retries(
            method="POST",
            url=_CANVA_TOKEN_URL,
            headers={
                "Authorization": f"Basic {cls._basic_auth_header()}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
                "code": code,
                "redirect_uri": get_oauth_callback_uri(base_domain, "canva"),
            },
            # Keep this flow snappy for interactive auth.
            delay=0.1,
            backoff=0,
        )

        token_data = response.json()
        return cls._format_token_data(token_data)

    @staticmethod
    def _format_token_data(token_data: dict[str, Any]) -> dict[str, Any]:
        token_data_copy = dict(token_data)
        expires_in = token_data_copy.get("expires_in")
        if isinstance(expires_in, int):
            token_data_copy["expires_at"] = int(time.time()) + expires_in
        elif isinstance(expires_in, str):
            try:
                token_data_copy["expires_at"] = int(time.time()) + int(expires_in)
            except ValueError:
                pass
        return token_data_copy

    def _refresh_access_token(self) -> dict[str, Any] | None:
        if not self.refresh_token:
            return None

        response = request_with_retries(
            method="POST",
            url=_CANVA_TOKEN_URL,
            headers={
                "Authorization": f"Basic {self._basic_auth_header()}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
            delay=0.1,
            backoff=0,
        )
        return self._format_token_data(response.json())

    def _is_access_token_expiring(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= self.expires_at - _TOKEN_REFRESH_BUFFER_SECONDS

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.access_token = (
            credentials.get("access_token") or credentials.get("canva_access_token")
        )
        self.refresh_token = credentials.get("refresh_token")

        raw_expires_at = credentials.get("expires_at")
        if isinstance(raw_expires_at, int):
            self.expires_at = raw_expires_at
        else:
            self.expires_at = None

        if not self.access_token:
            raise ConnectorMissingCredentialError("Canva")

        # Persist expires_at for older credential entries that only store expires_in.
        expires_in = credentials.get("expires_in")
        if self.expires_at is None and isinstance(expires_in, int):
            self.expires_at = int(time.time()) + expires_in
            return {
                **credentials,
                "expires_at": self.expires_at,
            }

        if self._is_access_token_expiring():
            refreshed_token_data = self._refresh_access_token()
            if refreshed_token_data:
                self.access_token = refreshed_token_data["access_token"]
                self.refresh_token = refreshed_token_data.get("refresh_token")
                self.expires_at = refreshed_token_data.get("expires_at")
                return {
                    **credentials,
                    **refreshed_token_data,
                }

        return None

    def _canva_get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.access_token:
            raise ConnectorMissingCredentialError("Canva")

        response = request_with_retries(
            method="GET",
            url=f"{_CANVA_API_BASE}{endpoint}",
            headers={"Authorization": f"Bearer {self.access_token}"},
            params=params,
        )
        return response.json()

    def _build_document_from_design(
        self,
        design: dict[str, Any],
        folder_id: str | None = None,
        folder_name: str | None = None,
    ) -> Document | None:
        design_id = design.get("id")
        if not isinstance(design_id, str) or not design_id:
            return None

        title = design.get("title")
        if not isinstance(title, str) or not title.strip():
            title = f"Canva Design {design_id}"

        design_url = design.get("url")
        urls = design.get("urls")
        if not isinstance(design_url, str) or not design_url:
            if isinstance(urls, dict):
                design_url = urls.get("view_url") or urls.get("edit_url")
        if not isinstance(design_url, str) or not design_url:
            design_url = _design_fallback_url(design_id)

        updated_at = design.get("updated_at")
        doc_updated_at = (
            datetime_from_utc_timestamp(updated_at)
            if isinstance(updated_at, int)
            else None
        )

        metadata: dict[str, str | list[str]] = {}
        if folder_id:
            metadata["folder_id"] = folder_id
        if folder_name:
            metadata["folder_name"] = folder_name

        owner = design.get("owner")
        if isinstance(owner, dict):
            owner_user_id = owner.get("user_id")
            owner_team_id = owner.get("team_id")
            if isinstance(owner_user_id, str) and owner_user_id:
                metadata["owner_user_id"] = owner_user_id
            if isinstance(owner_team_id, str) and owner_team_id:
                metadata["owner_team_id"] = owner_team_id

        text = title
        if folder_name:
            text = f"{title}\nFolder: {folder_name}"

        return Document(
            id=f"canva:design:{design_id}",
            sections=[TextSection(text=text, link=design_url)],
            source=DocumentSource.CANVA,
            semantic_identifier=title,
            title=title,
            doc_updated_at=doc_updated_at,
            metadata=metadata,
        )

    def _iter_designs(self) -> Iterator[Document]:
        if self.folder_ids:
            for folder_id in self.folder_ids:
                continuation: str | None = None
                while True:
                    params: dict[str, Any] = {
                        "item_types": "design",
                    }
                    if continuation:
                        params["continuation"] = continuation

                    page = self._canva_get(
                        endpoint=f"/folders/{folder_id}/items",
                        params=params,
                    )
                    page_items = page.get("items")
                    if not isinstance(page_items, list):
                        page_items = []

                    for item in page_items:
                        if not isinstance(item, dict):
                            continue
                        if item.get("type") != "design":
                            continue
                        design = item.get("design")
                        if not isinstance(design, dict):
                            continue
                        folder_obj = item.get("folder")
                        folder_name = (
                            folder_obj.get("name")
                            if isinstance(folder_obj, dict)
                            and isinstance(folder_obj.get("name"), str)
                            else None
                        )
                        document = self._build_document_from_design(
                            design=design,
                            folder_id=folder_id,
                            folder_name=folder_name,
                        )
                        if document:
                            yield document

                    continuation_value = page.get("continuation")
                    if not isinstance(continuation_value, str) or not continuation_value:
                        break
                    continuation = continuation_value
            return

        continuation = None
        while True:
            params: dict[str, Any] = {}
            if self.query:
                params["query"] = self.query
            if continuation:
                params["continuation"] = continuation

            page = self._canva_get(endpoint="/designs", params=params or None)
            page_items = page.get("items")
            if not isinstance(page_items, list):
                page_items = []

            for design in page_items:
                if not isinstance(design, dict):
                    continue
                document = self._build_document_from_design(design=design)
                if document:
                    yield document

            continuation_value = page.get("continuation")
            if not isinstance(continuation_value, str) or not continuation_value:
                break
            continuation = continuation_value

    @staticmethod
    def _is_in_poll_window(
        doc_updated_at: datetime | None,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> bool:
        if doc_updated_at is None:
            return False

        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
        return start_dt <= doc_updated_at <= end_dt

    def load_from_state(self) -> GenerateDocumentsOutput:
        batch: list[Document | HierarchyNode] = []
        for document in self._iter_designs():
            batch.append(document)
            if len(batch) >= self.batch_size:
                yield batch
                batch = []

        if batch:
            yield batch

    def poll_source(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> GenerateDocumentsOutput:
        batch: list[Document | HierarchyNode] = []
        for document in self._iter_designs():
            if not self._is_in_poll_window(document.doc_updated_at, start, end):
                continue

            batch.append(document)
            if len(batch) >= self.batch_size:
                yield batch
                batch = []

        if batch:
            yield batch

    def validate_connector_settings(self) -> None:
        if not self.access_token:
            raise ConnectorMissingCredentialError("Canva")

        try:
            if self.folder_ids:
                self._canva_get(
                    endpoint=f"/folders/{self.folder_ids[0]}/items",
                    params={"item_types": "design"},
                )
            else:
                self._canva_get(
                    endpoint="/designs",
                    params={"query": self.query} if self.query else None,
                )
        except Exception as e:
            raise ConnectorValidationError(f"Unable to access Canva API: {e}")
