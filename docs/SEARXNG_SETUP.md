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

Create the main SearxNG settings file:

```bash
cat > /opt/eneo/searxng/settings.yml << 'EOF'
# SearXNG settings for Eneo integration
use_default_settings: true

general:
  # Instance name
  instance_name: "Eneo SearXNG"
  # Enable safe search by default
  safe_search: 1
  # Disable debug in production
  debug: false

search:
  # CRITICAL: Enable JSON format for API access
  formats:
    - html
    - json
  max_results: 20
  default_lang: "en"
  auto_lang: true

server:
  # Server settings
  port: 8080
  bind_address: "0.0.0.0"
  # Generate secure secret key for production
  secret_key: "REPLACE_WITH_RANDOM_SECRET"
  # Disable rate limiting for internal API calls
  limiter: false
  # Enable CORS for API access
  default_http_headers:
    X-Content-Type-Options: nosniff
    X-XSS-Protection: 1; mode=block
    X-Download-Options: noopen
    X-Robots-Tag: noindex, nofollow
    Referrer-Policy: no-referrer
    Access-Control-Allow-Origin: "*"
    Access-Control-Allow-Methods: "GET, POST, OPTIONS"
    Access-Control-Allow-Headers: "Content-Type"

ui:
  # UI settings
  static_use_hash: false
  default_theme: simple
  simple_style: auto
  center_alignment: false
  results_on_new_tab: false
  hotkeys: default

# Cache settings (uses Redis for performance)
redis:
  url: redis://redis:6379/1

# Enable various search engines
engines:
  # Web search engines
  - name: google
    engine: google
    shortcut: go
    disabled: false
    use_mobile_ui: false

  - name: bing
    engine: bing
    shortcut: bi
    disabled: false

  - name: duckduckgo
    engine: duckduckgo
    shortcut: ddg
    disabled: false

  # Knowledge sources
  - name: wikipedia
    engine: wikipedia
    shortcut: wp
    disabled: false

  # Code and technical sources
  - name: github
    engine: github
    shortcut: gh
    disabled: false

  - name: stackoverflow
    engine: stackoverflow
    shortcut: so
    disabled: false

  # News sources
  - name: google news
    engine: google_news
    shortcut: gn
    disabled: false

# Outgoing request settings
outgoing:
  # Request timeout
  request_timeout: 3.0
  # Max request timeout
  max_request_timeout: 10.0
  # Pool connections
  pool_connections: 100
  # Pool max size
  pool_maxsize: 20
  # Enable HTTP/2
  enable_http2: true
  # User agent
  useragent_suffix: "Eneo-SearxNG"

# Enable categories
categories_as_tabs:
  general:
    - google
    - bing
    - duckduckgo
  news:
    - google news
  it:
    - github
    - stackoverflow
EOF
```

### Step 3: Generate Secure Secret Key

Generate a secure secret key for production:

```bash
# Generate and replace the secret key
SECRET_KEY=$(openssl rand -hex 32)
sed -i "s/REPLACE_WITH_RANDOM_SECRET/$SECRET_KEY/g" /opt/eneo/searxng/settings.yml
echo "Generated secret key: $SECRET_KEY"
```

### Step 4: Add SearxNG to Docker Compose

Add SearxNG service to your existing Docker Compose configuration:

```yaml
# Add to your docker-compose.yml
services:
  # ... existing services ...

  searxng:
    image: searxng/searxng:latest
    container_name: eneo_searxng
    restart: unless-stopped
    ports:
      - "8085:8080"
    volumes:
      - /opt/eneo/searxng:/etc/searxng:rw
    environment:
      - SEARXNG_BASE_URL=http://localhost:8085/
    depends_on:
      - redis
    networks:
      - eneo_network
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:8080/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
```

### Step 5: Configure Eneo Backend

Update your Eneo backend configuration to use SearxNG:

```bash
# Add to your env_backend.env file
echo "SEARXNG_BASE_URL=http://searxng:8080" >> /opt/eneo/deployment/env_backend.env
```

For production deployments, use the external URL:
```bash
# For external access (if exposing SearxNG publicly)
echo "SEARXNG_BASE_URL=https://search.your-domain.com" >> /opt/eneo/deployment/env_backend.env
```

### Step 6: Start Services

Start SearxNG along with your other services:

```bash
cd /opt/eneo/deployment
docker compose up -d searxng

# Verify SearxNG is running
docker compose logs searxng
curl -s "http://localhost:8085/search?q=test&format=json" | jq .
```

---

## 🔧 Configuration Options

### Essential Settings

**JSON Format (CRITICAL):**
```yaml
search:
  formats:
    - html
    - json  # Required for API access
```

**CORS Headers (for web integration):**
```yaml
server:
  default_http_headers:
    Access-Control-Allow-Origin: "*"
    Access-Control-Allow-Methods: "GET, POST, OPTIONS"
    Access-Control-Allow-Headers: "Content-Type"
```

**Rate Limiting:**
```yaml
server:
  limiter: false  # Disable for internal API calls
```

### Search Engine Configuration

Enable/disable specific search engines:

```yaml
engines:
  - name: google
    engine: google
    disabled: false  # Set to true to disable

  - name: bing
    engine: bing
    disabled: false

  # Add custom engines
  - name: custom_engine
    engine: xpath
    search_url: https://example.com/search?q={query}
    url_xpath: //a[@class="result-link"]/@href
    title_xpath: //a[@class="result-link"]/text()
    content_xpath: //div[@class="result-content"]/text()
```

### Performance Tuning

```yaml
# Redis caching
redis:
  url: redis://redis:6379/1

# Request optimization
outgoing:
  request_timeout: 3.0
  max_request_timeout: 10.0
  pool_connections: 100
  pool_maxsize: 20
  enable_http2: true
```

---

## 🧪 Testing SearxNG Integration

### Verify JSON API

Test the JSON API endpoint:

```bash
# Basic search test
curl -s "http://localhost:8085/search?q=artificial+intelligence&format=json" | jq '.'

# Test specific categories
curl -s "http://localhost:8085/search?q=python&format=json&categories=it" | jq '.results[0]'

# Test with language parameter
curl -s "http://localhost:8085/search?q=test&format=json&language=en" | jq '.results | length'
```

### Verify Eneo Integration

Test from within Eneo backend:

```python
# Test script to verify integration
import asyncio
from intric.libs.clients.searxng_client import SearXNGClient

async def test_searxng():
    client = SearXNGClient()
    async with client:
        results = await client.search("artificial intelligence")
        print(f"Found {len(results.get('results', []))} results")
        for result in results.get('results', [])[:3]:
            print(f"- {result.get('title')}: {result.get('url')}")

# Run test
asyncio.run(test_searxng())
```

---

## 🔒 Production Security

### SSL/TLS Configuration

For production, secure SearxNG with SSL:

```yaml
# docker-compose.yml - Add Traefik labels
services:
  searxng:
    # ... existing config ...
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.searxng.rule=Host(`search.your-domain.com`)"
      - "traefik.http.routers.searxng.tls=true"
      - "traefik.http.routers.searxng.tls.certresolver=letsencrypt"
      - "traefik.http.services.searxng.loadbalancer.server.port=8080"
```

### Access Control

Restrict access to SearxNG:

```yaml
# Add IP whitelist
server:
  default_http_headers:
    Access-Control-Allow-Origin: "https://your-eneo-domain.com"
```

Or use network isolation:

```yaml
# Remove public port exposure
services:
  searxng:
    # ports:
    #   - "8085:8080"  # Comment out for internal-only access
    expose:
      - "8080"
```

### Security Headers

```yaml
server:
  default_http_headers:
    X-Content-Type-Options: nosniff
    X-XSS-Protection: 1; mode=block
    X-Download-Options: noopen
    X-Robots-Tag: noindex, nofollow
    Referrer-Policy: no-referrer
    Strict-Transport-Security: max-age=31536000; includeSubDomains
```

---

## 📊 Monitoring and Maintenance

### Health Checks

Monitor SearxNG health:

```bash
# Check service status
docker compose ps searxng

# View logs
docker compose logs -f searxng

# Test API endpoint
curl -f "http://localhost:8085/search?q=test&format=json" || echo "SearxNG API failed"
```

### Performance Monitoring

```bash
# Monitor resource usage
docker stats eneo_searxng

# Check Redis cache usage
docker compose exec redis redis-cli info memory
```

### Log Analysis

```bash
# View search patterns
docker compose logs searxng | grep "search request"

# Monitor errors
docker compose logs searxng | grep -i error

# Check response times
docker compose logs searxng | grep "response time"
```

---

## 🛠️ Troubleshooting

### Common Issues

<details>
<summary>🔍 JSON Format Not Working</summary>

**Problem**: API returns HTML instead of JSON

**Solution**:
```yaml
# Ensure JSON format is enabled in settings.yml
search:
  formats:
    - html
    - json  # Must be present
```

**Test**:
```bash
curl "http://localhost:8085/search?q=test&format=json" -H "Accept: application/json"
```

</details>

<details>
<summary>🚫 CORS Errors</summary>

**Problem**: Cross-origin requests blocked

**Solution**:
```yaml
server:
  default_http_headers:
    Access-Control-Allow-Origin: "*"
    Access-Control-Allow-Methods: "GET, POST, OPTIONS"
    Access-Control-Allow-Headers: "Content-Type"
```

</details>

<details>
<summary>🐌 Slow Search Results</summary>

**Problem**: Search requests timing out

**Solutions**:
1. **Increase timeouts**:
```yaml
outgoing:
  request_timeout: 5.0
  max_request_timeout: 15.0
```

2. **Disable slow engines**:
```yaml
engines:
  - name: slow_engine
    disabled: true
```

3. **Enable Redis caching**:
```yaml
redis:
  url: redis://redis:6379/1
```

</details>

<details>
<summary>🔧 Configuration Not Loading</summary>

**Problem**: Settings changes not taking effect

**Solution**:
```bash
# Restart SearxNG container
docker compose restart searxng

# Check configuration mount
docker compose exec searxng ls -la /etc/searxng/

# Verify configuration syntax
docker compose exec searxng python -c "import yaml; yaml.safe_load(open('/etc/searxng/settings.yml'))"
```

</details>

---

## 📚 Advanced Configuration

### Custom Search Engines

Add specialized search engines:

```yaml
engines:
  # Academic papers
  - name: arxiv
    engine: arxiv
    shortcut: arx
    disabled: false

  # Code search
  - name: searchcode
    engine: searchcode_code
    shortcut: scc
    disabled: false

  # Documentation
  - name: devdocs
    engine: devdocs
    shortcut: dd
    disabled: false
```

### Language-Specific Configuration

```yaml
# Multi-language support
search:
  default_lang: "auto"
  auto_lang: true

# Language-specific engines
engines:
  - name: google_swedish
    engine: google
    shortcut: gosv
    language: sv
    disabled: false
```

### Custom Result Processing

```yaml
# Result customization
search:
  max_results: 50
  formats:
    - json
    - csv  # Additional formats

# Custom result ranking
engines:
  - name: google
    engine: google
    weight: 1.0  # Increase weight for better ranking
```

---

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

SearxNG integration enables web search capabilities in Eneo assistants:

1. **Automatic Integration**: Web search is automatically available when SearxNG is configured
2. **Assistant Instructions**: Include web search instructions in assistant prompts
3. **Search Queries**: Assistants can perform web searches to answer questions

Example assistant instruction:
```
You are a helpful assistant with access to web search. When users ask questions that require current information, use web search to find relevant and up-to-date answers.
```

---

## 📞 Support and Resources

### Documentation Links
- **SearxNG Official Docs**: https://docs.searxng.org/
- **Engine Configuration**: https://docs.searxng.org/admin/engines.html
- **Settings Reference**: https://docs.searxng.org/admin/settings.html

### Community Support
- **SearxNG GitHub**: https://github.com/searxng/searxng
- **Eneo Discussions**: https://github.com/eneo-ai/eneo/discussions

### Troubleshooting Resources
- Check the [Eneo Troubleshooting Guide](TROUBLESHOOTING.md)
- Review SearxNG logs: `docker compose logs searxng`
- Test API endpoints manually before reporting issues

---

**Next Steps:**
1. Follow the Docker setup steps above
2. Configure your search engines based on your needs
3. Test the integration with Eneo
4. Monitor performance and adjust settings as needed

This setup provides Eneo with powerful, privacy-focused web search capabilities through SearxNG's robust metasearch engine.
