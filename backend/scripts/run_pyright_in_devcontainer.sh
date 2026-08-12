#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backend_dir="$(cd "${script_dir}/.." && pwd)"
repo_root="$(cd "${backend_dir}/.." && pwd)"
workspace_backend="/workspace/backend"
service_name="eneo"
source "${repo_root}/scripts/lib/resolve-devcontainer.sh"

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
  export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=4096}"
  cd "${workspace_backend}"
  exec "${uv_bin}" run pyright "$@"
}

if [ -f /.dockerenv ] && [ -f "${workspace_backend}/pyproject.toml" ]; then
  run_inside_container "$@"
fi

container_name="$(resolve_eneo_devcontainer "${repo_root}" "${service_name}")"

exec docker exec -u vscode -i "${container_name}" bash -lc \
  'export PATH=/home/vscode/.local/bin:/home/vscode/.bun/bin:$PATH && export NODE_OPTIONS=${NODE_OPTIONS:---max-old-space-size=4096} && cd /workspace/backend && uv run pyright "$@"' \
  bash "$@"
