#!/bin/bash
# Copyright (c) 2024 Sundsvalls Kommun
#
# Licensed under the MIT License.

set -euf -o pipefail

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

# Install Bun
curl -fsSL https://bun.com/install | bash -s "bun-v1.2.23"

# Add Bun to PATH for this session
export PATH="$HOME/.bun/bin:$PATH"

# Install frontend dependencies
cd /workspace/frontend
bun run setup
