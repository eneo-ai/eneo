# Troubleshooting Guide

This guide covers common issues encountered when setting up, deploying, or using Eneo, along with their solutions.

---

## 🔍 Quick Diagnosis

### System Health Checks

Run these commands to quickly assess system status:

```bash
# Check all services
docker compose ps

# Check service logs
docker compose logs --tail=50

# Check system resources
docker stats --no-stream
df -h

# Test network connectivity
curl -I http://localhost:3000  # Frontend
curl -I http://localhost:8123/version  # Backend (development)
```

#### Health Check Endpoints

Eneo provides dedicated health check endpoints for monitoring:

```bash
# Backend API health (includes worker status)
curl http://localhost:8123/api/healthz

# Frontend web health
curl http://localhost:3000/web/healthz

# Check HTTP status codes
curl -w "%{http_code}" -s -o /dev/null http://localhost:8123/api/healthz
```

**Backend Health Response**:

*Healthy System (HTTP 200)*:
```json
{
  "status": "OK",
  "timestamp": "2025-01-20T10:30:45.123456+00:00",
  "backend": {
    "status": "healthy",
    "last_heartbeat": "2025-01-20T10:30:45.123456+00:00",
    "details": "Backend API server operational"
  },
  "worker": {
    "status": "healthy",
    "last_heartbeat": "2025-01-20T10:30:45.123456+00:00",
    "details": "Worker statistics and status"
  }
}
```

*Unhealthy System (HTTP 500)*:
```json
{
  "status": "UNHEALTHY",
  "timestamp": "2025-01-20T10:30:45.123456+00:00",
  "backend": {
    "status": "healthy",
    "last_heartbeat": "2025-01-20T10:30:45.123456+00:00",
    "details": "Backend API server operational"
  },
  "worker": {
    "status": "unhealthy",
    "last_heartbeat": null,
    "details": "Worker health check key not found or expired"
  }
}
```

**Frontend Health Response**:
```json
{
  "status": "OK",
  "timestamp": "2025-01-20T10:30:45.123456+00:00",
  "service": "frontend-web"
}
```

**HTTP Status Codes**:
- `200 OK`: All system components healthy and operational
- `500 Internal Server Error`: Critical system components down (worker, Redis)

**Worker Status Meanings**:
- `healthy`: ARQ worker is running and processing jobs
- `unhealthy`: Worker health check key expired (worker down)
- `unknown`: Redis connection error or worker status unclear

---

## 🚀 Installation & Setup Issues

### DevContainer Problems

<details>
<summary>🐳 "Reopen in Container" option not appearing</summary>

**Problem**: VS Code doesn't show the container prompt.

**Solutions**:
1. **Install Dev Containers extension**:
   - Open VS Code Extensions (Ctrl+Shift+X)
   - Search for "Dev Containers" by Microsoft
   - Install the extension

2. **Manual container opening**:
   ```bash
   # In VS Code, press Ctrl+Shift+P
   # Type: "Dev Containers: Reopen in Container"
   # Select the option
   ```

3. **Check .devcontainer configuration**:
   ```bash
   # Verify .devcontainer/devcontainer.json exists
   ls -la .devcontainer/
   ```

**Prevention**: Always install Dev Containers extension before opening the project.

</details>

<details>
<summary>🐳 Container build fails or takes too long</summary>

**Problem**: DevContainer fails to build or takes excessive time.

**Solutions**:
1. **Increase Docker resources**:
   - Open Docker Desktop
   - Go to Settings → Resources
   - Increase Memory to 4GB+ and CPU to 2+ cores
   - Apply & Restart

2. **Clear Docker cache**:
   ```bash
   docker system prune -a
   docker builder prune -a
   ```

3. **Rebuild container**:
   ```bash
   # In VS Code: Ctrl+Shift+P
   # Type: "Dev Containers: Rebuild Container"
   ```

4. **Check Docker Desktop status**:
   - Ensure Docker Desktop is running
   - Check for Docker updates

**Prevention**: Allocate sufficient Docker resources before starting.

</details>

<details>
<summary>🐍 Python/Poetry dependency issues</summary>

**Problem**: Poetry installation fails or dependencies conflict.

**Solutions**:
1. **Clear Poetry cache**:
   ```bash
   poetry cache clear pypi --all
   poetry env remove --all
   poetry install
   ```

2. **Update Poetry**:
   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   ```

3. **Python version mismatch**:
   ```bash
   # Check Python version
   python3 --version  # Should be 3.11+
   
   # Set specific Python version
   poetry env use python3.11
   poetry install
   ```

4. **Lock file issues**:
   ```bash
   # Delete lock file and reinstall
   rm poetry.lock
   poetry install
   ```

**Prevention**: Use the provided DevContainer for consistent environment.

</details>

<details>
<summary>📦 Node.js/pnpm dependency issues</summary>

**Problem**: pnpm installation fails or packages conflict.

**Solutions**:
1. **Update pnpm**:
   ```bash
   npm install -g pnpm@9.12.3
   ```

2. **Clear pnpm cache**:
   ```bash
   pnpm store prune
   rm -rf node_modules
   rm pnpm-lock.yaml
   pnpm install
   ```

3. **Node version issues**:
   ```bash
   # Check Node version
   node --version  # Should be 18+
   
   # Use nvm to switch versions (if available)
   nvm use 18
   ```

4. **Workspace issues**:
   ```bash
   # Reinstall all workspace dependencies
   pnpm install -r
   ```

**Prevention**: Use specified Node.js and pnpm versions.

</details>

---

## 🗄️ Database Issues

### Connection Problems

<details>
<summary>🔌 Database connection refused</summary>

**Problem**: Backend cannot connect to PostgreSQL.

**Solutions**:
1. **Check PostgreSQL container**:
   ```bash
   docker compose ps db
   docker compose logs db
   ```

2. **Restart database**:
   ```bash
   docker compose restart db
   ```

3. **Check database initialization**:
   ```bash
   docker compose logs db-init
   ```

4. **Manual database initialization**:
   ```bash
   cd backend
   uv run python init_db.py
   ```

5. **Verify environment variables**:
   ```bash
   # Check .env file
   grep POSTGRES backend/.env
   ```

**Common causes**:
- PostgreSQL container not running
- Incorrect database credentials
- Database not initialized
- Port conflicts (5432 already in use)

</details>

<details>
<summary>🔒 Authentication failed for user</summary>

**Problem**: Database authentication errors.

**Solutions**:
1. **Reset database**:
   ```bash
   docker compose down -v
   docker compose up -d db
   cd backend
   uv run python init_db.py
   ```

2. **Check password in environment**:
   ```bash
   # Verify POSTGRES_PASSWORD matches in all env files
   grep POSTGRES_PASSWORD backend/.env
   ```

3. **Manual password reset**:
   ```bash
   docker compose exec db psql -U postgres -c "ALTER USER postgres PASSWORD 'newpassword';"
   ```

**Prevention**: Ensure consistent database passwords across all configuration files.

</details>

<details>
<summary>📊 pgvector extension issues</summary>

**Problem**: Vector operations fail or extension not found.

**Solutions**:
1. **Verify pgvector installation**:
   ```bash
   docker compose exec db psql -U postgres -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
   ```

2. **Install pgvector manually**:
   ```bash
   docker compose exec db psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```

3. **Use correct base image**:
   ```yaml
   # In docker-compose.yml
   db:
     image: pgvector/pgvector:pg16  # Ensure this image is used
   ```

4. **Recreate database with extension**:
   ```bash
   docker compose down -v
   docker compose up -d
   ```

**Prevention**: Always use the pgvector/pgvector Docker image.

</details>

---

## 🔑 Authentication & Authorization Issues

### JWT Token Problems

<details>
<summary>🔐 JWT token invalid or expired</summary>

**Problem**: Authentication fails with token errors.

**Solutions**:
1. **Check JWT_SECRET matching**:
   ```bash
   # Ensure JWT_SECRET is identical in backend and frontend
   grep JWT_SECRET backend/.env
   grep JWT_SECRET frontend/apps/web/.env
   ```

2. **Generate new JWT secret**:
   ```bash
   # Generate secure secret
   openssl rand -hex 32
   
   # Update both backend and frontend .env files
   JWT_SECRET=your-new-secret
   ```

3. **Clear browser storage**:
   - Open browser developer tools (F12)
   - Go to Application → Storage
   - Clear localStorage and sessionStorage
   - Refresh page

4. **Restart services**:
   ```bash
   docker compose restart frontend backend
   ```

**Prevention**: Always use the same JWT_SECRET in both backend and frontend.

</details>

<details>
<summary>👤 Default user login fails</summary>

**Problem**: Cannot login with default credentials.

**Solutions**:
1. **Verify default user creation**:
   ```bash
   cd backend
   uv run python init_db.py  # This creates default user
   ```

2. **Check default credentials**:
   - Email: `user@example.com`
   - Password: `Password1!`

3. **Reset default user**:
   ```bash
   docker compose exec db psql -U postgres -d eneo -c "DELETE FROM users WHERE email = 'user@example.com';"
   cd backend
   uv run python init_db.py
   ```

4. **Create user manually**:
   ```bash
   # Access database
   docker compose exec db psql -U postgres -d eneo
   
   # Check users table
   SELECT email, username FROM users;
   ```

**Prevention**: Always run `init_db.py` after database setup.

</details>

---

## 🤖 AI Provider Issues

### API Key Problems

<details>
<summary>🔑 AI provider authentication failures</summary>

**Problem**: AI providers return authentication errors.

**Solutions**:
1. **Verify API keys**:
   ```bash
   # Test OpenAI key
   curl -H "Authorization: Bearer $OPENAI_API_KEY" \
        https://api.openai.com/v1/models
   
   # Test Anthropic key
   curl -H "x-api-key: $ANTHROPIC_API_KEY" \
        https://api.anthropic.com/v1/messages \
        -H "Content-Type: application/json" \
        -d '{
          "model": "claude-3-haiku-20240307",
          "max_tokens": 10,
          "messages": [{"role": "user", "content": "Hi"}]
        }'
   ```

2. **Check API key format**:
   - OpenAI: `sk-proj-...` (starts with sk-proj-)
   - Anthropic: `sk-ant-...` (starts with sk-ant-)
   - Azure: Custom format from Azure portal

3. **Verify API quotas**:
   - Check provider dashboard for usage limits
   - Ensure billing is set up correctly
   - Verify rate limits aren't exceeded

4. **Update environment variables**:
   ```bash
   # Edit backend/.env
   OPENAI_API_KEY=sk-proj-your-actual-key
   ANTHROPIC_API_KEY=sk-ant-your-actual-key
   
   # Restart backend
   docker compose restart backend
   ```

**Prevention**: Test API keys independently before configuring Eneo.

</details>

<details>
<summary>⚡ AI responses are slow or timing out</summary>

**Problem**: AI completions take too long or fail.

**Solutions**:
1. **Check provider status**:
   - Visit provider status pages
   - Verify your region/endpoint availability

2. **Optimize request parameters**:
   ```python
   # Reduce max_tokens for faster responses
   # Use faster models (e.g., GPT-3.5 instead of GPT-4)
   # Implement request timeouts
   ```

3. **Implement retries**:
   ```bash
   # Check worker logs for retry attempts
   docker compose logs worker
   ```

4. **Switch providers**:
   ```bash
   # Configure multiple providers for fallback
   # Edit assistant to use different model
   ```

**Prevention**: Configure multiple AI providers for redundancy.

</details>

---

## 🌐 Network & Connectivity Issues

### Port Conflicts

<details>
<summary>🔌 Ports already in use</summary>

**Problem**: Cannot start services due to port conflicts.

**Solutions**:
1. **Check port usage**:
   ```bash
   # Check what's using the ports
   lsof -i :3000  # Frontend
   lsof -i :8123  # Backend (development)
   lsof -i :8000  # Backend (production)
   lsof -i :5432  # PostgreSQL
   lsof -i :6379  # Redis
   ```

2. **Stop conflicting services**:
   ```bash
   # Stop specific service
   sudo kill -9 $(lsof -t -i:3000)
   
   # Or stop by service name
   sudo systemctl stop postgresql  # If system PostgreSQL is running
   ```

3. **Change ports in configuration**:
   ```yaml
   # docker-compose.yml - change port mapping
   frontend:
     ports:
       - "3001:3000"  # Use 3001 instead of 3000
   ```

4. **Use different ports**:
   ```bash
   # Frontend development
   cd frontend
   PORT=3001 pnpm run dev
   ```

**Prevention**: Check for running services before starting Eneo.

</details>

<details>
<summary>🌐 Frontend cannot connect to backend</summary>

**Problem**: Frontend shows connection errors to backend API.

**Solutions**:
1. **Check backend URL configuration**:
   ```bash
   # In frontend/.env
   INTRIC_BACKEND_URL=http://localhost:8000
   INTRIC_BACKEND_SERVER_URL=http://localhost:8000
   ```

2. **Verify backend is running**:
   ```bash
   curl http://localhost:8123/version  # Development
   curl http://localhost:8000/version  # Production
   ```

3. **Check CORS settings**:
   ```bash
   # Backend logs should show CORS errors if relevant
   docker compose logs backend | grep -i cors
   ```

4. **Network connectivity**:
   ```bash
   # Test from frontend container
   docker compose exec frontend curl http://backend:8000/version
   ```

**Prevention**: Use correct URLs in environment configuration.

</details>

---

## 🚀 Production Deployment Issues

### SSL Certificate Problems

<details>
<summary>🔒 Let's Encrypt certificate acquisition fails</summary>

**Problem**: Traefik cannot obtain SSL certificates.

**Solutions**:
1. **Check domain DNS**:
   ```bash
   nslookup your-domain.com
   dig your-domain.com
   ```

2. **Verify Traefik configuration**:
   ```bash
   docker compose logs traefik
   ```

3. **Check Let's Encrypt rate limits**:
   - Verify you haven't exceeded rate limits
   - Use staging environment first:
   ```yaml
   # In Traefik command
   - "--certificatesresolvers.letsencrypt.acme.caserver=https://acme-staging-v02.api.letsencrypt.org/directory"
   ```

4. **Manual certificate check**:
   ```bash
   # Check certificate status
   docker compose exec traefik cat /letsencrypt/acme.json
   ```

**Prevention**: Test with staging environment before production deployment.

</details>

<details>
<summary>🏗️ Container deployment failures</summary>

**Problem**: Production containers fail to start or crash.

**Solutions**:
1. **Check resource limits**:
   ```bash
   # Monitor resource usage
   docker stats
   free -h
   df -h
   ```

2. **Review container logs**:
   ```bash
   docker compose logs --tail=100 backend
   docker compose logs --tail=100 frontend
   ```

3. **Verify environment configuration**:
   ```bash
   # Check all required environment variables are set
   docker compose config
   ```

4. **Database initialization**:
   ```bash
   # Ensure database is properly initialized
   docker compose logs db-init
   ```

**Prevention**: Test full deployment process in staging environment.

</details>

---

## 📁 File Processing Issues

### Upload Problems

<details>
<summary>📄 File uploads fail or timeout</summary>

**Problem**: Document uploads don't work or are very slow.

**Solutions**:
1. **Check file size limits**:
   ```bash
   # Verify upload limits in backend/.env
   UPLOAD_MAX_FILE_SIZE=10485760  # 10MB in bytes
   ```

2. **Verify worker is running**:
   ```bash
   docker compose ps worker
   docker compose logs worker
   ```

3. **Check file processing logs**:
   ```bash
   # Look for processing errors
   docker compose logs worker | grep -i error
   ```

4. **Test with smaller files**:
   ```bash
   # Try uploading a small text file first
   ```

5. **Check disk space**:
   ```bash
   df -h
   docker system df
   ```

**Prevention**: Monitor disk space and ensure worker service is running.

</details>

<details>
<summary>🔍 Vector search not working</summary>

**Problem**: Semantic search returns no results or errors.

**Solutions**:
1. **Verify pgvector installation**:
   ```bash
   docker compose exec db psql -U postgres -d eneo -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
   ```

2. **Check embedding generation**:
   ```bash
   # Look for embedding generation in worker logs
   docker compose logs worker | grep -i embedding
   ```

3. **Verify embedding model configuration**:
   ```bash
   # Check if embedding models are configured
   docker compose exec db psql -U postgres -d eneo -c "SELECT * FROM embedding_models;"
   ```

4. **Test embeddings manually**:
   ```python
   # In backend container
   cd backend
   uv run python -c "
   from src.intric.embedding_models.infrastructure.create_embeddings_service import create_embeddings
   print('Testing embeddings...')
   "
   ```

**Prevention**: Ensure pgvector extension and embedding models are properly configured.

</details>

---

## 🔧 Performance Issues

### Slow Response Times

<details>
<summary>⏱️ Application responds slowly</summary>

**Problem**: Eneo feels sluggish or unresponsive.

**Solutions**:
1. **Check system resources**:
   ```bash
   docker stats
   top
   htop  # If available
   ```

2. **Database performance**:
   ```bash
   # Check database connections
   docker compose exec db psql -U postgres -d eneo -c "SELECT count(*) FROM pg_stat_activity;"
   
   # Check slow queries
   docker compose exec db psql -U postgres -d eneo -c "SELECT query, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;"
   ```

3. **Redis performance**:
   ```bash
   docker compose exec redis redis-cli info memory
   docker compose exec redis redis-cli info stats
   ```

4. **Backend bottlenecks**:
   ```bash
   # Check backend logs for slow requests
   docker compose logs backend | grep -E "(WARNING|ERROR|took|slow)"
   ```

5. **Frontend optimization**:
   ```bash
   # Check network tab in browser dev tools
   # Look for large bundle sizes or slow API calls
   ```

**Performance tuning**:
```bash
# Increase worker processes
# Add database connection pooling
# Implement caching strategies
# Optimize database queries
```

</details>

<details>
<summary>💾 Memory usage too high</summary>

**Problem**: Containers consume excessive memory.

**Solutions**:
1. **Identify memory-heavy containers**:
   ```bash
   docker stats --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"
   ```

2. **Optimize backend memory**:
   ```bash
   # Reduce worker processes
   # Implement pagination for large datasets
   # Clear unused variables in Python
   ```

3. **Database optimization**:
   ```bash
   # Adjust PostgreSQL memory settings
   docker compose exec db psql -U postgres -c "SHOW shared_buffers;"
   ```

4. **Set container limits**:
   ```yaml
   # In docker-compose.yml
   backend:
     deploy:
       resources:
         limits:
           memory: 512M
   ```

**Prevention**: Monitor memory usage and set appropriate container limits.

</details>

---

## 🛠️ Development Issues

### Hot Reload Problems

<details>
<summary>🔄 Frontend hot reload not working</summary>

**Problem**: Changes to frontend code don't trigger reloads.

**Solutions**:
1. **Check file watching**:
   ```bash
   # Increase file watch limits on Linux
   echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
   sudo sysctl -p
   ```

2. **Verify development server**:
   ```bash
   cd frontend
   pnpm run dev --host 0.0.0.0 --port 3000
   ```

3. **Check file permissions**:
   ```bash
   # Ensure files are writable
   ls -la src/
   ```

4. **WSL-specific issues**:
   ```bash
   # Move project to WSL filesystem
   cp -r /mnt/c/project ~/project
   cd ~/project
   ```

**Prevention**: Use native filesystem paths in WSL environments.

</details>

<details>
<summary>🐍 Backend auto-reload not working</summary>

**Problem**: Backend changes require manual restart.

**Solutions**:
1. **Verify development mode**:
   ```bash
   cd backend
   uv run uvicorn src.intric.server.main:app --reload --host 0.0.0.0 --port 8000
   ```

2. **Check file watching**:
   ```python
   # In main.py, ensure reload=True in development
   if __name__ == "__main__":
       uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
   ```

3. **File permissions**:
   ```bash
   # Ensure Python files are readable
   find src/ -name "*.py" -exec chmod 644 {} \;
   ```

**Prevention**: Use development-specific startup commands.

</details>

---

## 🔍 Debugging Tools

### Useful Commands

**Container debugging**:
```bash
# Access container shell
docker compose exec backend bash
docker compose exec frontend sh
docker compose exec db psql -U postgres -d eneo

# Check container details
docker inspect eneo_backend
docker compose config

# Resource monitoring
docker stats --no-stream
docker system df
```

**Log analysis**:
```bash
# Follow logs in real-time
docker compose logs -f backend

# Search logs for errors
docker compose logs backend | grep -i error

# Save logs to file
docker compose logs > eneo-logs.txt

# Check log rotation
docker inspect eneo_backend | grep -i log
```

**Database debugging**:
```bash
# Connect to database
docker compose exec db psql -U postgres -d eneo

# Common queries
SELECT * FROM users LIMIT 5;
SELECT * FROM assistants LIMIT 5;
SELECT * FROM sessions ORDER BY created_at DESC LIMIT 10;

# Check database size
SELECT pg_database_size('eneo');

# Active connections
SELECT count(*) FROM pg_stat_activity WHERE datname = 'eneo';
```

**Network debugging**:
```bash
# Test internal connectivity
docker compose exec frontend curl http://backend:8000/version
docker compose exec backend curl http://redis:6379

# Port scanning
nmap -p 3000,8000,5432,6379 localhost

# DNS resolution
docker compose exec frontend nslookup backend
```

---

## 📞 Getting Additional Help

### When to Seek Help

**Community Support**:
- GitHub Issues for bugs and feature requests
- GitHub Discussions for questions and ideas
- Check existing issues before creating new ones

**Enterprise Support**:
- Email: digitalisering@sundsvall.se
- Include detailed error logs
- Specify your environment (development/production)
- Describe reproduction steps

### Information to Include

When reporting issues, include:

1. **Environment details**:
   ```bash
   docker --version
   docker compose version
   uname -a  # Operating system
   ```

2. **Service status**:
   ```bash
   docker compose ps
   docker compose logs --tail=50
   ```

3. **Configuration files**:
   - Environment variables (remove sensitive data)
   - Docker Compose configuration
   - Error messages and stack traces

4. **Reproduction steps**:
   - Exact commands that cause the issue
   - Expected vs actual behavior
   - Screenshots if relevant

---

## 📋 Maintenance Tasks

### Regular Maintenance

**Daily**:
```bash
# Check service health
docker compose ps

# Monitor disk usage
df -h

# Review error logs
docker compose logs --since=24h | grep -i error
```

**Weekly**:
```bash
# Update container images
docker compose pull
docker compose up -d

# Clean up unused Docker resources
docker system prune -f

# Database maintenance
docker compose exec db vacuumdb -U postgres -d eneo --analyze
```

**Monthly**:
```bash
# Full system backup
# Review and rotate logs
# Update dependencies
# Security patches
```

---

Remember: Most issues can be resolved by checking logs, verifying configuration, and ensuring all services are running properly. When in doubt, restart the affected services and check the logs for detailed error messages.