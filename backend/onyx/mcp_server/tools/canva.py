"""Canva MCP tools for live design and folder metadata access."""

from __future__ import annotations

import base64
import os
from datetime import datetime
from datetime import timezone
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx

from onyx.configs.app_configs import CANVA_CLIENT_ID
from onyx.configs.app_configs import CANVA_CLIENT_SECRET
from onyx.configs.constants import DocumentSource
from onyx.db.credentials import backend_update_credential_json
from onyx.db.credentials import fetch_credentials_by_source_for_user
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import Credential
from onyx.db.models import User
from onyx.db.users import get_user_by_email
from onyx.mcp_server.api import mcp_server
from onyx.mcp_server.utils import get_http_client
from onyx.mcp_server.utils import require_access_token
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import build_api_server_url_for_http_requests

logger = setup_logger()

CANVA_API_BASE_URL = "https://api.canva.com/rest/v1"
CANVA_TOKEN_URL = f"{CANVA_API_BASE_URL}/oauth/token"
TOKEN_REFRESH_BUFFER_SECONDS = 300


def _ensure_db_engine_initialized() -> None:
    try:
        SqlEngine.get_engine()
        return
    except Exception:
        pass

    pool_size = int(os.environ.get("POSTGRES_API_SERVER_POOL_SIZE", "40"))
    overflow = int(os.environ.get("POSTGRES_API_SERVER_POOL_OVERFLOW", "10"))
    SqlEngine.init_engine(pool_size=pool_size, max_overflow=overflow)


async def _current_user_from_access_token() -> tuple[str | None, str | None, str | None]:
    access_token = require_access_token()
    try:
        response = await get_http_client().get(
            f"{build_api_server_url_for_http_requests(respect_env_override_if_set=True)}/me",
            headers={"Authorization": f"Bearer {access_token.token}"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return None, None, "Unexpected /me response."

        user_id = payload.get("id")
        user_email = payload.get("email")
        if isinstance(user_id, str):
            try:
                user_id = str(UUID(user_id))
            except Exception:
                user_id = None
        else:
            user_id = None

        if not isinstance(user_email, str):
            user_email = None

        if not user_id and not user_email:
            return None, None, "Unable to resolve current user."
        return user_id, user_email, None
    except Exception as exc:
        logger.error("Failed to resolve current user from /me", exc_info=True)
        return None, None, f"Failed to resolve current user: {exc}"


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

    return await _current_user_from_access_token()


def _normalize_folder_id(folder_id_or_url: str) -> str:
    normalized = folder_id_or_url.strip()
    if "://" not in normalized:
        return normalized

    parsed = urlparse(normalized)
    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        return normalized
    return path_parts[-1]


def _safe_parse_expires_at(expires_at: Any) -> int | None:
    if isinstance(expires_at, int):
        return expires_at
    if isinstance(expires_at, str):
        try:
            return int(expires_at)
        except ValueError:
            return None
    return None


def _is_access_token_expiring(expires_at: int | None) -> bool:
    if expires_at is None:
        return False
    now_ts = int(datetime.now(timezone.utc).timestamp())
    return now_ts >= expires_at - TOKEN_REFRESH_BUFFER_SECONDS


def _basic_auth_header() -> tuple[str | None, str | None]:
    if not CANVA_CLIENT_ID:
        return None, "CANVA_CLIENT_ID is not configured."
    if not CANVA_CLIENT_SECRET:
        return None, "CANVA_CLIENT_SECRET is not configured."

    client_credentials = f"{CANVA_CLIENT_ID}:{CANVA_CLIENT_SECRET}".encode("utf-8")
    return base64.b64encode(client_credentials).decode("utf-8"), None


def _format_token_data(token_data: dict[str, Any]) -> dict[str, Any]:
    token_data_copy = dict(token_data)
    expires_in = token_data_copy.get("expires_in")
    if isinstance(expires_in, int):
        token_data_copy["expires_at"] = int(datetime.now(timezone.utc).timestamp()) + expires_in
    elif isinstance(expires_in, str):
        try:
            token_data_copy["expires_at"] = int(datetime.now(timezone.utc).timestamp()) + int(
                expires_in
            )
        except ValueError:
            pass
    return token_data_copy


def _refresh_canva_access_token(
    credential: Credential,
    credential_json: dict[str, Any],
    db_session: Any,
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    refresh_token = credential_json.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        return None, None, "No Canva refresh token available."

    basic_auth, auth_error = _basic_auth_header()
    if auth_error or not basic_auth:
        return None, None, auth_error or "Canva OAuth client credentials are missing."

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                CANVA_TOKEN_URL,
                headers={
                    "Authorization": f"Basic {basic_auth}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )

        if response.status_code != 200:
            clipped = response.text[:300] if response.text else ""
            return (
                None,
                None,
                f"Canva token refresh failed ({response.status_code}): {clipped}",
            )

        payload = response.json()
        if not isinstance(payload, dict):
            return None, None, "Canva token refresh returned invalid payload."
        formatted = _format_token_data(payload)
        access_token = formatted.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            return None, None, "Canva token refresh response missing access_token."

        merged = {
            **credential_json,
            **formatted,
        }
        backend_update_credential_json(credential, merged, db_session)
        return access_token, merged, None
    except Exception as exc:
        return None, None, f"Failed to refresh Canva access token: {exc}"


def _select_credential(
    credentials: list[Credential],
    credential_id: int | None,
) -> tuple[Credential | None, str | None]:
    if not credentials:
        return None, "No Canva credential is accessible to this user."

    if credential_id is not None:
        selected = next((cred for cred in credentials if cred.id == credential_id), None)
        if selected is None:
            return None, (
                f"Canva credential_id={credential_id} is not accessible to this user."
            )
        return selected, None

    # Pick newest credential by update time, then create time.
    selected = sorted(
        credentials,
        key=lambda cred: (
            cred.time_updated or datetime.min.replace(tzinfo=timezone.utc),
            cred.time_created or datetime.min.replace(tzinfo=timezone.utc),
            cred.id,
        ),
        reverse=True,
    )[0]
    return selected, None


def _resolve_canva_access_token(
    user_id: str,
    credential_id: int | None = None,
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    _ensure_db_engine_initialized()
    with get_session_with_tenant(tenant_id="public") as db_session:
        try:
            parsed_user_id = UUID(user_id)
        except ValueError:
            return None, None, "Resolved user_id is not a valid UUID."

        user = db_session.get(User, parsed_user_id)
        if user is None:
            return None, None, f"User not found for user_id={user_id}."

        credentials = fetch_credentials_by_source_for_user(
            db_session=db_session,
            user=user,
            document_source=DocumentSource.CANVA,
            get_editable=False,
        )
        selected, select_error = _select_credential(credentials, credential_id)
        if select_error or selected is None:
            return None, None, select_error or "Unable to resolve Canva credential."

        credential_json = (
            selected.credential_json.get_value(apply_mask=False)
            if selected.credential_json
            else {}
        )
        if not isinstance(credential_json, dict):
            return None, None, "Canva credential payload is invalid."

        access_token = credential_json.get("access_token") or credential_json.get(
            "canva_access_token"
        )
        if not isinstance(access_token, str) or not access_token:
            return None, None, "Canva credential is missing access_token."

        expires_at = _safe_parse_expires_at(credential_json.get("expires_at"))
        if _is_access_token_expiring(expires_at):
            refreshed_token, refreshed_json, refresh_error = _refresh_canva_access_token(
                credential=selected,
                credential_json=credential_json,
                db_session=db_session,
            )
            if refreshed_token:
                access_token = refreshed_token
                if refreshed_json is not None:
                    credential_json = refreshed_json
            else:
                now_ts = int(datetime.now(timezone.utc).timestamp())
                if isinstance(expires_at, int) and expires_at <= now_ts:
                    return None, None, (
                        refresh_error
                        or "Canva access token is expired and refresh failed."
                    )
                logger.warning(
                    "Canva token refresh failed for credential_id=%s; using existing token. error=%s",
                    selected.id,
                    refresh_error,
                )

        credential_summary = {
            "id": selected.id,
            "name": selected.name,
            "source": selected.source.value
            if isinstance(selected.source, DocumentSource)
            else str(selected.source),
            "time_updated": selected.time_updated.isoformat()
            if selected.time_updated
            else None,
        }

    return access_token, credential_summary, None


def _design_fallback_url(design_id: str) -> str:
    return f"https://www.canva.com/design/{design_id}/view"


def _serialize_design(design: dict[str, Any]) -> dict[str, Any]:
    design_id_raw = design.get("id")
    design_id = str(design_id_raw) if design_id_raw is not None else ""
    title = design.get("title")
    if not isinstance(title, str) or not title.strip():
        title = f"Canva Design {design_id}" if design_id else "Canva Design"

    design_url = design.get("url")
    urls = design.get("urls")
    if not isinstance(design_url, str) or not design_url:
        if isinstance(urls, dict):
            view_url = urls.get("view_url")
            edit_url = urls.get("edit_url")
            if isinstance(view_url, str) and view_url:
                design_url = view_url
            elif isinstance(edit_url, str) and edit_url:
                design_url = edit_url

    if (not isinstance(design_url, str) or not design_url) and design_id:
        design_url = _design_fallback_url(design_id)

    owner_user_id: str | None = None
    owner_team_id: str | None = None
    owner = design.get("owner")
    if isinstance(owner, dict):
        raw_owner_user_id = owner.get("user_id")
        raw_owner_team_id = owner.get("team_id")
        if isinstance(raw_owner_user_id, str) and raw_owner_user_id:
            owner_user_id = raw_owner_user_id
        if isinstance(raw_owner_team_id, str) and raw_owner_team_id:
            owner_team_id = raw_owner_team_id

    return {
        "id": design_id,
        "title": title,
        "url": design_url,
        "updated_at": design.get("updated_at"),
        "created_at": design.get("created_at"),
        "owner_user_id": owner_user_id,
        "owner_team_id": owner_team_id,
    }


def _serialize_folder_item(item: dict[str, Any]) -> dict[str, Any]:
    item_type = item.get("type")
    base = {"type": item_type}

    if item_type == "design":
        design = item.get("design")
        if isinstance(design, dict):
            base["design"] = _serialize_design(design)
        folder = item.get("folder")
        if isinstance(folder, dict):
            base["folder"] = {
                "id": folder.get("id"),
                "name": folder.get("name"),
            }
        return base

    folder = item.get("folder")
    if item_type == "folder" and isinstance(folder, dict):
        base["folder"] = {
            "id": folder.get("id"),
            "name": folder.get("name"),
            "description": folder.get("description"),
            "updated_at": folder.get("updated_at"),
        }
        return base

    if isinstance(folder, dict):
        base["folder"] = {
            "id": folder.get("id"),
            "name": folder.get("name"),
        }
    base["raw"] = item
    return base


def _canva_get(
    access_token: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{CANVA_API_BASE_URL}{endpoint}",
                headers=headers,
                params=params,
            )

        if response.status_code == 401:
            return None, "Canva access unauthorized (401). Re-authenticate Canva credential."
        if response.status_code == 403:
            return None, "Canva access forbidden (403). Missing scope or file/folder permission."
        if response.status_code == 404:
            return None, "Canva resource not found (404)."
        if response.status_code >= 400:
            clipped = response.text[:300] if response.text else ""
            return None, f"Canva API error ({response.status_code}): {clipped}"

        payload = response.json()
        if not isinstance(payload, dict):
            return None, "Canva API returned invalid payload."
        return payload, None
    except Exception as exc:
        return None, f"Unable to call Canva API: {exc}"


@mcp_server.tool()
async def canva_list_designs(
    query: str | None = None,
    continuation: str | None = None,
    limit: int = 50,
    credential_id: int | None = None,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """List Canva designs visible to the connected credential."""
    capped_limit = max(1, min(limit, 200))
    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id,
        user_email=user_email,
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    access_token, credential_summary, token_error = _resolve_canva_access_token(
        user_id=resolved_user_id,
        credential_id=credential_id,
    )
    if token_error or not access_token:
        return {
            "ok": False,
            "error": token_error or "Unable to resolve Canva access token.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    params: dict[str, Any] = {}
    cleaned_query = query.strip() if isinstance(query, str) else ""
    cleaned_continuation = continuation.strip() if isinstance(continuation, str) else ""
    if cleaned_query:
        params["query"] = cleaned_query
    if cleaned_continuation:
        params["continuation"] = cleaned_continuation

    payload, fetch_error = _canva_get(
        access_token=access_token,
        endpoint="/designs",
        params=params or None,
    )
    if fetch_error or payload is None:
        return {
            "ok": False,
            "error": fetch_error or "Unable to fetch Canva designs.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
            "credential": credential_summary,
        }

    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    serialized = [
        _serialize_design(item)
        for item in items
        if isinstance(item, dict)
    ][:capped_limit]

    next_continuation = payload.get("continuation")
    if not isinstance(next_continuation, str):
        next_continuation = None

    return {
        "ok": True,
        "query": cleaned_query or None,
        "continuation_used": cleaned_continuation or None,
        "next_continuation": next_continuation,
        "results": serialized,
        "total_results": len(serialized),
        "credential": credential_summary,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
    }


@mcp_server.tool()
async def canva_get_design(
    design_id: str,
    credential_id: int | None = None,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Get metadata for one Canva design by id."""
    cleaned_design_id = design_id.strip()
    if not cleaned_design_id:
        return {"ok": False, "error": "design_id must not be empty."}

    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id,
        user_email=user_email,
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    access_token, credential_summary, token_error = _resolve_canva_access_token(
        user_id=resolved_user_id,
        credential_id=credential_id,
    )
    if token_error or not access_token:
        return {
            "ok": False,
            "error": token_error or "Unable to resolve Canva access token.",
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    payload, fetch_error = _canva_get(
        access_token=access_token,
        endpoint=f"/designs/{cleaned_design_id}",
    )
    if fetch_error or payload is None:
        return {
            "ok": False,
            "error": fetch_error or "Unable to fetch Canva design.",
            "design_id": cleaned_design_id,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
            "credential": credential_summary,
        }

    design_payload: dict[str, Any] | None = None
    nested_design = payload.get("design")
    if isinstance(nested_design, dict):
        design_payload = nested_design
    else:
        design_payload = payload

    if not isinstance(design_payload, dict):
        return {
            "ok": False,
            "error": "Canva design payload is invalid.",
            "design_id": cleaned_design_id,
            "credential": credential_summary,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    return {
        "ok": True,
        "design_id": cleaned_design_id,
        "design": _serialize_design(design_payload),
        "credential": credential_summary,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
    }


@mcp_server.tool()
async def canva_list_folder_items(
    folder_id: str,
    continuation: str | None = None,
    item_types: list[str] | None = None,
    limit: int = 50,
    credential_id: int | None = None,
    user_email: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """List items in a Canva folder (designs and/or folders)."""
    normalized_folder_id = _normalize_folder_id(folder_id)
    if not normalized_folder_id:
        return {"ok": False, "error": "folder_id must not be empty."}

    capped_limit = max(1, min(limit, 200))
    resolved_user_id, resolved_user_email, resolve_error = await _resolve_user_id(
        user_id=user_id,
        user_email=user_email,
    )
    if resolve_error or not resolved_user_id:
        return {"ok": False, "error": resolve_error or "Unable to resolve user identifier."}

    access_token, credential_summary, token_error = _resolve_canva_access_token(
        user_id=resolved_user_id,
        credential_id=credential_id,
    )
    if token_error or not access_token:
        return {
            "ok": False,
            "error": token_error or "Unable to resolve Canva access token.",
            "folder_id": normalized_folder_id,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
        }

    params: dict[str, Any] = {}
    cleaned_continuation = continuation.strip() if isinstance(continuation, str) else ""
    if cleaned_continuation:
        params["continuation"] = cleaned_continuation

    cleaned_item_types = [
        item_type.strip()
        for item_type in (item_types or [])
        if isinstance(item_type, str) and item_type.strip()
    ]
    if cleaned_item_types:
        params["item_types"] = ",".join(cleaned_item_types)
    else:
        params["item_types"] = "design"

    payload, fetch_error = _canva_get(
        access_token=access_token,
        endpoint=f"/folders/{normalized_folder_id}/items",
        params=params,
    )
    if fetch_error or payload is None:
        return {
            "ok": False,
            "error": fetch_error or "Unable to fetch Canva folder items.",
            "folder_id": normalized_folder_id,
            "user_id": resolved_user_id,
            "user_email": resolved_user_email,
            "credential": credential_summary,
        }

    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    serialized = [
        _serialize_folder_item(item)
        for item in items
        if isinstance(item, dict)
    ][:capped_limit]

    next_continuation = payload.get("continuation")
    if not isinstance(next_continuation, str):
        next_continuation = None

    return {
        "ok": True,
        "folder_id": normalized_folder_id,
        "continuation_used": cleaned_continuation or None,
        "next_continuation": next_continuation,
        "item_types": cleaned_item_types or ["design"],
        "results": serialized,
        "total_results": len(serialized),
        "credential": credential_summary,
        "user_id": resolved_user_id,
        "user_email": resolved_user_email,
    }
