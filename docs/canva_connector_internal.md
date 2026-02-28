# Canva Connector Internal Notes

Last updated: 2026-02-28

## Goal

Keep a single internal source of truth for what our Canva integration currently supports, what is missing, and how to validate it quickly.

## Current Architecture

We now have **two Canva paths**:

1. **Indexed Connector (existing)**
   - File: `backend/onyx/connectors/canva/connector.py`
   - Purpose: sync Canva design metadata into the Onyx document index for semantic search.
   - OAuth scopes used: `design:meta:read folder:read`.
   - Indexed document id format: `canva:design:{design_id}`.
   - Indexed content is metadata-heavy (title/folder/owner/link), not full design body content.

2. **Live MCP Tools (new)**
   - File: `backend/onyx/mcp_server/tools/canva.py`
   - Purpose: let agent call Canva APIs in real-time for listing/getting designs and folder contents.
   - Tool registration wired in:
     - `backend/onyx/mcp_server/tools/__init__.py`
     - `backend/onyx/mcp_server/api.py`

## Implemented Live Tools (Phase 1)

1. `canva_list_designs`
   - Lists Canva designs.
   - Inputs: `query`, `continuation`, `limit`, optional `credential_id`, optional `user_email`/`user_id`.
2. `canva_get_design`
   - Fetches one design by id.
   - Inputs: `design_id`, optional `credential_id`, optional `user_email`/`user_id`.
3. `canva_list_folder_items`
   - Lists folder items (defaults to `item_types=design`).
   - Inputs: `folder_id`, `continuation`, `item_types`, `limit`, optional `credential_id`, optional `user_email`/`user_id`.

## Token/Credential Behavior

- Live tools resolve the current user (from MCP bearer token by default).
- They load an accessible Canva `Credential` (`DocumentSource.CANVA`) for that user.
- If `credential_id` is omitted, newest accessible Canva credential is used.
- If token is near expiry, tools attempt refresh via Canva token endpoint and persist updated token back to credential JSON.

## What Is Connected vs Not Connected

### Connected now

- OAuth flow for connector credentials (Canva app + redirect callback).
- Connector indexing for Canva designs/folder designs.
- Live Canva metadata tools for list/get operations.

### Not connected yet

- True per-user Canva OAuth account mapping for live tools (currently credential-driven).
- Permission sync from Canva ACLs into Onyx document permissions.
- Canva content export/import pipelines for richer body text indexing.
- Brand template autofill / enterprise-only APIs.
- Write actions (create/update/comment/export jobs) as MCP tools.

## OAuth Setup Notes (Public Canva App)

- Redirect URI must match:
  - `{WEB_DOMAIN}/connector/oauth/callback/canva`
  - Example in dev: `https://dev.starwoodgpt.prosourceit.app/connector/oauth/callback/canva`
- Required env vars:
  - `CANVA_CLIENT_ID`
  - `CANVA_CLIENT_SECRET`
- Current scope requested by connector:
  - `design:meta:read folder:read`

## Verification Checklist

1. Confirm connector credentials exist for source `canva` and are accessible to your user.
2. In a chat session using MCP tools, ask for:
   - "List my Canva designs matching `Copy of kpop FINAL VERSION`."
3. Ask for exact design details by id once one is returned.
4. Ask for folder listing if testing folder path:
   - "List Canva folder items for folder `<folder_id>`."
5. Verify returned URLs open the expected Canva design.

## Reindex / Storage Notes

- If indexing errors show `507 Insufficient Storage`, this is capacity-related (Vespa/index storage), not a Canva API contract issue.
- Recovery path is infra cleanup (prune/reclaim) + reindex, then validate that new design docs ingest.

## Next Recommended Phase (when ready)

1. Add provider-specific Canva OAuth account support for per-user live access.
2. Add permission-aware behavior so tools only return files caller can access with their own Canva token.
3. Add one high-value write/action tool (for example, export job trigger) after read paths are stable.
