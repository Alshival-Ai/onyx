"""Starwood productivity MCP tools (Zendesk KB + M365 inbox/calendar/OneDrive/SharePoint)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from openai import OpenAI
from sqlalchemy import select

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import OAuthAccount
from onyx.db.users import get_user_by_email
from onyx.file_processing.extract_file_text import pptx_to_text
from onyx.file_processing.extract_file_text import read_docx_file
from onyx.file_processing.extract_file_text import read_pdf_file
from onyx.file_processing.extract_file_text import xlsx_to_text
from onyx.mcp_server.api import mcp_server
from onyx.mcp_server.utils import get_http_client
from onyx.mcp_server.utils import require_access_token
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import build_api_server_url_for_http_requests

logger = setup_logger()

try:
    import chromadb
except Exception:
    chromadb = None  # type: ignore[assignment]

MS_GRAPH_BASE_URL = os.environ.get("MS_GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0")
USER_EMAIL_DATA_ROOT = os.environ.get("USER_EMAIL_DATA_ROOT", "/app/users")
ZENDESK_WIKI_CHROMA_PATH = os.environ.get(
    "ZENDESK_WIKI_CHROMA_PATH", "onyx/zendesk/chroma"
)
ZENDESK_WIKI_COLLECTION = os.environ.get(
    "ZENDESK_WIKI_COLLECTION", "zendesk_help_center"
)
ZENDESK_WIKI_EMBEDDING_MODEL = os.environ.get(
    "ZENDESK_WIKI_EMBEDDING_MODEL", "text-embedding-3-small"
)
OPENID_CONFIG_URL = os.environ.get("OPENID_CONFIG_URL")
OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID")
OAUTH_CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET")
OIDC_SCOPE_OVERRIDE = os.environ.get("OIDC_SCOPE_OVERRIDE")
_OIDC_TOKEN_ENDPOINT: str | None = None


async def _current_user_from_access_token() -> tuple[str | None, str | None, str | None]:
    """Return (user_id, user_email, error) for current MCP bearer token."""
    access_token = require_access_token()
    try:
        response = await get_http_client().get(
            f"{build_api_server_url_for_http_requests(respect_env_override_if_set=True)}/me",
            headers={"Authorization": f"Bearer {access_token.token}"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return None, None, "Unexpected /me response"

        user_id = payload.get("id")
        email = payload.get("email")
        if isinstance(user_id, str):
            try:
                user_id = str(UUID(user_id))
            except Exception:
                user_id = None
        else:
            user_id = None

        if not isinstance(email, str):
            email = None

        if not user_id and not email:
            return None, None, "Unable to resolve current user"
        return user_id, email, None
    except Exception as exc:
        logger.error("Failed to resolve current user from /me", exc_info=True)
        return None, None, f"Failed to resolve current user: {exc}"


def _ensure_db_engine_initialized() -> None:
    # no-op if already initialized
    try:
        SqlEngine.get_engine()
        return
    except Exception:
        pass

    pool_size = int(os.environ.get("POSTGRES_API_SERVER_POOL_SIZE", "40"))
    overflow = int(os.environ.get("POSTGRES_API_SERVER_POOL_OVERFLOW", "10"))
    SqlEngine.init_engine(pool_size=pool_size, max_overflow=overflow)


def _deterministic_embedding(text: str, dimension: int = 64) -> list[float]:
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    for i in range(dimension):
        byte_value = seed[i % len(seed)]
        mapped = (byte_value / 255.0) * 2.0 - 1.0
        values.append(mapped)

    norm = sum(v * v for v in values) ** 0.5
    return values if norm <= 0 else [v / norm for v in values]


def _open_user_sqlite(user_id: str) -> sqlite3.Connection | None:
    sqlite_path = Path(USER_EMAIL_DATA_ROOT) / "users" / user_id / "emails.sqlite3"
    if not sqlite_path.exists():
        return None
    conn = sqlite3.connect(str(sqlite_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _serialize_email_row(row: sqlite3.Row) -> dict[str, Any]:
    raw_json = row["raw_json"]
    parsed_raw: dict[str, Any] | None = None
    if isinstance(raw_json, str) and raw_json:
        try:
            loaded = json.loads(raw_json)
            if isinstance(loaded, dict):
                parsed_raw = loaded
        except Exception:
            parsed_raw = None

    return {
        "id": row["id"],
        "internet_message_id": row["internet_message_id"],
        "conversation_id": row["conversation_id"],
        "subject": row["subject"],
        "sender": row["sender"],
        "received_at": row["received_at"],
        "preview": row["preview"],
        "web_link": row["web_link"],
        "updated_at": row["updated_at"],
        "raw_message": parsed_raw,
    }


def _serialize_graph_message(message: dict[str, Any]) -> dict[str, Any]:
    sender = message.get("from") if isinstance(message, dict) else {}
    sender_addr = sender.get("emailAddress") if isinstance(sender, dict) else {}
    sender_name = sender_addr.get("name") if isinstance(sender_addr, dict) else ""
    sender_email = sender_addr.get("address") if isinstance(sender_addr, dict) else ""
    sender_display = (
        f"{sender_name} <{sender_email}>"
        if sender_name and sender_email
        else sender_email or sender_name
    )

    return {
        "id": message.get("id"),
        "internet_message_id": message.get("internetMessageId"),
        "conversation_id": message.get("conversationId"),
        "subject": message.get("subject"),
        "sender": sender_display,
        "received_at": message.get("receivedDateTime"),
        "preview": message.get("bodyPreview"),
        "web_link": message.get("webLink"),
        "updated_at": message.get("lastModifiedDateTime"),
        "raw_message": message,
    }


def _fetch_graph_messages(
    access_token: str,
    max_items: int = 100,
) -> tuple[list[dict[str, Any]], str | None]:
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"{MS_GRAPH_BASE_URL.rstrip('/')}/me/messages"
    params = {
        "$top": str(min(max_items, 100)),
        "$orderby": "receivedDateTime desc",
        "$select": (
            "id,internetMessageId,conversationId,subject,from,receivedDateTime,"
            "bodyPreview,webLink,lastModifiedDateTime"
        ),
    }

    messages: list[dict[str, Any]] = []
    next_url: str | None = url
    next_params: dict[str, str] | None = params
    try:
        with httpx.Client(timeout=30.0) as client:
            while next_url and len(messages) < max_items:
                response = client.get(next_url, headers=headers, params=next_params)
                if response.status_code == 401:
                    return [], "Inbox access unauthorized (401). Re-authenticate user."
                if response.status_code == 403:
                    return [], "Inbox access forbidden (403). Missing Mail.Read scope or consent."
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    break
                value = payload.get("value")
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            messages.append(item)
                            if len(messages) >= max_items:
                                break
                raw_next = payload.get("@odata.nextLink")
                if isinstance(raw_next, str) and raw_next:
                    next_url = raw_next
                    next_params = None
                else:
                    next_url = None
                    next_params = None
    except Exception as exc:
        return [], f"Unable to fetch inbox messages: {exc}"

    return messages, None


def _serialize_calendar_event(event: dict[str, Any]) -> dict[str, Any]:
    organizer = event.get("organizer") if isinstance(event, dict) else {}
    organizer_email = organizer.get("emailAddress") if isinstance(organizer, dict) else {}
    organizer_name = organizer_email.get("name") if isinstance(organizer_email, dict) else ""
    organizer_addr = organizer_email.get("address") if isinstance(organizer_email, dict) else ""
    organizer_display = (
        f"{organizer_name} <{organizer_addr}>"
        if organizer_name and organizer_addr
        else organizer_addr or organizer_name
    )
    start = event.get("start") if isinstance(event, dict) else {}
    end = event.get("end") if isinstance(event, dict) else {}
    location = event.get("location") if isinstance(event, dict) else {}
    response = event.get("responseStatus") if isinstance(event, dict) else {}
    return {
        "id": event.get("id"),
        "subject": event.get("subject"),
        "organizer": organizer_display,
        "start_at": start.get("dateTime") if isinstance(start, dict) else None,
        "end_at": end.get("dateTime") if isinstance(end, dict) else None,
        "location": location.get("displayName") if isinstance(location, dict) else None,
        "is_all_day": event.get("isAllDay"),
        "is_cancelled": event.get("isCancelled"),
        "response": response.get("response") if isinstance(response, dict) else None,
        "web_link": event.get("webLink"),
        "preview": event.get("bodyPreview"),
        "raw_event": event,
    }


def _serialize_onedrive_item(item: dict[str, Any]) -> dict[str, Any]:
    file_info = item.get("file") if isinstance(item, dict) else {}
    folder_info = item.get("folder") if isinstance(item, dict) else {}
    parent_ref = item.get("parentReference") if isinstance(item, dict) else {}
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "web_url": item.get("webUrl"),
        "size": item.get("size"),
        "last_modified_at": item.get("lastModifiedDateTime"),
        "created_at": item.get("createdDateTime"),
        "etag": item.get("eTag"),
        "ctag": item.get("cTag"),
        "is_file": isinstance(file_info, dict),
        "is_folder": isinstance(folder_info, dict),
        "mime_type": file_info.get("mimeType") if isinstance(file_info, dict) else None,
        "file_hashes": file_info.get("hashes") if isinstance(file_info, dict) else None,
        "child_count": folder_info.get("childCount") if isinstance(folder_info, dict) else None,
        "parent_path": parent_ref.get("path") if isinstance(parent_ref, dict) else None,
        "download_url": item.get("@microsoft.graph.downloadUrl"),
        "raw_item": item,
    }


def _serialize_sharepoint_site(site: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": site.get("id"),
        "name": site.get("name"),
        "display_name": site.get("displayName"),
        "web_url": site.get("webUrl"),
        "description": site.get("description"),
        "raw_site": site,
    }


def _serialize_sharepoint_drive(drive: dict[str, Any]) -> dict[str, Any]:
    owner = drive.get("owner") if isinstance(drive, dict) else {}
    owner_user = owner.get("user") if isinstance(owner, dict) else {}
    return {
        "id": drive.get("id"),
        "name": drive.get("name"),
        "description": drive.get("description"),
        "drive_type": drive.get("driveType"),
        "web_url": drive.get("webUrl"),
        "created_at": drive.get("createdDateTime"),
        "owner_email": owner_user.get("email") if isinstance(owner_user, dict) else None,
        "raw_drive": drive,
    }


def _is_probably_text_file(mime_type: str | None, name: str | None) -> bool:
    if mime_type:
        mime = mime_type.lower()
        if mime.startswith("text/"):
            return True
        if any(token in mime for token in ("json", "xml", "javascript", "yaml", "csv")):
            return True

    if name:
        lowered = name.lower()
        text_extensions = (
            ".txt",
            ".md",
            ".markdown",
            ".json",
            ".csv",
            ".tsv",
            ".xml",
            ".html",
            ".css",
            ".js",
            ".ts",
            ".py",
            ".java",
            ".go",
            ".rs",
            ".sql",
            ".yaml",
            ".yml",
            ".log",
            ".ini",
            ".toml",
            ".env",
        )
        if lowered.endswith(text_extensions):
            return True

    return False


def _extract_text_from_file_bytes(
    raw_bytes: bytes, name: str | None, mime_type: str | None
) -> tuple[str, str | None]:
    file_name = name or ""
    lowered_name = file_name.lower()
    lowered_mime = (mime_type or "").lower()

    if _is_probably_text_file(mime_type, file_name):
        return raw_bytes.decode("utf-8", errors="replace"), None

    try:
        if lowered_name.endswith(".pdf") or "application/pdf" in lowered_mime:
            text, _, _ = read_pdf_file(io.BytesIO(raw_bytes))
            return text or "", None

        if lowered_name.endswith(".docx") or (
            "officedocument.wordprocessingml.document" in lowered_mime
        ):
            text, _ = read_docx_file(io.BytesIO(raw_bytes), file_name=file_name)
            return text or "", None

        if lowered_name.endswith(".pptx") or (
            "officedocument.presentationml.presentation" in lowered_mime
        ):
            return pptx_to_text(io.BytesIO(raw_bytes), file_name=file_name) or "", None

        if lowered_name.endswith(".xlsx") or (
            "officedocument.spreadsheetml.sheet" in lowered_mime
        ):
            return xlsx_to_text(io.BytesIO(raw_bytes), file_name=file_name) or "", None
    except Exception as exc:
        return "", f"Failed to extract text from file: {exc}"

    return "", "Unsupported file type for text extraction."


async def _resolve_user_id(
    user_id: str | None, user_email: str | None
) -> tuple[str | None, str | None, str | None]:
    if user_id:
        try:
            return str(UUID(user_id)), user_email, None
        except ValueError:
            return None, None, "user_id must be a valid UUID."

    if user_email:
        _ensure_db_engine_initialized()
        with get_session_with_tenant(tenant_id="public") as db_session:
            user = get_user_by_email(user_email, db_session)
            if user is None or not user.id:
                return None, None, f"No Onyx user found for email: {user_email}"
            return str(user.id), user.email, None

    # No explicit user provided: resolve from bearer token
    return await _current_user_from_access_token()


def _resolve_user_access_token(user_id: str) -> tuple[str | None, str | None]:
    _ensure_db_engine_initialized()
    with get_session_with_tenant(tenant_id="public") as db_session:
        oauth_account = db_session.execute(
            select(OAuthAccount)
            .where(OAuthAccount.user_id == UUID(user_id))
            .order_by(OAuthAccount.id.desc())
            .limit(1)
        ).scalar_one_or_none()

        if not oauth_account:
            return None, "No OAuth access token found for user."

        access_token = oauth_account.access_token
        if not access_token:
            return None, "No OAuth access token found for user."

        expires_at = oauth_account.expires_at
        now_ts = int(datetime.now(timezone.utc).timestamp())
        # Refresh shortly before expiry to avoid mid-request failures.
        needs_refresh = isinstance(expires_at, int) and (expires_at - now_ts) < 300

        if needs_refresh and oauth_account.oauth_name == "openid":
            refreshed_token, refresh_error = _refresh_openid_oauth_account(
                oauth_account, db_session
            )
            if refreshed_token:
                return refreshed_token, None
            if isinstance(expires_at, int) and expires_at <= now_ts:
                return None, refresh_error or "OAuth token expired. Re-authenticate user."
            logger.warning(
                "OpenID token refresh failed for user_id=%s; using existing token. error=%s",
                user_id,
                refresh_error,
            )

        if isinstance(access_token, str):
            return access_token, None

        # fallback for wrapped token types
        try:
            token_str = str(access_token)
            if token_str:
                return token_str, None
        except Exception:
            pass

    return None, "Unable to read OAuth access token for user."


def _get_openid_token_endpoint() -> tuple[str | None, str | None]:
    global _OIDC_TOKEN_ENDPOINT
    if _OIDC_TOKEN_ENDPOINT:
        return _OIDC_TOKEN_ENDPOINT, None

    if not OPENID_CONFIG_URL:
        return None, "OPENID_CONFIG_URL is not configured."

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(OPENID_CONFIG_URL)
            response.raise_for_status()
            payload = response.json()
        token_endpoint = payload.get("token_endpoint")
        if not isinstance(token_endpoint, str) or not token_endpoint:
            return None, "Unable to discover OIDC token endpoint."
        _OIDC_TOKEN_ENDPOINT = token_endpoint
        return token_endpoint, None
    except Exception as exc:
        return None, f"Failed to discover OIDC token endpoint: {exc}"


def _refresh_openid_oauth_account(
    oauth_account: OAuthAccount, db_session: Any
) -> tuple[str | None, str | None]:
    if not oauth_account.refresh_token:
        return None, "No refresh token available for user."
    if not OAUTH_CLIENT_ID or not OAUTH_CLIENT_SECRET:
        return None, "OIDC client credentials are not configured."

    token_endpoint, endpoint_error = _get_openid_token_endpoint()
    if endpoint_error or not token_endpoint:
        return None, endpoint_error or "Missing OIDC token endpoint."

    data = {
        "client_id": OAUTH_CLIENT_ID,
        "client_secret": OAUTH_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": oauth_account.refresh_token,
    }
    if OIDC_SCOPE_OVERRIDE:
        data["scope"] = OIDC_SCOPE_OVERRIDE.replace(",", " ")

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(token_endpoint, data=data)

        if response.status_code != 200:
            return (
                None,
                f"OIDC refresh failed ({response.status_code}): {response.text[:200]}",
            )

        token_payload = response.json()
        new_access_token = token_payload.get("access_token")
        if not isinstance(new_access_token, str) or not new_access_token:
            return None, "OIDC refresh response missing access_token."

        oauth_account.access_token = new_access_token

        new_refresh_token = token_payload.get("refresh_token")
        if isinstance(new_refresh_token, str) and new_refresh_token:
            oauth_account.refresh_token = new_refresh_token

        expires_in = token_payload.get("expires_in")
        if isinstance(expires_in, int):
            oauth_account.expires_at = (
                int(datetime.now(timezone.utc).timestamp()) + expires_in
            )

        db_session.add(oauth_account)
        db_session.commit()
        return new_access_token, None
    except Exception as exc:
        return None, f"OIDC refresh request failed: {exc}"


def _fetch_onedrive_items_page(
    access_token: str,
    base_url: str,
    params: dict[str, str],
    max_items: int,
) -> tuple[list[dict[str, Any]], str | None]:
    headers = {"Authorization": f"Bearer {access_token}"}
    items: list[dict[str, Any]] = []
    next_url: str | None = base_url
    next_params: dict[str, str] | None = params
    capped_max_items = max(1, max_items)
    try:
        with httpx.Client(timeout=30.0) as client:
            while next_url and len(items) < capped_max_items:
                response = client.get(next_url, headers=headers, params=next_params)
                if response.status_code == 401:
                    return [], "OneDrive access unauthorized (401). Re-authenticate user."
                if response.status_code == 403:
                    return [], "OneDrive access forbidden (403). Missing Files.Read scope or consent."
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    break
                value = payload.get("value")
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            items.append(item)
                            if len(items) >= capped_max_items:
                                break
                raw_next = payload.get("@odata.nextLink")
                if isinstance(raw_next, str) and raw_next:
                    next_url = raw_next
                    next_params = None
                else:
                    next_url = None
                    next_params = None
    except Exception as exc:
        return [], f"Unable to fetch OneDrive items: {exc}"
    return items, None


def _graph_json_get(
    access_token: str,
    url: str,
    params: dict[str, str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers, params=params)
            if response.status_code == 401:
                return None, "Microsoft Graph access unauthorized (401). Re-authenticate user."
            if response.status_code == 403:
                return None, "Microsoft Graph access forbidden (403). Missing scope or consent."
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return None, "Unexpected response shape from Microsoft Graph."
            return payload, None
    except Exception as exc:
        return None, f"Microsoft Graph request failed: {exc}"


def _fetch_calendar_events_live(
    access_token: str, window_days: int, max_events: int
) -> tuple[list[dict[str, Any]], str | None]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=max(1, window_days))
    end = now + timedelta(days=max(1, window_days))
    base_url = f"{MS_GRAPH_BASE_URL.rstrip('/')}/me/calendarView"
    params: dict[str, str] = {
        "startDateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "$orderby": "start/dateTime",
        "$top": "50",
        "$select": (
            "id,subject,organizer,start,end,location,isAllDay,"
            "isCancelled,responseStatus,webLink,bodyPreview"
        ),
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    events: list[dict[str, Any]] = []
    next_url: str | None = base_url
    next_params: dict[str, str] | None = params
    capped_max_events = max(1, max_events)

    try:
        with httpx.Client(timeout=30.0) as client:
            while next_url and len(events) < capped_max_events:
                response = client.get(next_url, headers=headers, params=next_params)
                if response.status_code == 401:
                    return [], "Calendar access unauthorized (401). Re-authenticate user."
                if response.status_code == 403:
                    return [], "Calendar access forbidden (403). Missing Calendars.Read scope or consent."
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    break
                value = payload.get("value")
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            events.append(item)
                            if len(events) >= capped_max_events:
                                break
                raw_next = payload.get("@odata.nextLink")
                if isinstance(raw_next, str) and raw_next:
                    next_url = raw_next
                    next_params = None
                else:
                    next_url = None
                    next_params = None
    except Exception as exc:
        return [], f"Unable to fetch calendar events: {exc}"

    return events, None


def _get_chroma_collection() -> Any:
    if chromadb is None:
        raise RuntimeError("chromadb is not installed.")
    client = chromadb.PersistentClient(path=ZENDESK_WIKI_CHROMA_PATH)
    return client.get_or_create_collection(name=ZENDESK_WIKI_COLLECTION)


def _openai_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing from environment.")
    return OpenAI(api_key=api_key)


@mcp_server.tool()
def ping(message: str | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "message": message or "pong",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@mcp_server.tool()
def search_kb(query: str, limit: int = 5) -> dict[str, Any]:
    """Search the indexed Zendesk Help Center knowledge base."""
    if not query.strip():
        return {"ok": False, "error": "Query must not be empty."}

    try:
        openai_client = _openai_client()
        collection = _get_chroma_collection()
    except Exception as exc:
        return {"ok": False, "error": f"Zendesk KB not available: {exc}"}

    embedding = openai_client.embeddings.create(
        model=ZENDESK_WIKI_EMBEDDING_MODEL,
        input=[query],
    ).data[0].embedding

    results = collection.query(
        query_embeddings=[embedding],
        n_results=max(1, min(limit, 20)),
        include=["documents", "metadatas", "distances"],
    )

    ids = results.get("ids", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    documents = results.get("documents", [[]])[0]
    distances = results.get("distances", [[]])[0]

    items: list[dict[str, Any]] = []
    for idx, doc_id in enumerate(ids):
        metadata = metadatas[idx] if idx < len(metadatas) else {}
        document = documents[idx] if idx < len(documents) else ""
        distance = distances[idx] if idx < len(distances) else None
        snippet = str(document)[:500].replace("\n", " ").strip()
        items.append(
            {
                "id": doc_id,
                "title": metadata.get("title") if isinstance(metadata, dict) else None,
                "url": metadata.get("url") if isinstance(metadata, dict) else None,
                "snippet": snippet,
                "distance": distance,
            }
        )

    return {"ok": True, "query": query, "results": items}


@mcp_server.tool()
def list_kb_articles(limit: int = 200) -> dict[str, Any]:
    """List indexed Zendesk Help Center articles from the local KB store."""
    capped_limit = max(1, min(limit, 2000))
    try:
        collection = _get_chroma_collection()
    except Exception as exc:
        return {"ok": False, "error": f"Zendesk KB not available: {exc}"}

    count = collection.count()
    if count <= 0:
        return {
            "ok": True,
            "total_documents": 0,
            "total_articles": 0,
            "articles": [],
            "collection": ZENDESK_WIKI_COLLECTION,
            "path": ZENDESK_WIKI_CHROMA_PATH,
        }

    fetch_limit = count
    rows = collection.get(
        limit=fetch_limit,
        include=["metadatas"],
    )
    metadatas = rows.get("metadatas", [])

    dedup: dict[str, dict[str, Any]] = {}
    for metadata in metadatas:
        if not isinstance(metadata, dict):
            continue
        title = metadata.get("title")
        url = metadata.get("url")
        title_s = str(title).strip() if title else None
        url_s = str(url).strip() if url else None
        key = url_s or title_s
        if not key:
            continue
        if key not in dedup:
            dedup[key] = {
                "title": title_s,
                "url": url_s,
            }

    all_articles = sorted(
        dedup.values(),
        key=lambda item: (item.get("title") or item.get("url") or "").lower(),
    )
    articles = all_articles[:capped_limit]
    return {
        "ok": True,
        "total_documents": count,
        "total_articles": len(all_articles),
        "articles": articles,
        "collection": ZENDESK_WIKI_COLLECTION,
        "path": ZENDESK_WIKI_CHROMA_PATH,
    }


@mcp_server.tool()
def search_zendesk_kb(query: str, limit: int = 5) -> dict[str, Any]:
    """Deprecated-compatible alias for Zendesk KB search."""
    return search_kb.fn(query=query, limit=limit)


@mcp_server.tool()
def list_zendesk_kb_articles(limit: int = 200) -> dict[str, Any]:
    """Deprecated-compatible alias for listing Zendesk KB articles."""
    return list_kb_articles.fn(limit=limit)


@mcp_server.tool()
async def search_user_inbox(
    query: str,
    limit: int = 5,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    if chromadb is None:
        return {"ok": False, "error": "chromadb is not installed."}

    cleaned_query = query.strip()
    if not cleaned_query:
        return {"ok": False, "error": "query must not be empty."}

    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    user_dir = Path(USER_EMAIL_DATA_ROOT) / "users" / resolved_user_id
    if not user_dir.exists():
        access_token, token_error = _resolve_user_access_token(resolved_user_id)
        if token_error or not access_token:
            return {"ok": False, "error": token_error or "No access token."}

        messages, fetch_error = _fetch_graph_messages(access_token, max_items=200)
        if fetch_error:
            return {"ok": False, "error": fetch_error}

        needle = cleaned_query.lower()
        results: list[dict[str, Any]] = []
        for message in messages:
            serialized = _serialize_graph_message(message)
            hay = " ".join(
                [
                    str(serialized.get("subject") or "").lower(),
                    str(serialized.get("sender") or "").lower(),
                    str(serialized.get("preview") or "").lower(),
                ]
            )
            if needle in hay:
                results.append(serialized)

        return {
            "ok": True,
            "query": cleaned_query,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
            "results": results[: max(1, min(limit, 20))],
            "total_results": len(results),
            "message": "Fetched from Microsoft Graph (no local inbox index found).",
        }

    try:
        client = chromadb.PersistentClient(path=str(user_dir))
        collection = client.get_collection(name="user_emails")
    except Exception as exc:
        return {"ok": False, "error": f"Unable to open user inbox collection: {exc}"}

    query_embedding = _deterministic_embedding(cleaned_query)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=max(1, min(limit, 20)),
        include=["documents", "metadatas", "distances"],
    )

    ids = results.get("ids", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    documents = results.get("documents", [[]])[0]
    distances = results.get("distances", [[]])[0]

    items: list[dict[str, Any]] = []
    for idx, doc_id in enumerate(ids):
        metadata = metadatas[idx] if idx < len(metadatas) else {}
        document = documents[idx] if idx < len(documents) else ""
        distance = distances[idx] if idx < len(distances) else None
        items.append(
            {
                "id": doc_id,
                "subject": metadata.get("subject") if isinstance(metadata, dict) else None,
                "sender": metadata.get("sender") if isinstance(metadata, dict) else None,
                "received_at": metadata.get("received_at") if isinstance(metadata, dict) else None,
                "web_link": metadata.get("web_link") if isinstance(metadata, dict) else None,
                "distance": distance,
                "snippet": str(document)[:600],
            }
        )

    return {
        "ok": True,
        "query": cleaned_query,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "results": items,
    }


@mcp_server.tool()
async def list_user_inbox_recent(
    limit: int = 20,
    user_email: str | None = None,
    user_id: str | None = None,
    sender_contains: str | None = None,
    subject_contains: str | None = None,
) -> dict[str, Any]:
    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    conn = _open_user_sqlite(resolved_user_id)
    if conn is None:
        access_token, token_error = _resolve_user_access_token(resolved_user_id)
        if token_error or not access_token:
            return {"ok": False, "error": token_error or "No access token."}

        messages, fetch_error = _fetch_graph_messages(access_token, max_items=200)
        if fetch_error:
            return {"ok": False, "error": fetch_error}

        results = [_serialize_graph_message(message) for message in messages]
        if sender_contains and sender_contains.strip():
            needle = sender_contains.strip().lower()
            results = [r for r in results if needle in str(r.get("sender") or "").lower()]
        if subject_contains and subject_contains.strip():
            needle = subject_contains.strip().lower()
            results = [r for r in results if needle in str(r.get("subject") or "").lower()]

        results = results[: max(1, min(limit, 100))]
        return {
            "ok": True,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
            "results": results,
            "total_results": len(results),
            "message": "Fetched from Microsoft Graph (no local inbox snapshot found).",
        }

    capped_limit = max(1, min(limit, 100))
    where_parts: list[str] = []
    query_params: list[Any] = []
    if sender_contains and sender_contains.strip():
        where_parts.append("LOWER(sender) LIKE ?")
        query_params.append(f"%{sender_contains.strip().lower()}%")
    if subject_contains and subject_contains.strip():
        where_parts.append("LOWER(subject) LIKE ?")
        query_params.append(f"%{subject_contains.strip().lower()}%")
    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    try:
        rows = conn.execute(
            f"""
            SELECT id, internet_message_id, conversation_id, subject, sender, received_at,
                   preview, web_link, raw_json, updated_at
            FROM emails
            {where_clause}
            ORDER BY received_at DESC
            LIMIT ?
            """,
            tuple([*query_params, capped_limit]),
        ).fetchall()
    finally:
        conn.close()

    results = [_serialize_email_row(row) for row in rows]
    return {
        "ok": True,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "results": results,
        "total_results": len(results),
    }


@mcp_server.tool()
async def get_user_inbox_message(
    message_id: str,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    cleaned_message_id = message_id.strip()
    if not cleaned_message_id:
        return {"ok": False, "error": "message_id must not be empty."}

    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    conn = _open_user_sqlite(resolved_user_id)
    if conn is None:
        access_token, token_error = _resolve_user_access_token(resolved_user_id)
        if token_error or not access_token:
            return {"ok": False, "error": token_error or "No access token."}

        payload, fetch_error = _graph_json_get(
            access_token=access_token,
            url=f"{MS_GRAPH_BASE_URL.rstrip('/')}/me/messages/{cleaned_message_id}",
            params={
                "$select": (
                    "id,internetMessageId,conversationId,subject,from,receivedDateTime,"
                    "bodyPreview,webLink,lastModifiedDateTime"
                )
            },
        )
        if fetch_error or payload is None:
            return {
                "ok": False,
                "error": fetch_error or f"Message not found for id: {cleaned_message_id}",
                "user_id": resolved_user_id,
                "user_email": resolved_user_email,
            }

        return {
            "ok": True,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
            "message": _serialize_graph_message(payload),
            "message_source": "microsoft_graph",
        }

    try:
        row = conn.execute(
            """
            SELECT id, internet_message_id, conversation_id, subject, sender, received_at,
                   preview, web_link, raw_json, updated_at
            FROM emails
            WHERE id = ?
            LIMIT 1
            """,
            (cleaned_message_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return {
            "ok": False,
            "error": f"Message not found for id: {cleaned_message_id}",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    return {
        "ok": True,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "message": _serialize_email_row(row),
    }


@mcp_server.tool()
async def get_user_inbox_thread(
    conversation_id: str | None = None,
    message_id: str | None = None,
    limit: int = 50,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    cleaned_conversation_id = conversation_id.strip() if conversation_id else ""
    cleaned_message_id = message_id.strip() if message_id else ""
    if not cleaned_conversation_id and not cleaned_message_id:
        return {"ok": False, "error": "Provide conversation_id or message_id."}

    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    conn = _open_user_sqlite(resolved_user_id)
    if conn is None:
        access_token, token_error = _resolve_user_access_token(resolved_user_id)
        if token_error or not access_token:
            return {"ok": False, "error": token_error or "No access token."}

        resolved_conversation_id = cleaned_conversation_id
        if not resolved_conversation_id and cleaned_message_id:
            payload, fetch_error = _graph_json_get(
                access_token=access_token,
                url=f"{MS_GRAPH_BASE_URL.rstrip('/')}/me/messages/{cleaned_message_id}",
                params={"$select": "conversationId"},
            )
            if fetch_error:
                return {"ok": False, "error": fetch_error}
            if payload:
                cid = payload.get("conversationId")
                if isinstance(cid, str):
                    resolved_conversation_id = cid

        if not resolved_conversation_id:
            return {
                "ok": False,
                "error": "Unable to resolve conversation_id from message_id.",
                "user_id": resolved_user_id,
                "user_email": resolved_user_email,
            }

        messages, fetch_error = _fetch_graph_messages(access_token, max_items=300)
        if fetch_error:
            return {"ok": False, "error": fetch_error}

        results = [
            _serialize_graph_message(message)
            for message in messages
            if str(message.get("conversationId") or "") == resolved_conversation_id
        ]
        results = sorted(results, key=lambda x: x.get("received_at") or "")[
            : max(1, min(limit, 200))
        ]
        return {
            "ok": True,
            "conversation_id": resolved_conversation_id,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
            "results": results,
            "total_results": len(results),
            "message_source": "microsoft_graph",
        }

    capped_limit = max(1, min(limit, 200))
    try:
        resolved_conversation_id = cleaned_conversation_id
        if not resolved_conversation_id and cleaned_message_id:
            row = conn.execute(
                "SELECT conversation_id FROM emails WHERE id = ? LIMIT 1",
                (cleaned_message_id,),
            ).fetchone()
            if row is not None and isinstance(row["conversation_id"], str):
                resolved_conversation_id = row["conversation_id"]

        if not resolved_conversation_id:
            return {
                "ok": False,
                "error": "Unable to resolve conversation_id from message_id.",
                "user_id": resolved_user_id,
                "user_email": resolved_user_email,
            }

        rows = conn.execute(
            """
            SELECT id, internet_message_id, conversation_id, subject, sender, received_at,
                   preview, web_link, raw_json, updated_at
            FROM emails
            WHERE conversation_id = ?
            ORDER BY received_at ASC
            LIMIT ?
            """,
            (resolved_conversation_id, capped_limit),
        ).fetchall()
    finally:
        conn.close()

    results = [_serialize_email_row(row) for row in rows]
    return {
        "ok": True,
        "conversation_id": resolved_conversation_id,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "results": results,
        "total_results": len(results),
    }


@mcp_server.tool()
async def list_user_calendar_events(
    limit: int = 20,
    user_email: str | None = None,
    user_id: str | None = None,
    start_at_from: str | None = None,
    start_at_to: str | None = None,
    include_cancelled: bool = False,
) -> dict[str, Any]:
    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    access_token, token_error = _resolve_user_access_token(resolved_user_id)
    if token_error or not access_token:
        return {
            "ok": False,
            "error": token_error or "No access token.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    capped_limit = max(1, min(limit, 200))
    events, fetch_error = _fetch_calendar_events_live(
        access_token=access_token,
        window_days=30,
        max_events=capped_limit * 4,
    )
    if fetch_error:
        return {
            "ok": False,
            "error": fetch_error,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    results: list[dict[str, Any]] = []
    for event in events:
        serialized = _serialize_calendar_event(event)
        start_at = serialized.get("start_at") or ""
        if not include_cancelled and serialized.get("is_cancelled"):
            continue
        if start_at_from and start_at and start_at < start_at_from:
            continue
        if start_at_to and start_at and start_at > start_at_to:
            continue
        results.append(serialized)

    results = sorted(results, key=lambda x: x.get("start_at") or "")[:capped_limit]
    return {
        "ok": True,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "results": results,
        "total_results": len(results),
    }


@mcp_server.tool()
async def search_user_calendar_events(
    query: str,
    limit: int = 20,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    cleaned_query = query.strip()
    if not cleaned_query:
        return {"ok": False, "error": "query must not be empty."}

    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    access_token, token_error = _resolve_user_access_token(resolved_user_id)
    if token_error or not access_token:
        return {
            "ok": False,
            "error": token_error or "No access token.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    capped_limit = max(1, min(limit, 200))
    events, fetch_error = _fetch_calendar_events_live(
        access_token=access_token,
        window_days=60,
        max_events=capped_limit * 8,
    )
    if fetch_error:
        return {
            "ok": False,
            "error": fetch_error,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    needle = cleaned_query.lower()
    results = []
    for event in events:
        serialized = _serialize_calendar_event(event)
        hay = " ".join(
            [
                str(serialized.get("subject") or "").lower(),
                str(serialized.get("organizer") or "").lower(),
                str(serialized.get("location") or "").lower(),
                str(serialized.get("preview") or "").lower(),
            ]
        )
        if needle in hay:
            results.append(serialized)
    results = sorted(results, key=lambda x: x.get("start_at") or "")[:capped_limit]
    return {
        "ok": True,
        "query": cleaned_query,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "results": results,
        "total_results": len(results),
    }


@mcp_server.tool()
async def get_user_calendar_event(
    event_id: str,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    cleaned_event_id = event_id.strip()
    if not cleaned_event_id:
        return {"ok": False, "error": "event_id must not be empty."}

    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    access_token, token_error = _resolve_user_access_token(resolved_user_id)
    if token_error or not access_token:
        return {
            "ok": False,
            "error": token_error or "No access token.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    events, fetch_error = _fetch_calendar_events_live(
        access_token=access_token,
        window_days=120,
        max_events=1500,
    )
    if fetch_error:
        return {
            "ok": False,
            "error": fetch_error,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    match = next((event for event in events if str(event.get("id") or "") == cleaned_event_id), None)
    if match is None:
        return {
            "ok": False,
            "error": f"Calendar event not found for id: {cleaned_event_id}",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    return {
        "ok": True,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "event": _serialize_calendar_event(match),
    }


@mcp_server.tool()
async def list_user_onedrive_items(
    limit: int = 50,
    folder_id: str | None = None,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    access_token, token_error = _resolve_user_access_token(resolved_user_id)
    if token_error or not access_token:
        return {
            "ok": False,
            "error": token_error or "No access token.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    capped_limit = max(1, min(limit, 200))
    graph_base = MS_GRAPH_BASE_URL.rstrip("/")
    cleaned_folder_id = folder_id.strip() if isinstance(folder_id, str) else ""
    if cleaned_folder_id:
        url = f"{graph_base}/me/drive/items/{cleaned_folder_id}/children"
    else:
        url = f"{graph_base}/me/drive/root/children"
    params = {
        "$top": "100",
        "$select": "id,name,webUrl,size,lastModifiedDateTime,createdDateTime,eTag,cTag,file,folder,parentReference",
    }
    items, fetch_error = _fetch_onedrive_items_page(
        access_token=access_token,
        base_url=url,
        params=params,
        max_items=capped_limit,
    )
    if fetch_error:
        return {
            "ok": False,
            "error": fetch_error,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    serialized = [_serialize_onedrive_item(item) for item in items][:capped_limit]
    return {
        "ok": True,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "folder_id": cleaned_folder_id or "root",
        "results": serialized,
        "total_results": len(serialized),
    }


@mcp_server.tool()
async def search_user_onedrive_items(
    query: str,
    limit: int = 20,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    cleaned_query = query.strip()
    if not cleaned_query:
        return {"ok": False, "error": "query must not be empty."}

    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    access_token, token_error = _resolve_user_access_token(resolved_user_id)
    if token_error or not access_token:
        return {
            "ok": False,
            "error": token_error or "No access token.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    capped_limit = max(1, min(limit, 100))
    graph_base = MS_GRAPH_BASE_URL.rstrip("/")
    escaped_query = cleaned_query.replace("'", "''")
    url = f"{graph_base}/me/drive/root/search(q='{escaped_query}')"
    params = {
        "$top": "50",
        "$select": "id,name,webUrl,size,lastModifiedDateTime,createdDateTime,eTag,cTag,file,folder,parentReference",
    }
    items, fetch_error = _fetch_onedrive_items_page(
        access_token=access_token,
        base_url=url,
        params=params,
        max_items=capped_limit,
    )
    if fetch_error:
        return {
            "ok": False,
            "error": fetch_error,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    serialized = [_serialize_onedrive_item(item) for item in items][:capped_limit]
    return {
        "ok": True,
        "query": cleaned_query,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "results": serialized,
        "total_results": len(serialized),
    }


@mcp_server.tool()
async def get_user_onedrive_item(
    item_id: str,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    cleaned_item_id = item_id.strip()
    if not cleaned_item_id:
        return {"ok": False, "error": "item_id must not be empty."}

    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    access_token, token_error = _resolve_user_access_token(resolved_user_id)
    if token_error or not access_token:
        return {
            "ok": False,
            "error": token_error or "No access token.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    graph_base = MS_GRAPH_BASE_URL.rstrip("/")
    url = f"{graph_base}/me/drive/items/{cleaned_item_id}"
    payload, fetch_error = _graph_json_get(
        access_token=access_token,
        url=url,
        params={
            "$select": "id,name,webUrl,size,lastModifiedDateTime,createdDateTime,eTag,cTag,file,folder,parentReference,@microsoft.graph.downloadUrl",
        },
    )
    if fetch_error or payload is None:
        return {
            "ok": False,
            "error": fetch_error or "Unable to fetch item metadata.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    return {
        "ok": True,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "item": _serialize_onedrive_item(payload),
    }


@mcp_server.tool()
async def get_user_onedrive_file_content(
    item_id: str,
    max_bytes: int = 20000,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    cleaned_item_id = item_id.strip()
    if not cleaned_item_id:
        return {"ok": False, "error": "item_id must not be empty."}

    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    access_token, token_error = _resolve_user_access_token(resolved_user_id)
    if token_error or not access_token:
        return {
            "ok": False,
            "error": token_error or "No access token.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    graph_base = MS_GRAPH_BASE_URL.rstrip("/")
    meta_url = f"{graph_base}/me/drive/items/{cleaned_item_id}"
    metadata, meta_error = _graph_json_get(
        access_token=access_token,
        url=meta_url,
        params={
            "$select": "id,name,webUrl,size,lastModifiedDateTime,createdDateTime,eTag,cTag,file,folder,parentReference,@microsoft.graph.downloadUrl",
        },
    )
    if meta_error or metadata is None:
        return {
            "ok": False,
            "error": meta_error or "Unable to fetch item metadata.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    serialized_item = _serialize_onedrive_item(metadata)
    if serialized_item.get("is_folder"):
        return {
            "ok": False,
            "error": "item_id refers to a folder; use list_user_onedrive_items to inspect children.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
            "item": serialized_item,
        }

    capped_max_bytes = max(128, min(max_bytes, 500000))
    content_url = f"{graph_base}/me/drive/items/{cleaned_item_id}/content"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(content_url, headers=headers)
            if response.status_code == 401:
                return {"ok": False, "error": "OneDrive access unauthorized (401). Re-authenticate user."}
            if response.status_code == 403:
                return {"ok": False, "error": "OneDrive access forbidden (403). Missing Files.Read scope or consent."}
            response.raise_for_status()
            raw = response.content
    except Exception as exc:
        return {"ok": False, "error": f"Unable to fetch file content: {exc}"}

    extracted_text, extract_error = _extract_text_from_file_bytes(
        raw_bytes=raw,
        name=serialized_item.get("name"),
        mime_type=serialized_item.get("mime_type"),
    )
    if extract_error:
        return {
            "ok": False,
            "error": extract_error,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
            "item": serialized_item,
        }

    clipped = extracted_text[:capped_max_bytes]
    return {
        "ok": True,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "item": serialized_item,
        "content_text": clipped,
        "bytes_returned": len(clipped.encode("utf-8")),
        "truncated": len(extracted_text) > capped_max_bytes,
    }


@mcp_server.tool()
async def list_user_sharepoint_sites(
    query: str | None = None,
    limit: int = 20,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    access_token, token_error = _resolve_user_access_token(resolved_user_id)
    if token_error or not access_token:
        return {
            "ok": False,
            "error": token_error or "No access token.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    capped_limit = max(1, min(limit, 50))
    cleaned_query = (query or "").strip()
    graph_base = MS_GRAPH_BASE_URL.rstrip("/")

    if cleaned_query:
        url = f"{graph_base}/sites"
        params = {
            "$top": str(capped_limit),
            "$select": "id,name,displayName,webUrl,description",
            "search": cleaned_query,
        }
        sites, fetch_error = _fetch_onedrive_items_page(
            access_token=access_token,
            base_url=url,
            params=params,
            max_items=capped_limit,
        )
        if fetch_error:
            return {
                "ok": False,
                "error": fetch_error,
                "user_id": resolved_user_id,
                "user_email": resolved_user_email,
            }
        serialized = [_serialize_sharepoint_site(site) for site in sites][:capped_limit]
    else:
        root_site, fetch_error = _graph_json_get(
            access_token=access_token,
            url=f"{graph_base}/sites/root",
            params={"$select": "id,name,displayName,webUrl,description"},
        )
        if fetch_error or root_site is None:
            return {
                "ok": False,
                "error": fetch_error or "Unable to fetch root SharePoint site.",
                "user_id": resolved_user_id,
                "user_email": resolved_user_email,
            }
        serialized = [_serialize_sharepoint_site(root_site)]

    return {
        "ok": True,
        "query": cleaned_query or None,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "results": serialized,
        "total_results": len(serialized),
    }


@mcp_server.tool()
async def list_user_sharepoint_drives(
    site_id: str,
    limit: int = 20,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    cleaned_site_id = site_id.strip()
    if not cleaned_site_id:
        return {"ok": False, "error": "site_id must not be empty."}

    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    access_token, token_error = _resolve_user_access_token(resolved_user_id)
    if token_error or not access_token:
        return {
            "ok": False,
            "error": token_error or "No access token.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    capped_limit = max(1, min(limit, 100))
    graph_base = MS_GRAPH_BASE_URL.rstrip("/")
    url = f"{graph_base}/sites/{cleaned_site_id}/drives"
    params = {
        "$top": str(capped_limit),
        "$select": "id,name,description,driveType,webUrl,createdDateTime,owner",
    }
    drives, fetch_error = _fetch_onedrive_items_page(
        access_token=access_token,
        base_url=url,
        params=params,
        max_items=capped_limit,
    )
    if fetch_error:
        return {
            "ok": False,
            "error": fetch_error,
            "site_id": cleaned_site_id,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    serialized = [_serialize_sharepoint_drive(drive) for drive in drives][:capped_limit]
    return {
        "ok": True,
        "site_id": cleaned_site_id,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "results": serialized,
        "total_results": len(serialized),
    }


@mcp_server.tool()
async def list_user_sharepoint_drive_items(
    drive_id: str,
    folder_id: str | None = None,
    limit: int = 50,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    cleaned_drive_id = drive_id.strip()
    if not cleaned_drive_id:
        return {"ok": False, "error": "drive_id must not be empty."}

    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    access_token, token_error = _resolve_user_access_token(resolved_user_id)
    if token_error or not access_token:
        return {
            "ok": False,
            "error": token_error or "No access token.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    capped_limit = max(1, min(limit, 200))
    graph_base = MS_GRAPH_BASE_URL.rstrip("/")
    cleaned_folder_id = folder_id.strip() if isinstance(folder_id, str) else ""
    if cleaned_folder_id:
        url = f"{graph_base}/drives/{cleaned_drive_id}/items/{cleaned_folder_id}/children"
    else:
        url = f"{graph_base}/drives/{cleaned_drive_id}/root/children"

    params = {
        "$top": "100",
        "$select": "id,name,webUrl,size,lastModifiedDateTime,createdDateTime,eTag,cTag,file,folder,parentReference",
    }
    items, fetch_error = _fetch_onedrive_items_page(
        access_token=access_token,
        base_url=url,
        params=params,
        max_items=capped_limit,
    )
    if fetch_error:
        return {
            "ok": False,
            "error": fetch_error,
            "drive_id": cleaned_drive_id,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    serialized = [_serialize_onedrive_item(item) for item in items][:capped_limit]
    return {
        "ok": True,
        "drive_id": cleaned_drive_id,
        "folder_id": cleaned_folder_id or "root",
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "results": serialized,
        "total_results": len(serialized),
    }


@mcp_server.tool()
async def search_user_sharepoint_drive_items(
    drive_id: str,
    query: str,
    limit: int = 20,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    cleaned_drive_id = drive_id.strip()
    cleaned_query = query.strip()
    if not cleaned_drive_id:
        return {"ok": False, "error": "drive_id must not be empty."}
    if not cleaned_query:
        return {"ok": False, "error": "query must not be empty."}

    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    access_token, token_error = _resolve_user_access_token(resolved_user_id)
    if token_error or not access_token:
        return {
            "ok": False,
            "error": token_error or "No access token.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    capped_limit = max(1, min(limit, 100))
    graph_base = MS_GRAPH_BASE_URL.rstrip("/")
    escaped_query = cleaned_query.replace("'", "''")
    url = f"{graph_base}/drives/{cleaned_drive_id}/root/search(q='{escaped_query}')"
    params = {
        "$top": "50",
        "$select": "id,name,webUrl,size,lastModifiedDateTime,createdDateTime,eTag,cTag,file,folder,parentReference",
    }
    items, fetch_error = _fetch_onedrive_items_page(
        access_token=access_token,
        base_url=url,
        params=params,
        max_items=capped_limit,
    )
    if fetch_error:
        return {
            "ok": False,
            "error": fetch_error,
            "drive_id": cleaned_drive_id,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    serialized = [_serialize_onedrive_item(item) for item in items][:capped_limit]
    return {
        "ok": True,
        "drive_id": cleaned_drive_id,
        "query": cleaned_query,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "results": serialized,
        "total_results": len(serialized),
    }


@mcp_server.tool()
async def get_user_sharepoint_drive_item(
    drive_id: str,
    item_id: str,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    cleaned_drive_id = drive_id.strip()
    cleaned_item_id = item_id.strip()
    if not cleaned_drive_id:
        return {"ok": False, "error": "drive_id must not be empty."}
    if not cleaned_item_id:
        return {"ok": False, "error": "item_id must not be empty."}

    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    access_token, token_error = _resolve_user_access_token(resolved_user_id)
    if token_error or not access_token:
        return {
            "ok": False,
            "error": token_error or "No access token.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    graph_base = MS_GRAPH_BASE_URL.rstrip("/")
    url = f"{graph_base}/drives/{cleaned_drive_id}/items/{cleaned_item_id}"
    payload, fetch_error = _graph_json_get(
        access_token=access_token,
        url=url,
        params={
            "$select": "id,name,webUrl,size,lastModifiedDateTime,createdDateTime,eTag,cTag,file,folder,parentReference,@microsoft.graph.downloadUrl",
        },
    )
    if fetch_error or payload is None:
        return {
            "ok": False,
            "error": fetch_error or "Unable to fetch item metadata.",
            "drive_id": cleaned_drive_id,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    return {
        "ok": True,
        "drive_id": cleaned_drive_id,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "item": _serialize_onedrive_item(payload),
    }


@mcp_server.tool()
async def get_user_sharepoint_file_content(
    drive_id: str,
    item_id: str,
    max_bytes: int = 20000,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    cleaned_drive_id = drive_id.strip()
    cleaned_item_id = item_id.strip()
    if not cleaned_drive_id:
        return {"ok": False, "error": "drive_id must not be empty."}
    if not cleaned_item_id:
        return {"ok": False, "error": "item_id must not be empty."}

    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id, user_email=user_email
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    access_token, token_error = _resolve_user_access_token(resolved_user_id)
    if token_error or not access_token:
        return {
            "ok": False,
            "error": token_error or "No access token.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    graph_base = MS_GRAPH_BASE_URL.rstrip("/")
    meta_url = f"{graph_base}/drives/{cleaned_drive_id}/items/{cleaned_item_id}"
    metadata, meta_error = _graph_json_get(
        access_token=access_token,
        url=meta_url,
        params={
            "$select": "id,name,webUrl,size,lastModifiedDateTime,createdDateTime,eTag,cTag,file,folder,parentReference,@microsoft.graph.downloadUrl",
        },
    )
    if meta_error or metadata is None:
        return {
            "ok": False,
            "error": meta_error or "Unable to fetch item metadata.",
            "drive_id": cleaned_drive_id,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    serialized_item = _serialize_onedrive_item(metadata)
    if serialized_item.get("is_folder"):
        return {
            "ok": False,
            "error": "item_id refers to a folder; use list_user_sharepoint_drive_items to inspect children.",
            "drive_id": cleaned_drive_id,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
            "item": serialized_item,
        }

    capped_max_bytes = max(128, min(max_bytes, 500000))
    content_url = f"{graph_base}/drives/{cleaned_drive_id}/items/{cleaned_item_id}/content"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(content_url, headers=headers)
            if response.status_code == 401:
                return {"ok": False, "error": "SharePoint access unauthorized (401). Re-authenticate user."}
            if response.status_code == 403:
                return {
                    "ok": False,
                    "error": "SharePoint access forbidden (403). Missing Files.Read/Sites.Read permissions or consent.",
                }
            response.raise_for_status()
            raw = response.content
    except Exception as exc:
        return {"ok": False, "error": f"Unable to fetch file content: {exc}"}

    extracted_text, extract_error = _extract_text_from_file_bytes(
        raw_bytes=raw,
        name=serialized_item.get("name"),
        mime_type=serialized_item.get("mime_type"),
    )
    if extract_error:
        return {
            "ok": False,
            "error": extract_error,
            "drive_id": cleaned_drive_id,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
            "item": serialized_item,
        }

    clipped = extracted_text[:capped_max_bytes]
    return {
        "ok": True,
        "drive_id": cleaned_drive_id,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
        "item": serialized_item,
        "content_text": clipped,
        "bytes_returned": len(clipped.encode("utf-8")),
        "truncated": len(extracted_text) > capped_max_bytes,
    }
