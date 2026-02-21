#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Dev environment requires HTTPS/certbot flow on the Pi.
export BAKE_DEFAULT_COMPOSE_FILE="docker-compose.prod.yml"

exec "${SCRIPT_DIR}/bake.sh" "$@"
