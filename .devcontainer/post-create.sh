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

# Install Python dependencies
cd /workspace/backend
uv sync

# Install pre-commit globally and setup hooks
cd /workspace
uv tool install pre-commit
pre-commit install

# Install Bun
curl -fsSL https://bun.com/install | bash -s "bun-v1.3.0"

# Add Bun to PATH for this session
export PATH="$HOME/.bun/bin:$PATH"

# Install frontend dependencies
cd /workspace/frontend
bun run setup
