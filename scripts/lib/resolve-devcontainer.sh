#!/usr/bin/env bash

# Resolve the running Eneo devcontainer mounted from one exact checkout.
resolve_eneo_devcontainer() {
  local repo_root="$1"
  local service_name="${2:-eneo}"

  if [ -n "${ENEO_DEVCONTAINER_NAME:-}" ]; then
    if docker inspect -f '{{.State.Running}}' "${ENEO_DEVCONTAINER_NAME}" 2>/dev/null | grep -qx true; then
      printf '%s\n' "${ENEO_DEVCONTAINER_NAME}"
      return
    fi
    printf 'Configured ENEO_DEVCONTAINER_NAME is not a running container: %s\n' "${ENEO_DEVCONTAINER_NAME}" >&2
    return 1
  fi

  if [ -f /.dockerenv ] && [ "$(cd "${repo_root}" && pwd -P)" = /workspace ]; then
    local current_container
    current_container="$(hostname)"
    if [ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "${current_container}" 2>/dev/null)" = "${service_name}" ]; then
      printf '%s\n' "${current_container}"
      return
    fi
    printf 'Current container is not the Eneo devcontainer for service "%s".\n' "${service_name}" >&2
    return 1
  fi

  local repo_root_real
  repo_root_real="$(cd "${repo_root}" && pwd -P)"
  local matches=()
  local candidate
  while IFS= read -r candidate; do
    [ -n "${candidate}" ] || continue
    local mount_source
    mount_source="$(docker inspect -f '{{range .Mounts}}{{if and (eq .Destination "/workspace") (eq .Type "bind")}}{{.Source}}{{end}}{{end}}' "${candidate}")"
    if [ -n "${mount_source}" ] && [ -d "${mount_source}" ] && [ "$(cd "${mount_source}" && pwd -P)" = "${repo_root_real}" ]; then
      matches+=("${candidate}")
    fi
  done < <(docker ps --filter "label=com.docker.compose.service=${service_name}" --format '{{.Names}}')

  if [ "${#matches[@]}" -eq 1 ]; then
    printf '%s\n' "${matches[0]}"
    return
  fi
  if [ "${#matches[@]}" -eq 0 ]; then
    printf 'No running "%s" devcontainer is mounted from %s.\n' "${service_name}" "${repo_root_real}" >&2
    return 1
  fi
  printf 'Multiple running "%s" devcontainers are mounted from %s:\n' "${service_name}" "${repo_root_real}" >&2
  printf '  %s\n' "${matches[@]}" >&2
  return 1
}
