FROM mcr.microsoft.com/devcontainers/python:3.11-bookworm

# Remove Yarn repository (expired GPG key causes apt-get update failures)
RUN rm -f /etc/apt/sources.list.d/yarn.list

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    ffmpeg \
    fontconfig \
    fonts-dejavu-core \
    libharfbuzz-subset0 \
    libmagic1 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libsndfile1 \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*
