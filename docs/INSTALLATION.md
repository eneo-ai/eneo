# Installation Guide

This guide covers setting up Eneo for development and testing. For production deployment, see the [Deployment Guide](DEPLOYMENT.md).

> 📌 **Port Usage**: Development runs on port **8123**, while production uses port **8000**. This guide uses development ports.

---

## 🎯 Quick Overview

**Development Options:**
- **🐳 DevContainer** (Recommended) - Pre-configured VS Code environment
- **💻 Local Setup** - Manual installation with full control
- **🔧 Docker Compose** - Containerized development environment

**Prerequisites:**
- Docker and Docker Compose
- At least one AI provider API key

---

## 🐳 DevContainer Setup (Recommended)

### Prerequisites
1. **Docker Desktop** - [Download here](https://www.docker.com/products/docker-desktop/)
2. **VS Code** - [Download here](https://code.visualstudio.com/)
3. **Dev Containers Extension** - Install from VS Code marketplace

### Setup Steps

1. **Clone Repository**
   ```bash
   git clone https://github.com/eneo-ai/eneo.git
   cd eneo
   ```

2. **Open in VS Code**
   ```bash
   code .
   ```

3. **Reopen in Container**
   - VS Code will show: "Folder contains a Dev Container configuration"
   - Click **"Reopen in Container"**
   - Wait 2-3 minutes for container setup (first time only)

4. **Configure Environment**
   ```bash
   # In VS Code terminal
   cp backend/env_template backend/.env
   cp frontend/apps/web/.env.example frontend/apps/web/.env
   
   # Edit .env files with your configuration
   # Minimum: Add at least one AI provider API key
   ```

5. **Initialize Database**
   ```bash
   cd backend
   poetry run python init_db.py
   ```

6. **Start Services**
   
   Open 3 terminals in VS Code:
   
   **Terminal 1 - Backend:**
   ```bash
   cd backend
   poetry run start
   ```
   
   **Terminal 2 - Frontend:**
   ```bash
   cd frontend
   pnpm run dev
   ```
   
   **Terminal 3 - Worker (Optional):**
   ```bash
   cd backend
   poetry run arq src.intric.worker.arq.WorkerSettings
   ```

7. **Access Application**
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8123/docs (development)
   - Default login: `user@example.com` / `Password1!`

> **Port Note**: Development uses port 8123, but production deployment uses port 8000.

---

## 💻 Local Development Setup

### System Requirements

- **Python**: 3.11 or higher
- **Node.js**: 18 or higher
- **pnpm**: 9.12.3 or higher
- **Docker**: For PostgreSQL and Redis
- **System Libraries**: `libmagic1`, `ffmpeg`

### Installation Steps

<details>
<summary>📋 Click to expand detailed local setup</summary>

#### 1. Install System Dependencies

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y libmagic1 ffmpeg python3.11 python3.11-pip nodejs npm
```

**macOS:**
```bash
brew install libmagic ffmpeg python@3.11 node
```

#### 2. Install Package Managers

```bash
# Install Poetry for Python
curl -sSL https://install.python-poetry.org | python3 -

# Install pnpm for Node.js
npm install -g pnpm@9.12.3
```

#### 3. Clone and Setup

```bash
git clone https://github.com/eneo-ai/eneo.git
cd eneo
```

#### 4. Backend Setup

```bash
cd backend

# Install dependencies
poetry install

# Copy and configure environment
cp env_template .env
# Edit .env with your settings (see env_template for all options)

# Start infrastructure services
docker compose up -d

# Initialize database
poetry run python init_db.py

# Start backend server
poetry run start
```

#### 5. Frontend Setup

```bash
cd frontend

# Install dependencies
pnpm install

# Setup shared packages
pnpm run setup

# Copy and configure environment
cp apps/web/.env.example apps/web/.env
# Edit .env with your settings

# Start frontend server
pnpm run dev
```

#### 6. Worker Setup (Optional)

```bash
cd backend
poetry run arq src.intric.worker.arq.WorkerSettings
```

</details>

---

## ⚙️ Environment Configuration

### Minimal Development Configuration

The template files contain all options. Here's the minimum needed to start:

#### Backend (`backend/.env`):
```bash
# Add at least one AI provider
OPENAI_API_KEY=sk-proj-your-key-here

# For development, defaults from env_template work for everything else
# See backend/env_template for all available options
```

#### Frontend (`frontend/apps/web/.env`):
```bash
# Already configured for development in .env.example
# Just copy it as-is: cp .env.example .env
```

### AI Provider Setup

Configure at least one AI provider:

<details>
<summary>🤖 OpenAI Configuration</summary>

```bash
# Required
OPENAI_API_KEY=sk-proj-...

# Optional - customize endpoints
OPENAI_BASE_URL=https://api.openai.com/v1
```

</details>

<details>
<summary>🧠 Anthropic Configuration</summary>

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional - customize endpoints
ANTHROPIC_BASE_URL=https://api.anthropic.com
```

</details>

<details>
<summary>☁️ Azure OpenAI Configuration</summary>

```bash
# Required
AZURE_API_KEY=your-azure-key
AZURE_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_API_VERSION=2024-02-15-preview
AZURE_MODEL_DEPLOYMENT=gpt-4

# Enable Azure models
USING_AZURE_MODELS=True
```

</details>

---

## 🔧 Development Commands

### Backend Commands

```bash
cd backend

# Development
poetry run start                    # Start API server
poetry run python init_db.py       # Initialize database
poetry run alembic upgrade head    # Apply migrations
poetry run arq src.intric.worker.arq.WorkerSettings  # Start worker

# Testing
poetry run pytest                  # Run all tests
poetry run pytest -v tests/        # Verbose test output
poetry run pytest --cov           # Test coverage report

# Database
poetry run alembic revision --autogenerate -m "description"  # Create migration
poetry run alembic downgrade -1    # Rollback last migration
```

### Frontend Commands

```bash
cd frontend

# Development
pnpm run dev                       # Start dev server
pnpm run setup                     # Build shared packages
pnpm install                       # Install dependencies

# Testing
pnpm run test                      # Run tests
pnpm run test:unit                 # Unit tests only
pnpm run lint                      # Lint code
pnpm run check                     # Type checking

# Building
pnpm run build                     # Build for production
pnpm run preview                   # Preview production build
```

### Infrastructure Commands

```bash
# Docker services
docker compose up -d               # Start PostgreSQL & Redis
docker compose down                # Stop services
docker compose logs <service>      # View service logs
docker compose ps                  # List running containers

# Database operations
docker compose exec db psql -U postgres  # Connect to database
docker compose restart db          # Restart database
```

---

## 🔍 Verification

### Check Installation

1. **Backend Health Check**
   ```bash
   curl http://localhost:8123/version
   ```

2. **Frontend Access**
   - Navigate to http://localhost:3000
   - Should show Eneo login page

3. **Database Connection**
   ```bash
   cd backend
   poetry run python -c "from src.intric.database.database import get_db; next(get_db())"
   ```

4. **AI Provider Test**
   - Log into frontend
   - Create a test assistant
   - Send a test message

### Default Credentials

- **Email**: `user@example.com`
- **Password**: `Password1!`

> 🔐 **Security Note**: Change default password after first login

---

## 🛠️ Troubleshooting

### Common Issues

<details>
<summary>🐍 Python/Poetry Issues</summary>

**Poetry not found:**
```bash
# Add Poetry to PATH
export PATH="$HOME/.local/bin:$PATH"
```

**Python version issues:**
```bash
# Check Python version
python3 --version
poetry env use python3.11
```

</details>

<details>
<summary>📦 Node.js/pnpm Issues</summary>

**pnpm not found:**
```bash
npm install -g pnpm@9.12.3
```

**Node version issues:**
```bash
# Check Node version
node --version
# Should be 18 or higher
```

</details>

<details>
<summary>🐳 Docker Issues</summary>

**Docker not running:**
```bash
# Check Docker status
docker --version
docker compose version

# Start Docker Desktop (GUI)
# Or on Linux:
sudo systemctl start docker
```

**Port conflicts:**
```bash
# Check port usage
lsof -i :3000  # Frontend
lsof -i :8000  # Backend
lsof -i :5432  # PostgreSQL
lsof -i :6379  # Redis
```

</details>

<details>
<summary>🔑 Authentication Issues</summary>

**JWT Secret mismatch:**
- Ensure `JWT_SECRET` is identical in backend and frontend `.env` files

**Database connection:**
```bash
# Test database connection
cd backend
poetry run python init_db.py
```

</details>

<details>
<summary>🤖 AI Provider Issues</summary>

**API key validation:**
```bash
# Test OpenAI key
curl -H "Authorization: Bearer $OPENAI_API_KEY" https://api.openai.com/v1/models

# Test Anthropic key
curl -H "x-api-key: $ANTHROPIC_API_KEY" https://api.anthropic.com/v1/messages
```

</details>

---

## 🔗 Next Steps

Once development environment is running:

1. **Read Architecture Guide** - Understanding system design
2. **Explore API Documentation** - Visit http://localhost:8000/docs
3. **Create First Assistant** - Build a simple chatbot
4. **Review Contributing Guide** - Learn development workflow
5. **Set up Production** - Follow [Deployment Guide](DEPLOYMENT.md)

---

## 📚 Additional Resources

- **[Architecture Documentation](ARCHITECTURE.md)** - System design details
- **[Contributing Guidelines](CONTRIBUTING.md)** - Development standards
- **[Troubleshooting Guide](TROUBLESHOOTING.md)** - Common problems and solutions
- **[API Documentation](http://localhost:8000/docs)** - Interactive API explorer

---

**Need Help?** 

- 🐛 [Report Issues](https://github.com/eneo-ai/eneo/issues)
- 💬 [Community Discussions](https://github.com/eneo-ai/eneo/discussions)
- 📧 [Contact Team](mailto:digitalisering@sundsvall.se)