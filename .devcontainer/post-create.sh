#!/bin/bash
# Copyright (c) 2024 Sundsvalls Kommun

set -euf -o pipefail

# Join the group that owns the mounted Docker socket for testcontainers support.
# On Linux this is commonly a dedicated docker group. Docker Desktop and
# OrbStack may expose the socket as root:root, so relying on a group named
# "docker" can still leave the vscode user unable to open it.
if [ -e /var/run/docker.sock ]; then
    DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)
    SOCKET_GROUP=$(getent group "$DOCKER_GID" | cut -d: -f1 || true)
    if [ -z "$SOCKET_GROUP" ]; then
        if getent group docker >/dev/null; then
            sudo groupmod -g "$DOCKER_GID" docker
        else
            sudo groupadd -g "$DOCKER_GID" docker
        fi
        SOCKET_GROUP=docker
    fi
    sudo usermod -aG "$SOCKET_GROUP" vscode
    echo "✓ vscode joined Docker socket group $SOCKET_GROUP (GID $DOCKER_GID) for testcontainers support"
fi

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
export UV_LINK_MODE=copy

# The backend .venv, frontend node_modules, and web-next .next cache are on
# named Docker volumes (see docker-compose.yml). Docker creates named volume
# mount points as root:root, but post-create.sh runs as vscode — without these
# chowns, uv/bun/next fail to write into them. The volumes also persist across
# rebuilds, so fix ownership recursively in case a previous container left
# root-owned installed files.
sudo mkdir -p /workspace/backend/.venv \
    /workspace/frontend/node_modules \
    /workspace/frontend/apps/web-next/.next
sudo chown -R -h vscode:vscode /workspace/backend/.venv \
    /workspace/frontend/node_modules \
    /workspace/frontend/apps/web-next/.next
sudo chmod -R u+rwX /workspace/backend/.venv \
    /workspace/frontend/node_modules \
    /workspace/frontend/apps/web-next/.next

# Install Python dependencies
# Use --reinstall-package to ensure the project entry points are up-to-date
# even when the .venv volume persists across container rebuilds
cd /workspace/backend
uv sync --reinstall-package eneo

# Install pre-commit globally and setup hooks
cd /workspace
uv tool install pre-commit
git config --global --add safe.directory /workspace || true

if git -C /workspace rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    LOCAL_HOOKS_PATH="$(git -C /workspace config --local --get core.hooksPath || true)"
    if [ -n "$LOCAL_HOOKS_PATH" ] && [ ! -d "$LOCAL_HOOKS_PATH" ]; then
        echo "Resetting repo-local core.hooksPath ('$LOCAL_HOOKS_PATH') to Git default for the devcontainer"
        git -C /workspace config --local --unset-all core.hooksPath
    fi
    pre-commit install --overwrite --install-hooks \
        --hook-type pre-commit \
        --hook-type commit-msg \
        --hook-type pre-push
else
    echo "Skipping pre-commit hook installation: /workspace is not a usable Git work tree inside this container."
    if [ -f /workspace/.git ] && grep -q '^gitdir: /' /workspace/.git; then
        echo "The workspace appears to be a Git worktree whose .git file points at an absolute host path outside the container mount."
    fi
fi

# Node 22 is installed by the devcontainers/node feature (see devcontainer.json)
# during container creation, so it's already on PATH here — no nvm step needed.

# Install Bun
curl -fsSL https://bun.com/install | bash -s "bun-v1.3.14"

# Add Bun to PATH for this session
export PATH="$HOME/.bun/bin:$PATH"

# Clean frontend node_modules to prevent stale native binaries (e.g. esbuild)
# after container rebuilds where the workspace mount persists. The root
# node_modules is a volume mount point, so empty its contents instead of
# removing the directory itself.
cd /workspace/frontend
find node_modules -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
rm -rf packages/*/node_modules apps/*/node_modules
bun run setup

# Bundled tool runtime (separate Bun project, own lockfile)
cd /workspace/tool-runtime
bun install --frozen-lockfile

# Vitest browser mode needs Chromium and its Linux libraries.
cd /workspace/frontend/apps/web
bun x playwright install --with-deps chromium chromium-headless-shell
