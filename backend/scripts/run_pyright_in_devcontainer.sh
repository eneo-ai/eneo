#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backend_dir="$(cd "${script_dir}/.." && pwd)"
repo_root="$(cd "${backend_dir}/.." && pwd)"
workspace_backend="/workspace/backend"
service_name="eneo"

resolve_uv_bin() {
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return
  fi

  if [ -x /home/vscode/.local/bin/uv ]; then
    printf '%s\n' /home/vscode/.local/bin/uv
    return
  fi

  printf 'uv executable not found.\n' >&2
  exit 1
}

run_inside_container() {
  local uv_bin
  uv_bin="$(resolve_uv_bin)"
  export PATH="/home/vscode/.local/bin:/home/vscode/.bun/bin:${PATH}"
  cd "${workspace_backend}"
  exec "${uv_bin}" run pyright "$@"
}

resolve_container() {
  if [ -n "${ENEO_DEVCONTAINER_NAME:-}" ]; then
    if docker inspect -f '{{.State.Running}}' "${ENEO_DEVCONTAINER_NAME}" >/dev/null 2>&1; then
      printf '%s\n' "${ENEO_DEVCONTAINER_NAME}"
      return
    fi

    printf 'Configured ENEO_DEVCONTAINER_NAME is not a running container: %s\n' "${ENEO_DEVCONTAINER_NAME}" >&2
    exit 1
  fi

  local candidates=()
  local candidate_name
  while IFS= read -r candidate_name; do
    if [ -n "${candidate_name}" ]; then
      candidates+=("${candidate_name}")
    fi
  done < <(docker ps --filter "label=com.docker.compose.service=${service_name}" --format '{{.Names}}')

  if [ "${#candidates[@]}" -eq 0 ]; then
    printf 'No running devcontainer found for compose service "%s". Start the devcontainer or set ENEO_DEVCONTAINER_NAME.\n' "${service_name}" >&2
    exit 1
  fi

  if [ "${#candidates[@]}" -eq 1 ]; then
    printf '%s\n' "${candidates[0]}"
    return
  fi

  local repo_root_real
  repo_root_real="$(cd "${repo_root}" && pwd -P)"

  local candidate
  for candidate in "${candidates[@]}"; do
    local mount_source=""
    mount_source="$(docker inspect -f '{{range .Mounts}}{{if and (eq .Destination "/workspace") (eq .Type "bind")}}{{.Source}}{{end}}{{end}}' "${candidate}")"
    if [ -n "${mount_source}" ] && [ -d "${mount_source}" ]; then
      if [ "$(cd "${mount_source}" && pwd -P)" = "${repo_root_real}" ]; then
        printf '%s\n' "${candidate}"
        return
      fi
    fi
  done

  printf 'Multiple running "%s" devcontainers were found and none matched %s.\n' "${service_name}" "${repo_root_real}" >&2
  printf 'Set ENEO_DEVCONTAINER_NAME to one of:\n' >&2
  printf '  %s\n' "${candidates[@]}" >&2
  exit 1
}

if [ -f "${workspace_backend}/pyproject.toml" ] && [ -d /workspace ]; then
  run_inside_container "$@"
fi

container_name="$(resolve_container)"

exec docker exec -u vscode -i "${container_name}" bash -lc \
  'export PATH=/home/vscode/.local/bin:/home/vscode/.bun/bin:$PATH && cd /workspace/backend && uv run pyright "$@"' \
  bash "$@"
