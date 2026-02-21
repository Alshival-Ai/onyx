#####
# Periodic Tasks
#####
import datetime
import json
import secrets
import string
from typing import Any

from celery import shared_task
from celery.contrib.abortable import AbortableTask  # type: ignore
from celery.exceptions import TaskRevokedError
from sqlalchemy import inspect
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.app_configs import MCP_API_KEY_HEADER
from onyx.configs.app_configs import MCP_ROTATING_KEY_ENABLED
from onyx.configs.app_configs import MCP_ROTATING_KEY_LENGTH
from onyx.configs.app_configs import MCP_ROTATING_KEY_PREVIOUS_TTL_SECONDS
from onyx.configs.app_configs import MCP_ROTATING_KEY_TTL_SECONDS
from onyx.configs.app_configs import MCP_SERVER_DESCRIPTION
from onyx.configs.app_configs import MCP_SERVER_NAME
from onyx.configs.app_configs import MCP_SERVER_OWNER_EMAIL
from onyx.configs.app_configs import MCP_SERVER_TRANSPORT
from onyx.configs.app_configs import MCP_SERVER_URL
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisConstants
from onyx.configs.constants import ONYX_CLOUD_TENANT_ID
from onyx.configs.constants import PostgresAdvisoryLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPServerStatus
from onyx.db.enums import MCPTransport
from onyx.db.mcp import create_connection_config
from onyx.db.mcp import create_mcp_server__no_commit
from onyx.db.mcp import extract_connection_data
from onyx.db.mcp import get_connection_config_by_id
from onyx.db.mcp import update_connection_config
from onyx.db.mcp import update_mcp_server__no_commit
from onyx.db.models import MCPServer
from onyx.db.tools import create_tool__no_commit
from onyx.db.tools import delete_tool__no_commit
from onyx.db.tools import get_tools_by_mcp_server_id
from onyx.redis.redis_pool import get_redis_client
from onyx.tools.tool_implementations.mcp.mcp_client import discover_mcp_tools
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA


@shared_task(
    name=OnyxCeleryTask.KOMBU_MESSAGE_CLEANUP_TASK,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
    base=AbortableTask,
)
def kombu_message_cleanup_task(self: Any, tenant_id: str) -> int:  # noqa: ARG001
    """Runs periodically to clean up the kombu_message table"""

    # we will select messages older than this amount to clean up
    KOMBU_MESSAGE_CLEANUP_AGE = 7  # days
    KOMBU_MESSAGE_CLEANUP_PAGE_LIMIT = 1000

    ctx = {}
    ctx["last_processed_id"] = 0
    ctx["deleted"] = 0
    ctx["cleanup_age"] = KOMBU_MESSAGE_CLEANUP_AGE
    ctx["page_limit"] = KOMBU_MESSAGE_CLEANUP_PAGE_LIMIT
    with get_session_with_current_tenant() as db_session:
        # Exit the task if we can't take the advisory lock
        result = db_session.execute(
            text("SELECT pg_try_advisory_lock(:id)"),
            {"id": PostgresAdvisoryLocks.KOMBU_MESSAGE_CLEANUP_LOCK_ID.value},
        ).scalar()
        if not result:
            return 0

        while True:
            if self.is_aborted():
                raise TaskRevokedError("kombu_message_cleanup_task was aborted.")

            b = kombu_message_cleanup_task_helper(ctx, db_session)
            if not b:
                break

            db_session.commit()

    if ctx["deleted"] > 0:
        task_logger.info(
            f"Deleted {ctx['deleted']} orphaned messages from kombu_message."
        )

    return ctx["deleted"]


def kombu_message_cleanup_task_helper(ctx: dict, db_session: Session) -> bool:
    """
    Helper function to clean up old messages from the `kombu_message` table that are no longer relevant.

    This function retrieves messages from the `kombu_message` table that are no longer visible and
    older than a specified interval. It checks if the corresponding task_id exists in the
    `celery_taskmeta` table. If the task_id does not exist, the message is deleted.

    Args:
        ctx (dict): A context dictionary containing configuration parameters such as:
            - 'cleanup_age' (int): The age in days after which messages are considered old.
            - 'page_limit' (int): The maximum number of messages to process in one batch.
            - 'last_processed_id' (int): The ID of the last processed message to handle pagination.
            - 'deleted' (int): A counter to track the number of deleted messages.
        db_session (Session): The SQLAlchemy database session for executing queries.

    Returns:
        bool: Returns True if there are more rows to process, False if not.
    """

    inspector = inspect(db_session.bind)
    if not inspector:
        return False

    # With the move to redis as celery's broker and backend, kombu tables may not even exist.
    # We can fail silently.
    if not inspector.has_table("kombu_message"):
        return False

    query = text(
        """
    SELECT id, timestamp, payload
    FROM kombu_message WHERE visible = 'false'
    AND timestamp < CURRENT_TIMESTAMP - INTERVAL :interval_days
    AND id > :last_processed_id
    ORDER BY id
    LIMIT :page_limit
"""
    )
    kombu_messages = db_session.execute(
        query,
        {
            "interval_days": f"{ctx['cleanup_age']} days",
            "page_limit": ctx["page_limit"],
            "last_processed_id": ctx["last_processed_id"],
        },
    ).fetchall()

    if len(kombu_messages) == 0:
        return False

    for msg in kombu_messages:
        payload = json.loads(msg[2])
        task_id = payload["headers"]["id"]

        # Check if task_id exists in celery_taskmeta
        task_exists = db_session.execute(
            text("SELECT 1 FROM celery_taskmeta WHERE task_id = :task_id"),
            {"task_id": task_id},
        ).fetchone()

        # If task_id does not exist, delete the message
        if not task_exists:
            result = db_session.execute(
                text("DELETE FROM kombu_message WHERE id = :message_id"),
                {"message_id": msg[0]},
            )
            if result.rowcount > 0:  # type: ignore
                ctx["deleted"] += 1

        ctx["last_processed_id"] = msg[0]

    return True


def _generate_mcp_api_key(length: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _get_transport_from_config() -> MCPTransport:
    try:
        return MCPTransport(MCP_SERVER_TRANSPORT)
    except ValueError:
        task_logger.warning(
            "Invalid MCP_SERVER_TRANSPORT=%s, defaulting to STREAMABLE_HTTP",
            MCP_SERVER_TRANSPORT,
        )
        return MCPTransport.STREAMABLE_HTTP


def _upsert_mcp_server_config(
    tenant_id: str | None,
    api_key: str,
) -> None:
    server_url = (MCP_SERVER_URL or "").strip()
    if not server_url:
        task_logger.warning("MCP_SERVER_URL is empty; skipping MCP server upsert.")
        return

    transport = _get_transport_from_config()
    owner_email = MCP_SERVER_OWNER_EMAIL or "system@local"

    with get_session_with_tenant(
        tenant_id=tenant_id or POSTGRES_DEFAULT_SCHEMA
    ) as db_session:
        server = db_session.scalar(
            select(MCPServer).where(MCPServer.server_url == server_url)
        )

        if server is None:
            server = create_mcp_server__no_commit(
                owner_email=owner_email,
                name=MCP_SERVER_NAME,
                description=MCP_SERVER_DESCRIPTION,
                server_url=server_url,
                auth_type=MCPAuthenticationType.API_TOKEN,
                auth_performer=MCPAuthenticationPerformer.ADMIN,
                transport=transport,
                db_session=db_session,
            )
            admin_config = create_connection_config(
                config_data={"headers": {MCP_API_KEY_HEADER: api_key}},
                mcp_server_id=server.id,
                db_session=db_session,
            )
            update_mcp_server__no_commit(
                server_id=server.id,
                db_session=db_session,
                admin_connection_config_id=admin_config.id,
                status=MCPServerStatus.CONNECTED,
            )
            try:
                _sync_mcp_tools_for_server(
                    db_session=db_session,
                    mcp_server=server,
                    headers={"headers": {MCP_API_KEY_HEADER: api_key}},
                )
            except Exception:
                task_logger.exception(
                    "Failed to sync MCP tools for %s during create. "
                    "Keeping updated MCP API key/header and existing tool snapshots.",
                    server_url,
                )
                update_mcp_server__no_commit(
                    server_id=server.id,
                    db_session=db_session,
                    status=MCPServerStatus.DISCONNECTED,
                )
            db_session.commit()
            task_logger.info("Created MCP server %s", server_url)
            return

        update_mcp_server__no_commit(
            server_id=server.id,
            db_session=db_session,
            name=MCP_SERVER_NAME,
            description=MCP_SERVER_DESCRIPTION,
            server_url=server_url,
            auth_type=MCPAuthenticationType.API_TOKEN,
            auth_performer=MCPAuthenticationPerformer.ADMIN,
            transport=transport,
            status=MCPServerStatus.CONNECTED,
        )

        if server.admin_connection_config_id:
            config = get_connection_config_by_id(
                server.admin_connection_config_id, db_session
            )
            config_data = extract_connection_data(config)
            config_data["headers"] = {MCP_API_KEY_HEADER: api_key}
            update_connection_config(config.id, db_session, config_data)
        else:
            admin_config = create_connection_config(
                config_data={"headers": {MCP_API_KEY_HEADER: api_key}},
                mcp_server_id=server.id,
                db_session=db_session,
            )
            update_mcp_server__no_commit(
                server_id=server.id,
                db_session=db_session,
                admin_connection_config_id=admin_config.id,
            )
        try:
            _sync_mcp_tools_for_server(
                db_session=db_session,
                mcp_server=server,
                headers={"headers": {MCP_API_KEY_HEADER: api_key}},
            )
        except Exception:
            task_logger.exception(
                "Failed to sync MCP tools for %s during update. "
                "Keeping updated MCP API key/header and existing tool snapshots.",
                server_url,
            )
            update_mcp_server__no_commit(
                server_id=server.id,
                db_session=db_session,
                status=MCPServerStatus.DISCONNECTED,
            )
        db_session.commit()

        task_logger.info("Updated MCP server credentials for %s", server_url)


def _sync_mcp_tools_for_server(
    db_session: Session,
    mcp_server: MCPServer,
    headers: dict[str, dict[str, str]],
) -> None:
    if mcp_server.transport is None:
        return

    connection_headers = headers.get("headers", {})
    discovered_tools = discover_mcp_tools(
        mcp_server.server_url,
        connection_headers,
        transport=mcp_server.transport,
        auth=None,
    )

    update_mcp_server__no_commit(
        server_id=mcp_server.id,
        db_session=db_session,
        status=MCPServerStatus.CONNECTED,
        last_refreshed_at=datetime.datetime.now(datetime.timezone.utc),
    )

    existing_tools = get_tools_by_mcp_server_id(mcp_server.id, db_session)
    existing_by_name = {tool.name: tool for tool in existing_tools}
    processed_names: set[str] = set()
    db_dirty = False

    for tool in discovered_tools:
        tool_name = tool.name
        if not tool_name:
            continue

        processed_names.add(tool_name)
        description = tool.description or ""
        annotations_title = tool.annotations.title if tool.annotations else None
        display_name = tool.title or annotations_title or tool_name
        input_schema = tool.inputSchema

        if existing_tool := existing_by_name.get(tool_name):
            if existing_tool.description != description:
                existing_tool.description = description
                db_dirty = True
            if existing_tool.display_name != display_name:
                existing_tool.display_name = display_name
                db_dirty = True
            if existing_tool.mcp_input_schema != input_schema:
                existing_tool.mcp_input_schema = input_schema
                db_dirty = True
            continue

        new_tool = create_tool__no_commit(
            name=tool_name,
            description=description,
            openapi_schema=None,
            custom_headers=None,
            user_id=None,
            db_session=db_session,
            passthrough_auth=False,
            mcp_server_id=mcp_server.id,
            enabled=True,
        )
        new_tool.display_name = display_name
        new_tool.mcp_input_schema = input_schema
        db_dirty = True

    for name, db_tool in existing_by_name.items():
        if name not in processed_names:
            delete_tool__no_commit(db_tool.id, db_session)
            db_dirty = True

    if db_dirty:
        db_session.commit()


@shared_task(
    name=OnyxCeleryTask.ROTATE_MCP_API_KEY,
    soft_time_limit=JOB_TIMEOUT,
)
def rotate_mcp_api_key_task(tenant_id: str | None = None) -> int:
    if not MCP_ROTATING_KEY_ENABLED:
        task_logger.info("MCP rotating key disabled. Skipping.")
        return 0

    redis_client = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
    current_key = redis_client.get(OnyxRedisConstants.MCP_API_KEY_CURRENT)
    if isinstance(current_key, bytes):
        current_key = current_key.decode("utf-8")

    new_key = _generate_mcp_api_key(MCP_ROTATING_KEY_LENGTH)

    if current_key:
        redis_client.set(
            OnyxRedisConstants.MCP_API_KEY_PREVIOUS,
            current_key,
            ex=MCP_ROTATING_KEY_PREVIOUS_TTL_SECONDS,
        )

    redis_client.set(
        OnyxRedisConstants.MCP_API_KEY_CURRENT,
        new_key,
        ex=MCP_ROTATING_KEY_TTL_SECONDS,
    )

    _upsert_mcp_server_config(tenant_id, new_key)

    task_logger.info("Rotated MCP API key.")
    return 1
