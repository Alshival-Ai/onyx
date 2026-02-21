#!/bin/sh
# Setup Onyx Craft templates
# This script is called on container startup to ensure Craft templates are ready
# Set ENABLE_CRAFT=false to skip setup

# Check if Craft is disabled
if [ "$ENABLE_CRAFT" = "false" ] || [ "$ENABLE_CRAFT" = "False" ]; then
    echo "Onyx Craft is disabled (ENABLE_CRAFT=false), skipping template setup"
    exit 0
fi

set -e

# Verify opencode CLI is available (installed in Dockerfile)
if ! command -v opencode >/dev/null 2>&1; then
    echo "ERROR: opencode CLI is not available but ENABLE_CRAFT is enabled." >&2
    echo "opencode is required for Craft agent functionality. Ensure you are using Dockerfile" >&2
    echo "which includes the opencode CLI, or set ENABLE_CRAFT=false to disable Craft." >&2
    exit 1
fi

CRAFT_BASE="/app/onyx/server/features/build/sandbox/kubernetes/docker"
DEMO_DATA_ZIP="${CRAFT_BASE}/demo_data.zip"
DEMO_DATA_DIR="${CRAFT_BASE}/demo_data"
# Use environment variables if set, otherwise use defaults
OUTPUTS_TEMPLATE_PATH="${OUTPUTS_TEMPLATE_PATH:-${CRAFT_BASE}/templates/outputs}"
VENV_TEMPLATE_PATH="${VENV_TEMPLATE_PATH:-${CRAFT_BASE}/templates/venv}"
WEB_TEMPLATE_PATH="${WEB_TEMPLATE_PATH:-${OUTPUTS_TEMPLATE_PATH}/web}"
REQUIREMENTS_PATH="${CRAFT_BASE}/initial-requirements.txt"
FORCE_NPM_INSTALL="${CRAFT_FORCE_TEMPLATE_NPM_INSTALL:-false}"

echo "Setting up Onyx Craft templates..."

# 1. Unzip demo_data.zip if demo_data directory doesn't exist
if [ ! -d "$DEMO_DATA_DIR" ] && [ -f "$DEMO_DATA_ZIP" ]; then
    echo "  Extracting demo data..."
    cd "$CRAFT_BASE" && unzip -q demo_data.zip || { echo "ERROR: Failed to extract demo data" >&2; exit 1; }
    echo "  Demo data extracted"
fi

# 2. Create Python venv template if it doesn't exist
if [ ! -d "$VENV_TEMPLATE_PATH" ] && [ -f "$REQUIREMENTS_PATH" ]; then
    echo "  Creating Python venv template (this may take 30-60 seconds)..."
    python -m venv "$VENV_TEMPLATE_PATH"
    "$VENV_TEMPLATE_PATH/bin/pip" install --upgrade pip -q
    "$VENV_TEMPLATE_PATH/bin/pip" install -q -r "$REQUIREMENTS_PATH"
    echo "  Python venv template created"
fi

# 3. Install web template dependencies only when needed
if [ -d "$WEB_TEMPLATE_PATH" ]; then
    if ! command -v npm >/dev/null 2>&1; then
        echo "ERROR: npm is not available but ENABLE_CRAFT is enabled." >&2
        echo "npm is required for Craft web features. Ensure you are using Dockerfile" >&2
        echo "which includes Node.js, or set ENABLE_CRAFT=false to disable Craft." >&2
        exit 1
    fi

    NPM_MARKER_PATH="${WEB_TEMPLATE_PATH}/.node_modules.lock.sha256"
    SHOULD_INSTALL_NPM="false"

    # Allow manual override for refresh/debug scenarios
    if [ "$FORCE_NPM_INSTALL" = "true" ] || [ "$FORCE_NPM_INSTALL" = "True" ]; then
        SHOULD_INSTALL_NPM="true"
        echo "  Forced npm dependency refresh enabled"
    fi

    if [ ! -d "${WEB_TEMPLATE_PATH}/node_modules" ]; then
        SHOULD_INSTALL_NPM="true"
    fi

    LOCK_HASH=""
    if [ -f "${WEB_TEMPLATE_PATH}/package-lock.json" ] && command -v sha256sum >/dev/null 2>&1; then
        LOCK_HASH="$(sha256sum "${WEB_TEMPLATE_PATH}/package-lock.json" | awk '{print $1}')"
        if [ -z "$LOCK_HASH" ] || [ ! -f "$NPM_MARKER_PATH" ] || [ "$(cat "$NPM_MARKER_PATH" 2>/dev/null)" != "$LOCK_HASH" ]; then
            SHOULD_INSTALL_NPM="true"
        fi
    fi

    if [ "$SHOULD_INSTALL_NPM" = "true" ]; then
        if [ -d "${WEB_TEMPLATE_PATH}/node_modules" ]; then
            echo "  Removing existing node_modules..."
            rm -rf "${WEB_TEMPLATE_PATH}/node_modules"
        fi

        echo "  Installing npm packages (this may take 1-2 minutes)..."
        if [ -f "${WEB_TEMPLATE_PATH}/package-lock.json" ]; then
            (cd "$WEB_TEMPLATE_PATH" && npm ci) || { echo "ERROR: npm ci failed" >&2; exit 1; }
        else
            (cd "$WEB_TEMPLATE_PATH" && npm install) || { echo "ERROR: npm install failed" >&2; exit 1; }
        fi

        if [ -n "$LOCK_HASH" ]; then
            echo "$LOCK_HASH" > "$NPM_MARKER_PATH"
        fi

        echo "  Web template dependencies installed"
    else
        echo "  Web template dependencies already prepared, skipping npm install"
    fi
fi

echo "Craft template setup complete"
