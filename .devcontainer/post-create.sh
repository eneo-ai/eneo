#!/bin/bash
# Copyright (c) 2024 Sundsvalls Kommun
#
# Licensed under the MIT License.

set -euf -o pipefail

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

# Install Node.js dependencies
cd /workspace/frontend

npm install -g pnpm@9.12.3
# Set pnpm store directory
pnpm config set store-dir $HOME/.pnpm-store
pnpm run setup
