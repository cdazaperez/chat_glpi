# Deployment Guide

## Prerequisites

- Docker and Docker Compose installed
- Access to GLPI instance with API enabled
- OpenAI API key
- (Production) SSL certificates
- (Production) Domain name configured

## Local Development

### 1. Clone and Configure

```bash
# Clone the repository
cd /path/to/chat_glpi

# Copy environment template
cp .env.example .env

# Edit .env with your values
nano .env
```

### 2. Configure Required Variables

```bash
# GLPI Configuration (required)
GLPI_BASE_URL=https://your-glpi-instance.com
GLPI_APP_TOKEN=your-app-token
GLPI_USERNAME=api-user
GLPI_PASSWORD=your-password

# OpenAI Configuration (required)
OPENAI_API_KEY=sk-your-api-key
OPENAI_MODEL=gpt-4.1-mini

# App Configuration
APP_ENV=dev
APP_ALLOWED_ORIGINS=http://localhost:3000
```

### 3. Start Services

```bash
# Build and start all services
docker-compose up --build

# Or run in background
docker-compose up -d --build
```

### 4. Verify Deployment

```bash
# Check health endpoint
curl http://localhost:8000/health

# Check readiness
curl http://localhost:8000/health/ready
```

### 5. Access the Application

- Frontend: http://localhost:3000
- API Docs: http://localhost:8000/docs (dev only)
- API ReDoc: http://localhost:8000/redoc (dev only)

## Local Development without Docker

If you prefer to run the services locally without Docker:

### Backend (Python)

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn app.main:app --reload --port 8000
```

### Frontend (Bun)

The frontend uses **Bun** as the package manager and runtime.

```bash
# Install Bun (if not already installed)
# macOS/Linux:
curl -fsSL https://bun.sh/install | bash

# Install dependencies
cd frontend
bun install

# Run development server
bun run dev
```

The frontend will be available at http://localhost:3000

### Redis (Optional for local dev)

```bash
# Using Docker for Redis only
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Or install locally on macOS
brew install redis
brew services start redis
```

## Production Deployment

### Option A: Docker Compose (Simple)

#### 1. Prepare the Server

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

#### 2. Configure SSL Certificates

```bash
# Create SSL directory
mkdir -p infra/nginx/ssl

# Option 1: Use Let's Encrypt (certbot)
sudo apt install certbot
sudo certbot certonly --standalone -d helpdesk-ai.yourdomain.com
sudo cp /etc/letsencrypt/live/helpdesk-ai.yourdomain.com/fullchain.pem infra/nginx/ssl/cert.pem
sudo cp /etc/letsencrypt/live/helpdesk-ai.yourdomain.com/privkey.pem infra/nginx/ssl/key.pem

# Option 2: Use existing certificates
cp /path/to/your/certificate.pem infra/nginx/ssl/cert.pem
cp /path/to/your/private-key.pem infra/nginx/ssl/key.pem
```

#### 3. Configure Environment

```bash
# Copy production environment
cp .env.example .env.prod

# Edit with production values
nano .env.prod
```

Key production settings:
```bash
APP_ENV=prod
APP_ALLOWED_ORIGINS=https://helpdesk-ai.yourdomain.com
APP_SECRET_KEY=$(openssl rand -hex 32)
APP_LOG_LEVEL=info
NEXT_PUBLIC_API_URL=https://helpdesk-ai.yourdomain.com
```

#### 4. Deploy

```bash
# Deploy with production compose file
docker-compose -f infra/docker-compose.prod.yml --env-file .env.prod up -d --build
```

#### 5. Configure Automatic Certificate Renewal

```bash
# Add to crontab
0 0 1 * * certbot renew --quiet && docker-compose -f /path/to/infra/docker-compose.prod.yml restart nginx
```

### Option B: Kubernetes

#### 1. Create Namespace

```bash
kubectl create namespace helpdesk-ai
```

#### 2. Create Secrets

```bash
kubectl create secret generic helpdesk-ai-secrets \
  --from-literal=GLPI_APP_TOKEN=your-token \
  --from-literal=GLPI_PASSWORD=your-password \
  --from-literal=OPENAI_API_KEY=sk-your-key \
  --from-literal=APP_SECRET_KEY=$(openssl rand -hex 32) \
  -n helpdesk-ai
```

#### 3. Create ConfigMap

```bash
kubectl create configmap helpdesk-ai-config \
  --from-literal=GLPI_BASE_URL=https://your-glpi.com \
  --from-literal=GLPI_USERNAME=api-user \
  --from-literal=OPENAI_MODEL=gpt-4.1-mini \
  --from-literal=APP_ENV=prod \
  -n helpdesk-ai
```

#### 4. Apply Manifests

```bash
kubectl apply -f infra/k8s/ -n helpdesk-ai
```

## Health Monitoring

### Health Check Endpoints

| Endpoint | Purpose | Expected Response |
|----------|---------|-------------------|
| GET /health | Liveness | 200 OK |
| GET /health/ready | Readiness | 200 OK with component status |

### Example Health Check Script

```bash
#!/bin/bash
HEALTH_URL="http://localhost:8000/health/ready"
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" $HEALTH_URL)

if [ $RESPONSE -eq 200 ]; then
    echo "Health check passed"
    exit 0
else
    echo "Health check failed: HTTP $RESPONSE"
    exit 1
fi
```

## Updating the Application

### Docker Compose Update

```bash
# Pull latest changes
git pull

# Rebuild and restart
docker-compose down
docker-compose up -d --build
```

### Zero-Downtime Update (Production)

```bash
# Build new images
docker-compose -f infra/docker-compose.prod.yml build

# Rolling restart (if using replicas)
docker-compose -f infra/docker-compose.prod.yml up -d --no-deps --scale backend=2
docker-compose -f infra/docker-compose.prod.yml up -d --no-deps --scale backend=1
```

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker-compose logs backend
docker-compose logs frontend

# Check for missing environment variables
docker-compose config
```

### GLPI Connection Issues

```bash
# Test GLPI connectivity from container
docker-compose exec backend curl -I https://your-glpi.com/apirest.php

# Check GLPI credentials
docker-compose exec backend python -c "
from app.core.config import get_settings
s = get_settings()
print(f'GLPI URL: {s.glpi.base_url}')
"
```

### Redis Connection Issues

```bash
# Check Redis is running
docker-compose ps redis

# Test Redis connection
docker-compose exec redis redis-cli ping
```

### High Memory Usage

```bash
# Check container resources
docker stats

# Limit container memory in docker-compose.yml
services:
  backend:
    deploy:
      resources:
        limits:
          memory: 1G
```

## Backup and Recovery

### Backup Redis Data

```bash
# Create backup
docker-compose exec redis redis-cli BGSAVE
docker cp $(docker-compose ps -q redis):/data/dump.rdb ./backup/

# Restore backup
docker cp ./backup/dump.rdb $(docker-compose ps -q redis):/data/
docker-compose restart redis
```

### Backup Logs

```bash
# Export container logs
docker-compose logs --no-color > logs_$(date +%Y%m%d).txt
```

## Scaling

### Horizontal Scaling (Docker Compose)

```bash
# Scale backend replicas
docker-compose up -d --scale backend=3
```

### Load Balancer Configuration

Update nginx upstream for multiple backends:
```nginx
upstream backend {
    least_conn;
    server backend_1:8000;
    server backend_2:8000;
    server backend_3:8000;
    keepalive 32;
}
```

## Security Hardening

### Firewall Rules

```bash
# Allow only necessary ports
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw deny 8000/tcp  # Block direct backend access
sudo ufw deny 6379/tcp  # Block direct Redis access
sudo ufw enable
```

### Restrict API Access

Update nginx to restrict `/docs` and `/redoc`:
```nginx
location ~ ^/(docs|redoc) {
    deny all;
    return 404;
}
```

## Environment Variables Reference

See `.env.example` for the complete list of configuration options.
