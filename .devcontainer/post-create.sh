#!/bin/bash
# Copyright (c) 2024 Sundsvalls Kommun
#
# Licensed under the MIT License.

set -euf -o pipefail

# Create docker group for testcontainers support (Docker-in-Docker)
# Extract the GID from the docker socket which is mounted from the host
# This works on any system because it uses the actual docker GID from the socket
if [ -e /var/run/docker.sock ]; then
    DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)
    if ! grep -q "^docker:" /etc/group; then
        sudo groupadd -g "$DOCKER_GID" docker || true
    fi
    sudo usermod -aG docker vscode
    echo "✓ Docker group created with GID $DOCKER_GID for testcontainers support"
fi

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
export UV_LINK_MODE=copy

# The backend .venv is on a named Docker volume (see docker-compose.yml).
# Docker creates named volume mount points as root:root, but post-create.sh
# runs as vscode. The volume also persists across rebuilds, so fix ownership
# recursively in case a previous container left root-owned installed files.
sudo mkdir -p /workspace/backend/.venv
sudo chown -R -h vscode:vscode /workspace/backend/.venv
sudo chmod -R u+rwX /workspace/backend/.venv

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

# Install Bun
curl -fsSL https://bun.com/install | bash -s "bun-v1.3.0"

# Add Bun to PATH for this session
export PATH="$HOME/.bun/bin:$PATH"

# Clean frontend node_modules to prevent stale native binaries (e.g. esbuild)
# after container rebuilds where the workspace mount persists
cd /workspace/frontend
rm -rf node_modules packages/*/node_modules apps/*/node_modules
bun run setup
