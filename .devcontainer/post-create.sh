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

# Install system dependencies
sudo apt-get update
sudo apt-get install -y libmagic1 ffmpeg

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# The backend .venv, frontend node_modules, and web-next .next cache are on
# named Docker volumes (see docker-compose.yml). Docker creates named volume
# mount points as root:root, but post-create.sh runs as vscode — without these
# chowns, uv/bun/next fail to write into them.
sudo chown vscode:vscode /workspace/backend/.venv \
    /workspace/frontend/node_modules \
    /workspace/frontend/apps/web-next/.next

# Install Python dependencies
# Use --reinstall-package to ensure the project entry points are up-to-date
# even when the .venv volume persists across container rebuilds
cd /workspace/backend
uv sync --reinstall-package intric

# Install pre-commit globally and setup hooks
cd /workspace
uv tool install pre-commit
LOCAL_HOOKS_PATH="$(git config --local --get core.hooksPath || true)"
if [ -n "$LOCAL_HOOKS_PATH" ] && [ ! -d "$LOCAL_HOOKS_PATH" ]; then
    echo "Resetting repo-local core.hooksPath ('$LOCAL_HOOKS_PATH') to Git default for the devcontainer"
    git config --local --unset-all core.hooksPath
fi
pre-commit install --overwrite --install-hooks \
    --hook-type pre-commit \
    --hook-type commit-msg \
    --hook-type pre-push

# Install Node 22 via the nvm that ships in the base image
# (apps/web-next runs Next.js, whose CLI requires Node >= 20.9; Bun alone is not enough)
set +u # nvm.sh references unset variables
source /usr/local/share/nvm/nvm.sh
nvm install 22
nvm alias default 22
set -u

# Install Bun
curl -fsSL https://bun.com/install | bash -s "bun-v1.3.0"

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
