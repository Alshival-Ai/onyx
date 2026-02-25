#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_DIR="${REPO_ROOT}/deployment/docker_compose"
ENV_FILE="${COMPOSE_DIR}/.env"

usage() {
  cat <<'EOF'
Usage:
  ./tools/bake.sh [buildx-bake-targets-and-flags] [--compose-up|--compose-restart] [--compose-file FILE] [--compose-up-service SERVICE]

Examples:
  ./tools/bake.sh --compose-restart
  ./tools/bake.sh
  ./tools/bake.sh web
  ENABLE_CRAFT=true ./tools/bake.sh backend --compose-restart --compose-file docker-compose.dev.yml
  ./tools/bake.sh --compose-restart --compose-file docker-compose.prod.yml
  ./tools/bake.sh web --compose-up --compose-file docker-compose.prod.yml --compose-up-service web_server
EOF
}

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

set_repo_from_image() {
  local image_ref="$1"
  local repo_var="$2"

  if [[ -z "$image_ref" ]]; then
    return
  fi

  local repo="$image_ref"
  local tag=""

  # Digest-pinned refs do not have a tag component.
  if [[ "$image_ref" == *@* ]]; then
    repo="${image_ref%@*}"
  else
    local last_path_segment="${image_ref##*/}"
    # Only treat ":" as a tag delimiter if it appears after the final "/".
    if [[ "$last_path_segment" == *:* ]]; then
      repo="${image_ref%:*}"
      tag="${image_ref##*:}"
    fi
  fi

  printf -v "$repo_var" "%s" "$repo"
  export "$repo_var"

  if [[ -n "$tag" && -z "${TAG:-}" ]]; then
    export TAG="$tag"
  fi
}

# Keep compose image names and bake repository targets aligned.
set_repo_from_image "${ONYX_BACKEND_IMAGE:-}" BACKEND_REPOSITORY
set_repo_from_image "${ONYX_WEB_SERVER_IMAGE:-}" WEB_SERVER_REPOSITORY
set_repo_from_image "${ONYX_MODEL_SERVER_IMAGE:-}" MODEL_SERVER_REPOSITORY

# Keep TAG (bake) and IMAGE_TAG (compose) synchronized.
if [[ -n "${TAG:-}" ]]; then
  export IMAGE_TAG="$TAG"
elif [[ -n "${IMAGE_TAG:-}" ]]; then
  export TAG="$IMAGE_TAG"
fi

compose_action=""
compose_file="${BAKE_DEFAULT_COMPOSE_FILE:-docker-compose.yml}"
compose_service=""
declare -a bake_args
bake_args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --compose-up)
      compose_action="up"
      shift
      ;;
    --compose-restart)
      compose_action="restart"
      shift
      ;;
    --compose-file)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --compose-file" >&2
        exit 1
      fi
      compose_file="$2"
      shift 2
      ;;
    --compose-up-service)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --compose-up-service" >&2
        exit 1
      fi
      compose_service="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      bake_args+=("$1")
      shift
      ;;
  esac
done

if [[ -n "$compose_service" && -z "$compose_action" ]]; then
  echo "--compose-up-service requires --compose-up or --compose-restart" >&2
  exit 1
fi

docker buildx bake "${bake_args[@]}"

if [[ -n "$compose_action" ]]; then
  if [[ "$compose_file" = /* ]]; then
    compose_file_path="$compose_file"
  elif [[ -f "$compose_file" ]]; then
    compose_file_path="$(cd -- "$(dirname -- "$compose_file")" && pwd)/$(basename -- "$compose_file")"
  elif [[ -f "${COMPOSE_DIR}/${compose_file}" ]]; then
    compose_file_path="${COMPOSE_DIR}/${compose_file}"
  elif [[ -f "${REPO_ROOT}/${compose_file}" ]]; then
    compose_file_path="${REPO_ROOT}/${compose_file}"
  else
    echo "Compose file not found: $compose_file" >&2
    exit 1
  fi

  compose_cmd=(docker compose)
  if [[ -f "$ENV_FILE" ]]; then
    compose_cmd+=(--env-file "$ENV_FILE")
  fi
  compose_basename="$(basename -- "$compose_file_path")"
  compose_dir="$(dirname -- "$compose_file_path")"
  if [[ "$compose_basename" == "docker-compose.dev.yml" ]]; then
    base_compose="${compose_dir}/docker-compose.yml"
    if [[ ! -f "$base_compose" ]]; then
      echo "Base compose file not found for dev override: $base_compose" >&2
      exit 1
    fi
    compose_cmd+=(-f "$base_compose" -f "$compose_file_path")
  else
    compose_cmd+=(-f "$compose_file_path")
  fi
  compose_cmd+=(up -d)
  if [[ "$compose_action" == "restart" ]]; then
    compose_cmd+=(--force-recreate --remove-orphans)
  fi
  if [[ -n "$compose_service" ]]; then
    compose_cmd+=("$compose_service")
  fi
  "${compose_cmd[@]}"
fi
