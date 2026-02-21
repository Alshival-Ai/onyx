"""Authentication helpers for the Onyx MCP server."""

from typing import Optional

from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.auth import TokenVerifier

from onyx.configs.app_configs import MCP_ROTATING_KEY_ENABLED
from onyx.configs.constants import OnyxRedisConstants
from onyx.configs.constants import ONYX_CLOUD_TENANT_ID
from onyx.redis.redis_pool import get_redis_client
from onyx.mcp_server.utils import get_http_client
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import build_api_server_url_for_http_requests

logger = setup_logger()


def _is_valid_rotating_mcp_key(token: str) -> bool:
    try:
        redis_client = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)
        current = redis_client.get(OnyxRedisConstants.MCP_API_KEY_CURRENT)
        previous = redis_client.get(OnyxRedisConstants.MCP_API_KEY_PREVIOUS)

        if isinstance(current, bytes):
            current = current.decode("utf-8")
        if isinstance(previous, bytes):
            previous = previous.decode("utf-8")

        return token == current or token == previous
    except Exception:
        logger.exception("Failed validating rotating MCP API key against Redis.")
        return False


class OnyxTokenVerifier(TokenVerifier):
    """Validates bearer tokens by delegating to the API server."""

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        """Call API /me to verify the token, return minimal AccessToken on success."""
        if MCP_ROTATING_KEY_ENABLED and _is_valid_rotating_mcp_key(token):
            return AccessToken(
                token=token,
                client_id="mcp-api-key",
                scopes=["mcp:use"],
                expires_at=None,
                resource=None,
                claims={},
            )

        try:
            response = await get_http_client().get(
                f"{build_api_server_url_for_http_requests(respect_env_override_if_set=True)}/me",
                headers={"Authorization": f"Bearer {token}"},
            )
        except Exception as exc:
            logger.error(
                "MCP server failed to reach API /me for authentication: %s",
                exc,
                exc_info=True,
            )
            return None

        if response.status_code != 200:
            logger.warning(
                "API server rejected MCP auth token with status %s",
                response.status_code,
            )
            return None

        return AccessToken(
            token=token,
            client_id="mcp",
            scopes=["mcp:use"],
            expires_at=None,
            resource=None,
            claims={},
        )
