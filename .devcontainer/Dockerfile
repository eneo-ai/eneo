FROM mcr.microsoft.com/devcontainers/python:3.11-bookworm

# Remove Yarn repository (expired GPG key causes apt-get update failures)
RUN rm -f /etc/apt/sources.list.d/yarn.list
