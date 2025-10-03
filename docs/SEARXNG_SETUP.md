# SearxNG Setup for Eneo

This guide covers setting up SearxNG as a web search engine for Eneo. SearxNG provides privacy-focused web search capabilities that can be integrated with Eneo's AI assistants for enhanced information retrieval.

---

## 🎯 Overview

**SearxNG** is a privacy-respecting, hackable metasearch engine that aggregates results from multiple search engines without storing search data. Eneo integrates with SearxNG to provide web search capabilities for AI assistants.

**Benefits:**
- **Privacy-focused**: No tracking or data collection
- **Multiple sources**: Aggregates results from Google, Bing, DuckDuckGo, and more
- **Self-hosted**: Full control over your search infrastructure
- **JSON API**: Perfect for programmatic access by AI assistants

---

## 🐳 Docker Setup (Recommended)

### Prerequisites

- Docker and Docker Compose installed
- Basic understanding of Docker networking
- Access to modify your Eneo configuration

### Step 1: Create SearxNG Configuration

Create a directory structure for SearxNG configuration:

```bash
# Create SearxNG configuration directory
mkdir -p /opt/eneo/searxng
cd /opt/eneo/searxng
```

### Step 2: Create Settings Configuration

Create the main SearxNG settings file (see [.devcontainer/searxng/settings.yml](.devcontainer/searxng/settings.yml) for a reference example).

### Step 3: Generate Secure Secret Key

Generate a secure secret key for production:

```bash
# Generate and replace the secret key
SECRET_KEY=$(openssl rand -hex 32)
sed -i "s/REPLACE_WITH_RANDOM_SECRET/$SECRET_KEY/g" /opt/eneo/searxng/settings.yml
echo "Generated secret key: $SECRET_KEY"
```

### Step 4: Add SearxNG to Docker Compose

Add SearxNG service to your existing Docker Compose configuration (see [.devcontainer/docker-compose.yml](.devcontainer/docker-compose.yml) for a reference example).

### Step 5: Configure Eneo Backend

Update your Eneo backend configuration to use SearxNG by setting the internal searxng address:

```bash
# Add to your backends env
SEARXNG_BASE_URL=http://searxng:8080 # Update with your selected internal service name
```

---

## 🔧 Configuration Options

### Essential Settings for Eneo Integration

For Eneo to work properly with SearxNG, ensure these settings are configured:

1. **JSON Format (CRITICAL)**: Enable JSON format in `search.formats` - required for API access
2. **CORS Headers**: Configure `Access-Control-Allow-Origin` in `server.default_http_headers` for web integration
3. **Rate Limiting**: Disable `server.limiter` for internal API calls

See [.devcontainer/searxng/settings.yml](.devcontainer/searxng/settings.yml) for a working example configuration.

### Additional Configuration

For detailed configuration options, refer to the official SearxNG documentation:

- **Settings Reference**: https://docs.searxng.org/admin/settings.html
- **Engine Configuration**: https://docs.searxng.org/admin/engines.html
- **Performance Tuning**: https://docs.searxng.org/admin/buildhosts.html

---

## 🧪 Testing SearxNG Integration

### Verify JSON API

Test the JSON API endpoint (adjust the URL and port based on your deployment):

```bash
# Basic search test (devcontainer uses port 8085, adjust for your deployment)
curl -s "http://localhost:8085/search?q=artificial+intelligence&format=json" | jq '.'

# Test specific categories
curl -s "http://localhost:8085/search?q=python&format=json&categories=it" | jq '.results[0]'

# Test with language parameter
curl -s "http://localhost:8085/search?q=test&format=json&language=en" | jq '.results | length'
```

### Verify Eneo Integration

Test from within the Eneo backend container to verify the integration works correctly. The backend uses the internal Docker network URL configured in your environment variables (e.g., `SEARXNG_BASE_URL=http://searxng:8080`).

## 🔗 Integration with Eneo

### Backend Configuration

Ensure your backend environment includes:

```bash
# Required for SearxNG integration
SEARXNG_BASE_URL=http://searxng:8080

# Optional: Configure search behavior
SEARCH_MAX_RESULTS=10
SEARCH_TIMEOUT=5
```

### Using Web Search in Assistants

To enable web search functionality in Eneo:

1. **Backend Configuration**: Configure `SEARXNG_BASE_URL` in your backend environment
2. **Frontend Configuration**: Enable `SHOW_WEB_SEARCH=true` in your frontend environment to show web search UI controls
3. **Usage**: Users can then enable web search when interacting with assistants

**Next Steps:**
1. Follow the Docker setup steps above
2. Configure your search engines based on your needs
3. Test the integration with Eneo
4. Monitor performance and adjust settings as needed

This setup provides Eneo with powerful, privacy-focused web search capabilities through SearxNG's robust metasearch engine.
