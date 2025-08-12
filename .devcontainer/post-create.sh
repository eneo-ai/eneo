#!/bin/bash
# Copyright (c) 2024 Sundsvalls Kommun
#
# Licensed under the MIT License.

set -euf -o pipefail

# Install system dependencies
sudo apt-get update
sudo apt-get install -y libmagic1 ffmpeg

# Install Python dependencies
python -m pip install --no-cache-dir poetry

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
