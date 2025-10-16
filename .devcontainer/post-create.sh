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

# Install Python dependencies
python -m pip install --no-cache-dir poetry==2.1.3

cd /workspace/backend
python -m poetry config virtualenvs.in-project true
python -m poetry install

# Install pre-commit globally and setup hooks
cd /workspace
python -m pip install pre-commit
pre-commit install

# Install Node.js dependencies
cd /workspace/frontend

npm install -g pnpm@9.12.3
# Set pnpm store directory
pnpm config set store-dir $HOME/.pnpm-store
pnpm run setup
