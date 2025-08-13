# Production Deployment Guide

This guide covers deploying Eneo in production environments. For development setup, see the [Installation Guide](INSTALLATION.md).

---

## 🎯 Deployment Overview

**Deployment Strategy:**
- **Container-based** deployment using Docker/Podman
- **Traefik** reverse proxy with automatic SSL certificates
- **PostgreSQL** with pgvector for vector search
- **Redis** for caching and task queuing
- **Background workers** for document processing

**Supported Environments:**
- Linux servers (Ubuntu, RHEL, CentOS)
- Cloud platforms (AWS, Azure, GCP)
- On-premises infrastructure
- Kubernetes clusters

---

## 🏗️ Production Architecture

<details>
<summary>🔍 Click to view production architecture diagram</summary>

```mermaid
graph TB
    subgraph "External Layer"
        INT[Internet]
        DNS[DNS Provider]
    end
    
    subgraph "Edge Layer"
        LB[Load Balancer<br/>Optional]
        CF[Cloudflare<br/>Optional]
    end
    
    subgraph "Application Layer"
        TR[Traefik<br/>Reverse Proxy<br/>SSL Termination]
        FE[Eneo Frontend<br/>Container]
        BE[Eneo Backend<br/>Container]
        WK[Background Workers<br/>Container]
    end
    
    subgraph "Data Layer"
        DB[(PostgreSQL<br/>+ pgvector)]
        RD[(Redis<br/>Cache/Queue)]
        FS[File Storage<br/>Persistent Volume]
    end
    
    subgraph "External Services"
        LE[Let's Encrypt<br/>SSL Certificates]
        AI[AI Providers<br/>OpenAI/Anthropic/etc.]
    end
    
    INT --> CF
    CF --> LB
    LB --> TR
    INT -.-> TR
    DNS --> TR
    
    TR --> FE
    TR --> BE
    
    BE --> DB
    BE --> RD
    BE --> FS
    BE --> AI
    
    WK --> RD
    WK --> DB
    WK --> FS
    WK --> AI
    
    TR --> LE
    
    style TR fill:#e1f5fe
    style FE fill:#f3e5f5
    style BE fill:#e8f5e8
    style WK fill:#fff3e0
    style DB fill:#fce4ec
    style RD fill:#f1f8e9
```

</details>

---

## 📋 System Requirements

### Minimum Requirements
- **CPU**: 2 cores
- **RAM**: 4 GB
- **Storage**: 50 GB SSD
- **Network**: Outbound HTTPS for AI providers

### Recommended Requirements
- **CPU**: 4+ cores
- **RAM**: 8+ GB
- **Storage**: 100+ GB SSD
- **Network**: 1 Gbps connection

### Operating System Support
- **Ubuntu**: 20.04 LTS or higher
- **RHEL/CentOS**: 8 or higher
- **Debian**: 11 or higher
- **Container Runtime**: Docker 20.10+ or Podman 3.0+

---

## 🚀 Production Deployment in 5 Steps

This guide provides a streamlined, step-by-step process to get Eneo running in a production environment using Docker.

### Step 1: Prerequisites

Before you begin, ensure you have the following:

- **A Linux server** that meets the [minimum system requirements](#-system-requirements).
- **Docker and Docker Compose** installed. If not, run the following:
  ```bash
  # Install Docker and Docker Compose
  curl -fsSL https://get.docker.com -o get-docker.sh
  sh get-docker.sh
  ```
- **A registered domain name** (e.g., `eneo.my-organization.com`) with its DNS `A` record pointing to your server's IP address.
- **An API key** from at least one AI provider (e.g., OpenAI, Anthropic).

---

### Step 2: Download & Prepare

First, create a dedicated directory for the Eneo deployment files. Using `/opt/eneo` is a common convention for applications on Linux, but you can choose a different location if you prefer.

```bash
# Create and enter the deployment directory
sudo mkdir -p /opt/eneo/deployment
cd /opt/eneo/deployment

# Download the required configuration files
curl -O https://raw.githubusercontent.com/eneo-ai/eneo/main/docs/deployment/docker-compose.yml
curl -O https://raw.githubusercontent.com/eneo-ai/eneo/main/docs/deployment/env_backend.template
curl -O https://raw.githubusercontent.com/eneo-ai/eneo/main/docs/deployment/env_frontend.template
curl -O https://raw.githubusercontent.com/eneo-ai/eneo/main/docs/deployment/env_db.template

# Create the environment files from the templates
cp env_backend.template env_backend.env
cp env_frontend.template env_frontend.env
cp env_db.template env_db.env
```

---

### Step 3: Configuration

This is the most critical step. You will configure your Eneo instance by setting environment variables.

**A. Configure `docker-compose.yml`:**

Set your domain name and email address in the `docker-compose.yml` file. These are used by the Traefik reverse proxy to automatically issue a free SSL certificate from Let's Encrypt.

```bash
# Set your email (for SSL certificate notifications)
sed -i 's/your-email@domain.com/your-actual-email@example.com/g' docker-compose.yml

# Set your domain name (replace `your-domain.com` with your actual domain)
sed -i 's/your-domain.com/eneo.my-organization.com/g' docker-compose.yml
```
> **Note:** The domain `eneo.my-organization.com` is an example. Remember to use your own.

**B. Configure Secrets and Passwords:**

Generate unique secrets and a strong database password, then add them to the appropriate `.env` files.

```bash
# 1. Generate a secure database password
DB_PASSWORD=$(openssl rand -base64 32)
echo "POSTGRES_PASSWORD=$DB_PASSWORD" >> env_db.env

# 2. Generate a JWT secret for securing user sessions
JWT_SECRET=$(openssl rand -hex 32)
echo "JWT_SECRET=$JWT_SECRET" >> env_backend.env
echo "JWT_SECRET=$JWT_SECRET" >> env_frontend.env # Must be identical to the backend

# 3. Generate a URL signing key for the backend
URL_SIGNING_KEY=$(openssl rand -hex 32)
echo "URL_SIGNING_KEY=$URL_SIGNING_KEY" >> env_backend.env
```

**C. Configure Backend and Frontend URLs:**

Set the public URL for the frontend and backend in their respective `.env` files.

```bash
# Set the public URLs (use your actual domain)
echo "ORIGIN=https://eneo.my-organization.com" >> env_frontend.env
echo "INTRIC_BACKEND_URL=https://eneo.my-organization.com" >> env_frontend.env
```

**D. Add Your AI Provider API Key:**

Add your AI provider's API key to the `env_backend.env` file. You only need to add one.

```bash
# Example for OpenAI (replace with your actual key)
echo "OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" >> env_backend.env
```

<details>
<summary>🔍 Click to see final example environment files</summary>

**`env_db.env` should look like this:**
```
# Database Environment Configuration for Eneo

# IMPORTANT: Change the password for production!
POSTGRES_USER=postgres
POSTGRES_PASSWORD= # This will be populated by the command above
POSTGRES_DB=eneo
```

**`env_backend.env` should look like this:**
```
# Backend Environment Configuration for Eneo

###############
# REQUIRED: AI Model API Keys - Add at least ONE
###############
# OpenAI Configuration
OPENAI_API_KEY= # This will be populated by the command above

# ... (other AI provider keys)

###############
# REQUIRED: Security Settings - MUST BE CHANGED!
###############
# Generate with: openssl rand -hex 32
JWT_SECRET= # This will be populated by the command above
URL_SIGNING_KEY= # This will be populated by the command above

# ... (rest of the file)
```

**`env_frontend.env` should look like this:**
```
# Frontend Environment Configuration for Eneo

###############
# REQUIRED: Public URL Configuration
###############
# The public URL where Eneo will be accessible
ORIGIN= # This will be populated by the command above

# Backend URL as seen from the browser (public URL)
INTRIC_BACKEND_URL= # This will be populated by the command above

# ... (rest of the file)
```

</details>

---

### Step 4: Deploy Eneo

Now that configuration is complete, you can start the application.

```bash
# Create the external network for the reverse proxy
docker network create proxy_tier

# Start all services in the background
docker compose up -d
```
The initial startup may take a few minutes as Docker downloads the necessary images.

---

### Step 5: Verify & Secure Your Installation

**A. Check Container Status:**

Ensure all services are running correctly.

```bash
docker compose ps
```
You should see `eneo_frontend`, `eneo_backend`, `eneo_worker`, `eneo_db`, and `eneo_traefik` with the status `running`.

**B. Access Your Eneo Instance:**

Open your web browser and navigate to the domain you configured (e.g., `https://eneo.my-organization.com`). You should see the Eneo login page.

**C. Change the Default Password (CRITICAL):**

This is the most important post-deployment step.

1.  Log in with the default credentials:
    - **Email:** `user@example.com`
    - **Password:** `Password1!`
2.  Navigate to the user menu in the top-right corner and change your password immediately.

**Congratulations! Your Eneo instance is now deployed and secured.**


---

## ⚙️ Environment Configuration

### Minimal Configuration Example

Here's a minimal working configuration. For all available options, see the template files.

**Backend (`env_backend.env`):**
```bash
# Required: Add at least one AI provider
OPENAI_API_KEY=sk-proj-your-actual-key

# Required: Security (generate with: openssl rand -hex 32)
JWT_SECRET=your-generated-64-character-hex-secret
URL_SIGNING_KEY=your-generated-64-character-hex-secret

# Database (defaults for Docker Compose)
POSTGRES_HOST=db
POSTGRES_PASSWORD=your-secure-password

# Everything else uses secure defaults from the template
```

**Frontend (`env_frontend.env`):**
```bash
# Required: Your domain
ORIGIN=https://your-domain.com
INTRIC_BACKEND_URL=https://your-domain.com

# Required: Must match backend JWT_SECRET exactly
JWT_SECRET=your-generated-64-character-hex-secret

# Defaults are fine for everything else
```

**Database (`env_db.env`):**
```bash
POSTGRES_PASSWORD=your-secure-password
# Other values use secure defaults
```

---

## 🔒 Security Configuration

### SSL Certificates

Traefik automatically manages SSL certificates via Let's Encrypt:

1. **Automatic Renewal**: Certificates auto-renew before expiration
2. **Multiple Domains**: Support for multiple domains and subdomains
3. **Security Headers**: HSTS and security headers automatically added

### Firewall Configuration

```bash
# Ubuntu/Debian with ufw
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP (redirects to HTTPS)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable

# RHEL/CentOS with firewalld
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

### Docker Security

```bash
# Create non-root user for Docker
sudo groupadd docker
sudo usermod -aG docker $USER

# Secure Docker daemon
sudo systemctl enable docker
sudo systemctl start docker

# Regular security updates
sudo apt update && sudo apt upgrade -y  # Ubuntu/Debian
sudo dnf update -y                      # RHEL/CentOS
```

---

## 📊 Monitoring and Maintenance

### Health Checks

```bash
# Check service status
docker compose ps

# View logs
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f worker

# Resource usage
docker stats

# Database health
docker compose exec db pg_isready -U postgres
```

### Backup Strategy

<details>
<summary>💾 Database Backup</summary>

```bash
# Create backup script
cat > /opt/eneo/backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/eneo/backups"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR

# Database backup
docker compose exec -T db pg_dump -U postgres eneo > $BACKUP_DIR/eneo_db_$DATE.sql

# Backend data backup
docker run --rm -v eneo_eneo_backend_data:/data -v $BACKUP_DIR:/backup alpine tar czf /backup/eneo_data_$DATE.tar.gz -C /data .

# Keep only last 30 days
find $BACKUP_DIR -name "*.sql" -mtime +30 -delete
find $BACKUP_DIR -name "*.tar.gz" -mtime +30 -delete

echo "Backup completed: $DATE"
EOF

chmod +x /opt/eneo/backup.sh

# Add to crontab for daily backups
(crontab -l ; echo "0 2 * * * /opt/eneo/backup.sh") | crontab -
```

</details>

### Updates and Maintenance

```bash
# Update containers
docker compose pull
docker compose up -d

# Clean up old images
docker system prune -f

# Database maintenance
docker compose exec db vacuumdb -U postgres -d eneo --analyze

# Check disk usage
df -h
docker system df
```

---

## 🏢 Enterprise Deployment

### RHEL/CentOS with Podman

<details>
<summary>🔴 RHEL Enterprise Setup</summary>

```bash
# Install Podman and dependencies
sudo dnf install -y podman podman-compose podman-docker
sudo systemctl enable podman.socket

# Configure SELinux (if enabled)
sudo setsebool -P container_manage_cgroup on
sudo setsebool -P container_use_cgroup_namespace on

# Setup Eneo
sudo mkdir -p /opt/eneo
cd /opt/eneo
# ... copy configuration files ...

# Use podman-compose instead of docker-compose
podman-compose up -d

# Create systemd service
sudo cat > /etc/systemd/system/eneo.service << 'EOF'
[Unit]
Description=Eneo AI Platform
After=network.target

[Service]
Type=oneshot
RemainAfterExit=true
WorkingDirectory=/opt/eneo/deployment
ExecStart=/usr/bin/podman-compose up -d
ExecStop=/usr/bin/podman-compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable eneo
sudo systemctl start eneo
```

</details>

### Kubernetes Deployment

<details>
<summary>☸️ Kubernetes Configuration</summary>

```yaml
# namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: eneo

---
# configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: eneo-config
  namespace: eneo
data:
  POSTGRES_HOST: "eneo-postgresql"
  REDIS_HOST: "eneo-redis"
  # ... other non-secret config

---
# secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: eneo-secrets
  namespace: eneo
type: Opaque
stringData:
  JWT_SECRET: "your-jwt-secret"
  POSTGRES_PASSWORD: "your-db-password"
  OPENAI_API_KEY: "your-openai-key"
  # ... other secrets

---
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: eneo-backend
  namespace: eneo
spec:
  replicas: 2
  selector:
    matchLabels:
      app: eneo-backend
  template:
    metadata:
      labels:
        app: eneo-backend
    spec:
      containers:
      - name: backend
        image: ghcr.io/eneo-ai/eneo-backend:latest
        ports:
        - containerPort: 8000
        envFrom:
        - configMapRef:
            name: eneo-config
        - secretRef:
            name: eneo-secrets
        volumeMounts:
        - name: data
          mountPath: /app/data
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: eneo-backend-pvc

# ... additional resources for frontend, worker, database, etc.
```

</details>

---

## 🔧 Troubleshooting

### Common Issues

<details>
<summary>🚨 SSL Certificate Issues</summary>

**Problem**: SSL certificate not working

**Solutions**:
```bash
# Check Traefik logs
docker compose logs traefik

# Verify domain DNS
nslookup your-domain.com

# Check Let's Encrypt rate limits
# Wait if rate limited, or use staging environment

# Force certificate renewal
docker compose restart traefik
```

</details>

<details>
<summary>🐳 Container Issues</summary>

**Problem**: Containers not starting

**Solutions**:
```bash
# Check container logs
docker compose logs

# Check resource usage
docker stats
df -h

# Restart services
docker compose restart
docker compose up -d --force-recreate
```

</details>

<details>
<summary>🗄️ Database Issues</summary>

**Problem**: Database connection errors

**Solutions**:
```bash
# Check database container
docker compose logs db

# Test database connection
docker compose exec db pg_isready -U postgres

# Check database initialization
docker compose logs db-init

# Manual database init
docker compose exec backend python init_db.py
```

</details>

---

## 📚 Production Checklist

### Pre-deployment
- [ ] Domain name configured and DNS pointing to server
- [ ] SSL email configured for Let's Encrypt
- [ ] All environment variables configured
- [ ] AI provider API keys tested
- [ ] Secure passwords generated for database and JWT
- [ ] Firewall configured
- [ ] Backup strategy implemented

### Post-deployment
- [ ] All services running (`docker compose ps`)
- [ ] HTTPS working with valid certificate
- [ ] Default user password changed
- [ ] Admin user created
- [ ] First AI assistant tested
- [ ] Monitoring configured
- [ ] Backup tested and verified

### Ongoing Maintenance
- [ ] Regular container updates
- [ ] Database backups verified
- [ ] Security updates applied
- [ ] Log monitoring configured
- [ ] Performance monitoring setup

---

## 📞 Support

**Production Issues:**
- 🔍 Check [Troubleshooting Guide](TROUBLESHOOTING.md)
- 🐛 [Report Issues](https://github.com/eneo-ai/eneo/issues)
- 📧 [Enterprise Support](mailto:digitalisering@sundsvall.se)

**Community Support:**
- 💬 [GitHub Discussions](https://github.com/eneo-ai/eneo/discussions)
- 📖 [Documentation](README.md)
- 🤝 [Contributing Guide](CONTRIBUTING.md)