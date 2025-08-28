# LiteLLM Setup for Devcontainer

## Overview
This document explains how to set up LiteLLM proxy in the devcontainer environment.

## GitHub Container Registry Authentication

LiteLLM's official Docker images are hosted on GitHub Container Registry (GHCR), which requires authentication even for public images due to rate limiting policies.

### Setup Process

1. **Create GitHub Personal Access Token**
   - Go to https://github.com/settings/tokens
   - Create a new token with `read:packages` scope
   - Copy the token

2. **Add Token to Environment**
   ```bash
   # Add to ~/.zshenv (or ~/.bashrc)
   export CR_PAT=your_github_token_here
   ```

3. **Reload Environment and Authenticate**
   ```bash
   source ~/.zshenv
   echo $CR_PAT | docker login ghcr.io -u your_github_username --password-stdin
   ```

## Docker Compose Configuration

The LiteLLM service is configured in `docker-compose.yml`:

```yaml
litellm:
  image: ghcr.io/berriai/litellm:main-stable
  networks:
    - eneo
  ports:
    - "4000:4000"
```

## Available Images

- `ghcr.io/berriai/litellm:main-stable` - Standard proxy (recommended)
- `ghcr.io/berriai/litellm-database:main-stable` - With database support
- `ghcr.io/berriai/litellm:main-latest` - Latest development version

## Usage

Once running, the LiteLLM proxy will be available at:
- Local: http://localhost:4000
- From other containers: http://litellm:4000

## Configuration

For advanced configuration, mount a config file:
```yaml
volumes:
  - ./litellm-config.yaml:/app/config.yaml
command: ["--config", "/app/config.yaml", "--port", "4000"]
```

## Troubleshooting

- **403 Forbidden errors**: Ensure you're authenticated with GHCR
- **JSON parse errors**: Usually caused by missing authentication
- **Image pull failures**: Check your GitHub token has `read:packages` scope