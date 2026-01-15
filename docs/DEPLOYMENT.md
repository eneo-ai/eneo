# Eneo Production Deployment (Docker Compose)

This guide provides a streamlined, step-by-step process to deploy Eneo in a production environment on a single Linux host using Docker Compose.

> **Note**: For local development, please see the [INSTALLATION.md](./INSTALLATION.md) guide.

> **Quick Reference Available:** Already familiar with the process? Use the [Quick Reference Guide](./deployment/README.md) for condensed commands.

## 📁 Required Files Location

All deployment files (`docker-compose.yml` and environment templates) are located in the [`docs/deployment/`](https://github.com/eneo-ai/eneo/tree/develop/docs/deployment) folder:

```bash
# Clone the repository and navigate to deployment folder
git clone https://github.com/eneo-ai/eneo.git
cd eneo/docs/deployment/

# You'll find these files:
# - docker-compose.yml
# - env_backend.template
# - env_frontend.template
# - env_db.template
```

## 📋 Prerequisites

Before you begin, ensure you have the following:

- **Linux server** with Docker and the Docker Compose plugin installed
- **Domain name** (e.g., `eneo.your-company.com`) with its DNS A record pointing to your server's public IP address
- **Email address** for notifications from Let's Encrypt regarding your SSL certificate
- **At least one AI provider API key** (e.g., OpenAI, Anthropic, Google Gemini)
- **Server firewall** configured to allow inbound traffic on ports 80 (HTTP) and 443 (HTTPS)

## 🔒 Security Checklist

Review this checklist before you begin deployment. Ensure your setup meets these security requirements:

- [ ] Domain and email are correctly set in `docker-compose.yml`
- [ ] A strong, unique password will be generated for `POSTGRES_PASSWORD`
- [ ] Strong, unique secrets will be generated for `JWT_SECRET` and `URL_SIGNING_KEY`
- [ ] You will change the default user password immediately after first login
- [ ] Your server's firewall only exposes ports 80 and 443 to the internet

> **Important**: Complete all items in this checklist during the deployment process. Skipping security steps puts your deployment at risk.

## 🐳 The Docker Compose Setup

The provided `docker-compose.yml` file defines all the services needed to run Eneo as a complete, ready-to-use stack:

- **`traefik`**: A reverse proxy that handles incoming traffic, routes it to the correct service, and automatically manages SSL certificates
- **`frontend`**: The web interface for Eneo
- **`backend`**: The main API and application logic
- **`worker`**: A background service for processing heavy tasks like document ingestion, crawling, and audit log exports
- **`db`**: A PostgreSQL database with the pgvector extension for storing all application data
- **`redis`**: An in-memory data store used for caching and managing background jobs

### A Note on Flexibility

> This `docker-compose.yml` file with Traefik is a convenient, all-in-one solution, but it is **not mandatory**.
>
> The Eneo frontend and backend images are self-contained and can be run in any container environment. You can integrate them into your own custom `docker-compose.yml` file or deploy them using other tools like Nginx, Caddy, or cloud-based load balancers if you prefer.

## 🚀 Deployment in 4 Steps

Follow these steps to get your Eneo instance up and running.

### Step 1: Prepare Configuration Files

First, copy the provided template files to create your local environment configuration.

```bash
cp env_backend.template env_backend.env
cp env_frontend.template env_frontend.env
cp env_db.template env_db.env
```

### Step 2: Configure Your Environment

This is the most critical step. You will set the required variables for your specific setup.

#### A. Domain & SSL in `docker-compose.yml`

You need to tell Traefik (our reverse proxy) which domain to use and what email to use for SSL certificate registration.

Open `docker-compose.yml` and replace the following placeholders:
- **`your-email@domain.com`**: Replace with your actual email address
- **`your-domain.com`**: Replace in all four locations with your actual domain name

<details>
<summary>💡 Click for an example using sed</summary>

```bash
# Replace with your email for Let's Encrypt notifications
sed -i 's/your-email@domain.com/ops@your-company.com/g' docker-compose.yml

# Replace with your domain name for Traefik routing rules
sed -i 's/your-domain.com/eneo.your-company.com/g' docker-compose.yml
```

</details>

#### B. Database Password in `env_db.env`

Generate a secure password for your PostgreSQL database.

```bash
# This command generates a strong password and appends it to the file
echo "POSTGRES_PASSWORD=$(openssl rand -base64 32)" >> env_db.env
```

#### C. Backend Secrets & API Keys in `env_backend.env`

Configure the backend with security secrets and your chosen AI provider's API key.

```bash
# 1. Add at least ONE AI provider key (example for OpenAI)
echo "OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxx" >> env_backend.env

# 2. Generate and add required security secrets
echo "JWT_SECRET=$(openssl rand -hex 32)" >> env_backend.env
echo "URL_SIGNING_KEY=$(openssl rand -hex 32)" >> env_backend.env
```

#### D. Frontend Configuration in `env_frontend.env`

The frontend needs three URLs configured and must share the exact same `JWT_SECRET` as the backend.

```bash
# 1. Set the URLs (replace eneo.your-company.com with your actual domain)
# Server-side URL - used by frontend SSR
echo "INTRIC_BACKEND_URL=https://eneo.your-company.com" >> env_frontend.env

# Internal URL - server-to-server within Docker (skips Traefik, faster)
echo "INTRIC_BACKEND_SERVER_URL=http://backend:8000" >> env_frontend.env

# Client-side URL - used by browser for API calls (PUBLIC_ exposes to browser)
echo "PUBLIC_INTRIC_BACKEND_URL=https://eneo.your-company.com" >> env_frontend.env

# Origin - used for cookies and CORS
echo "ORIGIN=https://eneo.your-company.com" >> env_frontend.env

# Public origin - required for OIDC authentication
echo "PUBLIC_ORIGIN=https://eneo.your-company.com" >> env_frontend.env

# 2. Copy the JWT_SECRET from the backend's .env file
JWT_SECRET_VALUE=$(grep '^JWT_SECRET=' env_backend.env | cut -d= -f2-)
echo "JWT_SECRET=$JWT_SECRET_VALUE" >> env_frontend.env
```

> **Important**:
> - The `JWT_SECRET` must be identical in both `env_backend.env` and `env_frontend.env` for authentication to work correctly.
> - `INTRIC_BACKEND_SERVER_URL` must be `http://backend:8000` (using Docker service name, not `localhost`).
> - `PUBLIC_INTRIC_BACKEND_URL` is the URL the browser uses - must be your public domain.
> - `PUBLIC_ORIGIN` is required for OIDC authentication.

### Step 3: Launch the Application

With the configuration complete, you can now start all the services.

```bash
# Create the external network required by Traefik
docker network create proxy_tier

# Start all services in the background
docker compose up -d
```

The initial startup may take a few minutes as Docker downloads the necessary container images. Once done, you can visit `https://your-domain.com` in your browser.

### Step 4: First-Time Login (Critical Security Step)

After deployment, you **must** secure the default account.

1. Log in with the default credentials:
   - **Email**: `user@example.com`
   - **Password**: `Password1!`

2. **Immediately** navigate to the user menu in the top-right corner and change your password.

**Congratulations!** Your Eneo instance is now deployed and secured. 🎉

## ⚙️ Managing Your Instance

Here are some common commands for operating your Eneo deployment.

**Check the status of all services:**
```bash
docker compose ps
```

**View logs for a specific service (e.g., backend):**
```bash
docker compose logs -f backend
```

**Update to the latest container images:**
```bash
docker compose pull
docker compose up -d
```

> **Production Tip:** For production deployments, consider pinning to specific version tags (e.g., `v1.2.3`) instead of using `latest`. This gives you control over when updates are applied. See [Version Pinning](#production-best-practice-version-pinning) for details.

**Stop and remove all containers:**
```bash
docker compose down
# Note: This does not delete your data volumes (database, etc.)
# To remove data as well, use: docker compose down --volumes
```

### Docker Volumes

Eneo uses several Docker volumes for persistent data storage:

| Volume | Path | Description |
|--------|------|-------------|
| `eneo_postgres_data` | `/var/lib/postgresql/data` | PostgreSQL database storage |
| `eneo_redis_data` | `/data` | Redis cache and job queue state |
| `eneo_backend_data` | `/app/data` | Backend application data |
| `eneo_exports_data` | `/app/exports` | Audit log exports (auto-cleaned after 24h) |
| `traefik_letsencrypt` | `/letsencrypt` | SSL certificates |

> **Note**: The `eneo_exports_data` volume is shared between `backend` and `worker` services for large audit log exports. Export files are automatically cleaned up after 24 hours.

## 🔄 Upgrading Your Eneo Instance

### Production Best Practice: Version Pinning

For production deployments, we **strongly recommend** pinning to specific version tags instead of using `latest`.

**Why pin versions?**
- **Predictable deployments** - Know exactly which version is running
- **Controlled upgrades** - Test new versions in staging before production
- **Easy rollbacks** - Return to a previous working version if issues arise
- **Audit trail** - Clear version history in your docker-compose.yml

**How to pin versions:**

The example `docker-compose.yml` uses `:latest` tags to keep documentation current, but you should replace these with specific versions:

```yaml
# ❌ Example (uses latest - not recommended for production)
frontend:
  image: ghcr.io/eneo-ai/eneo-frontend:latest

backend:
  image: ghcr.io/eneo-ai/eneo-backend:latest

worker:
  image: ghcr.io/eneo-ai/eneo-backend:latest
```

```yaml
# ✅ Production (pinned to specific version)
frontend:
  image: ghcr.io/eneo-ai/eneo-frontend:v1.2.3

backend:
  image: ghcr.io/eneo-ai/eneo-backend:v1.2.3

worker:
  image: ghcr.io/eneo-ai/eneo-backend:v1.2.3
```

**Where to find versions:**
- GitHub Releases: https://github.com/eneo-ai/eneo/releases
- Container Registry: https://github.com/orgs/eneo-ai/packages

**Controlled upgrade workflow:**
```bash
# 1. Check for new versions at GitHub releases

# 2. Update version tags in docker-compose.yml
#    Change: v1.2.3 → v1.2.4

# 3. Pull the specific version
docker compose pull

# 4. Deploy the updated version
docker compose up -d

# 5. Verify the new version is running
docker compose exec backend python -c "import intric; print(intric.__version__)"
```

### Before You Upgrade

> **⚠️ IMPORTANT:** Always back up your data before upgrading to a new version.

```bash
# Back up your database
docker compose exec db pg_dump -U eneo eneo_db > backup_$(date +%Y%m%d).sql

# Back up your volumes
docker compose down
docker run --rm -v eneo_postgres_data:/data -v $(pwd):/backup ubuntu tar czf /backup/postgres_data_backup.tar.gz /data
```

### Upgrading Between Minor Versions

For routine updates (e.g., v1.2.3 → v1.2.4):

**With version pinning (recommended):**
```bash
# 1. Edit docker-compose.yml and update version tags
# 2. Pull and deploy the new version
docker compose pull
docker compose up -d
```

**With latest tags (if you haven't pinned versions yet):**
```bash
docker compose pull
docker compose up -d
```

> **Note:** Using pinned versions gives you control over when updates are applied. With `latest`, updates happen whenever you run `docker compose pull`, which may introduce unexpected changes.

### Upgrading Between Major Versions or After Long Gaps

If upgrading from a very old image or across major versions (e.g., develop branch to main branch), you may encounter database migration issues.

**Symptoms:**
- "Unauthorized" errors in the frontend after upgrade
- Backend fails to start with database errors
- User authentication no longer works

**Resolution:**

The safest approach is to start fresh:

```bash
# 1. Back up your data (if needed)
docker compose exec db pg_dump -U eneo eneo_db > backup.sql

# 2. Stop all containers
docker compose down

# 3. Remove volumes (ensures clean state)
docker volume rm eneo_postgres_data eneo_redis_data eneo_backend_data
# Verify volumes are removed: docker volume ls

# 4. Start with fresh installation
docker compose up -d

# 5. Restore data if needed (advanced)
# docker compose exec -T db psql -U eneo eneo_db < backup.sql
```

> **Note:** If you need to preserve your data across major migrations, use `pg_dump` to export, then restore to the fresh database. This may require manual schema adjustments depending on the changes between versions.

## ✨ Advanced Configuration & Features

Enable optional features by setting variables in `env_backend.env`.

**Enable Crawler & Document Upload:**
> To use the web crawler or upload documents, the worker service must be running and at least one embedding model must be enabled in the admin panel.

**Access Sysadmin Endpoints:**
To get access to system administration endpoints, set an API key:
```bash
INTRIC_SUPER_API_KEY=your-secure-api-key
```

**Access Modules Endpoint:**
To get access to the modules endpoint, set a separate, higher-privileged API key:
```bash
INTRIC_SUPER_DUPER_API_KEY=your-other-secure-api-key
```

### Multi-Tenant Features

Eneo supports advanced multi-tenancy for organizations hosting multiple municipalities or departments:

**Per-Tenant LLM Credentials:**

Enable tenant-specific API keys for isolated billing and compliance:

```bash
# 1. Generate encryption key (required for credential security)
cd backend
docker compose exec backend uv run python -m intric.cli.generate_encryption_key

# 2. Add to env_backend.env
ENCRYPTION_KEY=<generated-44-char-key>
TENANT_CREDENTIALS_ENABLED=true

# 3. Configure per-tenant credentials via API
curl -X PUT https://your-domain.com/api/v1/sysadmin/tenants/{tenant_id}/credentials/openai \
  -H "X-API-Key: ${INTRIC_SUPER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "sk-proj-tenant-specific-key"}'
```

**Per-Tenant Identity Providers:**

Allow each tenant to use their own IdP (Entra ID, Auth0, Okta, etc.):

```bash
# 1. Enable federation mode in env_backend.env
FEDERATION_PER_TENANT_ENABLED=true
ENCRYPTION_KEY=<same-key-as-above>

# 2. Configure per-tenant IdP via API
curl -X PUT https://your-domain.com/api/v1/sysadmin/tenants/{tenant_id}/federation \
  -H "X-API-Key: ${INTRIC_SUPER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "entra_id",
    "discovery_endpoint": "https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration",
    "client_id": "...",
    "client_secret": "...",
    "allowed_domains": ["municipality.gov"]
  }'
```

**⚠️ Important Notes:**
- Backup your `ENCRYPTION_KEY` securely - lost keys make encrypted data unrecoverable
- In strict mode (`TENANT_CREDENTIALS_ENABLED=true`), tenants without configured credentials cannot use LLM features
- Federation requires each tenant to have a unique `slug` - run `uv run python -m intric.cli.backfill_tenant_slugs` if needed

**Documentation:**
- [Federation Per Tenant](./FEDERATION_PER_TENANT.md) - Architecture and setup
- [Multi-Tenant Credentials](./MULTI_TENANT_CREDENTIALS.md) - Credential management
- [Multi-Tenant OIDC Setup](./MULTITENANT_OIDC_SETUP_GUIDE.md) - Step-by-step guide

## 🔧 Troubleshooting

If you encounter issues, here are some common problems and their solutions.

### SSL Certificate Not Issued (HTTPS not working)
- Confirm your domain's DNS A record correctly points to the server's IP
- Check the Traefik logs for errors from Let's Encrypt:
  ```bash
  docker compose logs -f traefik
  ```

### "Unauthorized" or General Login Errors

**First, check JWT configuration:**
- Ensure the `JWT_SECRET` is exactly the same in both `env_backend.env` and `env_frontend.env`

**If upgrading from an old version:**
- Database migration issues can cause authentication failures
- See the [Upgrading Your Eneo Instance](#upgrading-your-eneo-instance) section for guidance on starting fresh

### Default User Not Created (Can't Login)
If the database tables exist but you can't login with `user@example.com` / `Password1!`:
- Check that the `DEFAULT_*` variables are set (not commented out) in `env_backend.env`:
  ```bash
  DEFAULT_TENANT_NAME=ExampleTenant
  DEFAULT_TENANT_QUOTA_LIMIT=10737418240
  DEFAULT_USER_NAME=ExampleUser
  DEFAULT_USER_EMAIL=user@example.com
  DEFAULT_USER_PASSWORD=Password1!
  ```
- Re-run the database initialization:
  ```bash
  docker compose run --rm db-init
  ```

### Frontend Shows "ECONNREFUSED 127.0.0.1:8000"
This means the frontend is trying to connect to `localhost` instead of the backend container:
- Check `env_frontend.env` has the correct URLs:
  ```bash
  INTRIC_BACKEND_URL=https://your-domain.com        # Public URL (your actual domain)
  INTRIC_BACKEND_SERVER_URL=http://backend:8000     # Must be "backend", NOT "localhost"
  ORIGIN=https://your-domain.com
  ```
- In Docker, `localhost` means "this container" - use `backend` (the Docker service name) instead

### HTTP to HTTPS Redirect Not Working
If you see `middleware "redirect-to-https@docker" does not exist` in Traefik logs:
- Ensure the `traefik` service in `docker-compose.yml` has `traefik.enable=true` in its labels:
  ```yaml
  traefik:
    labels:
      - "traefik.enable=true"  # This line is required!
      - "traefik.http.middlewares.redirect-to-https.redirectscheme.scheme=https"
      - "traefik.http.middlewares.redirect-to-https.redirectscheme.permanent=true"
  ```

### 502 Bad Gateway or 404 Not Found
- Verify that you replaced `your-domain.com` in all four places within `docker-compose.yml`
- Check the backend and frontend logs for startup errors:
  ```bash
  docker compose logs -f backend
  docker compose logs -f frontend
  ```

### Cannot click "Users" in Admin Panel
- Ensure user access management is enabled in `env_backend.env`:
  ```bash
  USING_ACCESS_MANAGEMENT=True
  ```

### Cannot create "Apps"
- This feature often relies on a transcription model
- Go to the admin panel, navigate to the "Models" page, select the "Transcription" tab, and enable a model like Whisper

### Errors when uploading large files (e.g., PDFs)
- The default upload limits might be too low
- Increase the values in `env_backend.env` (values are in bytes, 10485760 = 10MB):
  ```bash
  UPLOAD_MAX_FILE_SIZE=10485760
  ```

