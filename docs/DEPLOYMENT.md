# Eneo Production Deployment (Docker Compose)

This guide provides a streamlined, step-by-step process to deploy Eneo in a production environment on a single Linux host using Docker Compose.

> **Note**: For local development, please see the [INSTALLATION.md](./INSTALLATION.md) guide.

## 📋 Prerequisites

Before you begin, ensure you have the following:

- **Linux server** with Docker and the Docker Compose plugin installed
- **Domain name** (e.g., `eneo.your-company.com`) with its DNS A record pointing to your server's public IP address
- **Email address** for notifications from Let's Encrypt regarding your SSL certificate
- **At least one AI provider API key** (e.g., OpenAI, Anthropic, Google Gemini)
- **Server firewall** configured to allow inbound traffic on ports 80 (HTTP) and 443 (HTTPS)

## 🐳 The Docker Compose Setup

The provided `docker-compose.yml` file defines all the services needed to run Eneo as a complete, ready-to-use stack:

- **`traefik`**: A reverse proxy that handles incoming traffic, routes it to the correct service, and automatically manages SSL certificates
- **`frontend`**: The web interface for Eneo
- **`backend`**: The main API and application logic
- **`worker`**: A background service for processing heavy tasks like document ingestion and crawling
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

The frontend needs to know its public URL and must share the exact same `JWT_SECRET` as the backend.

```bash
# 1. Set the public URLs (use your actual domain)
echo "ORIGIN=https://eneo.your-company.com" >> env_frontend.env
echo "INTRIC_BACKEND_URL=https://eneo.your-company.com" >> env_frontend.env

# 2. Copy the JWT_SECRET from the backend's .env file
JWT_SECRET_VALUE=$(grep '^JWT_SECRET=' env_backend.env | cut -d= -f2-)
echo "JWT_SECRET=$JWT_SECRET_VALUE" >> env_frontend.env
```

> **Important**: The `JWT_SECRET` must be identical in both `env_backend.env` and `env_frontend.env` for authentication to work correctly.

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

**Stop and remove all containers:**
```bash
docker compose down
# Note: This does not delete your data volumes (database, etc.)
# To remove data as well, use: docker compose down --volumes
```

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

## 🔧 Troubleshooting

If you encounter issues, here are some common problems and their solutions.

### SSL Certificate Not Issued (HTTPS not working)
- Confirm your domain's DNS A record correctly points to the server's IP
- Check the Traefik logs for errors from Let's Encrypt: 
  ```bash
  docker compose logs -f traefik
  ```

### "Unauthorized" or General Login Errors
- Ensure the `JWT_SECRET` is exactly the same in both `env_backend.env` and `env_frontend.env`

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

### Login issues when running locally (for development)
If you are running the frontend locally for development and cannot log in, you may need to edit `vite.config.ts`. Change the server configuration from `host: process.env.HOST ? "0.0.0.0" : undefined,` to explicitly bind to all network interfaces:

```javascript
server: {
  host: "0.0.0.0",
  port: 3000,
  strictPort: true
},
```

## 🔒 Security Checklist

Review this checklist to ensure your deployment is secure:

- [ ] Domain and email are correctly set in `docker-compose.yml`
- [ ] A strong, unique password has been set for `POSTGRES_PASSWORD`
- [ ] Strong, unique secrets have been generated for `JWT_SECRET` and `URL_SIGNING_KEY`
- [ ] The default user password has been changed immediately after the first login
- [ ] Your server's firewall only exposes ports 80 and 443 to the internet
