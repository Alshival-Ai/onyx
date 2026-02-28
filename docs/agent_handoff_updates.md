# Agent Handoff Updates

## 2026-02-28

### Canva Connector + Live MCP Tools

- Added Canva internal status doc:
  - `docs/canva_connector_internal.md`
- Added new Canva MCP tools module:
  - `backend/onyx/mcp_server/tools/canva.py`
- Registered Canva tools in MCP imports:
  - `backend/onyx/mcp_server/tools/__init__.py`
  - `backend/onyx/mcp_server/api.py`

Implemented tools:

- `canva_list_designs`
- `canva_get_design`
- `canva_list_folder_items`

Behavior notes:

- Tools resolve the current user (or explicit `user_id`/`user_email`) and pick an accessible Canva connector credential.
- If no `credential_id` is passed, the newest accessible Canva credential is used.
- Token refresh is attempted when token expiry is near.

## 2026-02-27

### Chat Text Color Override (Chat Area Only)

- Added workspace setting `chat_text_color` with supported values:
  - `null` / `auto` (default behavior)
  - `dark`
  - `light`
- This setting only affects assistant text rendering in the chat content area.
- Sidebar/admin/navigation colors are unchanged.

### Files Updated

- Backend settings schema:
  - `backend/onyx/server/settings/models.py`
- Frontend settings typing and default fallback:
  - `web/src/app/admin/settings/interfaces.ts`
  - `web/src/components/settings/lib.ts`
- Admin UI control:
  - `web/src/app/admin/settings/SettingsForm.tsx`
- Chat text style definitions and options:
  - `web/src/lib/constants/chatBackgrounds.ts`
- Runtime application of text color override:
  - `web/src/providers/AppBackgroundProvider.tsx`
  - `web/src/app/app/message/messageComponents/renderers/MessageTextRenderer.tsx`

### Behavior Notes

- If `chat_text_color` is `dark` or `light`, that override is always used.
- If `chat_text_color` is `auto`, text style falls back to background-specific defaults.
- If no background is active and `auto` is selected, existing default chat text behavior is preserved.
