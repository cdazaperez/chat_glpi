# Helpdesk AI

AI-powered helpdesk chat application integrated with GLPI (IT Service Management).

## Overview

Helpdesk AI enables IT support teams and end-users to get instant answers by querying GLPI's knowledge base and resolved tickets using natural language. Powered by OpenAI's language models with function calling, responses are always grounded in actual GLPI data.

### Key Features

- **Knowledge Base Search** - Query KB articles for documented solutions
- **Ticket History** - Find similar resolved issues and their solutions
- **Verifiable References** - Every response includes KB/Ticket IDs
- **Ticket Creation** - Optionally create tickets when no solution exists
- **Guardrails** - Block inappropriate requests and prompt injection
- **Privacy First** - PII masking in logs, no data stored beyond session

## Quick Start

### Prerequisites

- Docker and Docker Compose
- GLPI instance with REST API enabled
- OpenAI API key

### 1. Clone and Configure

```bash
git clone <repository-url>
cd chat_glpi

# Copy environment template
cp .env.example .env

# Edit with your values
nano .env
```

### 2. Set Required Variables

```env
# GLPI
GLPI_BASE_URL=https://your-glpi-instance.com
GLPI_APP_TOKEN=your-app-token
GLPI_USERNAME=api-user
GLPI_PASSWORD=your-password

# OpenAI
OPENAI_API_KEY=sk-your-api-key
OPENAI_MODEL=gpt-4.1-mini
```

### 3. Start the Application

```bash
docker-compose up --build
```

### 4. Access

- **Chat Interface**: http://localhost:3000
- **API Documentation**: http://localhost:8000/docs

## Architecture

```
┌─────────────┐     ┌─────────────────────────────────┐
│   Frontend  │────▶│          Backend API            │
│   (React)   │     │  ┌─────────┐    ┌───────────┐  │
│             │◀────│  │  GLPI   │    │    LLM    │  │
│  Chat UI    │     │  │ Client  │    │Orchestrator│  │
└─────────────┘     │  └────┬────┘    └─────┬─────┘  │
                    │       │               │         │
                    │       ▼               ▼         │
                    │  ┌─────────┐    ┌───────────┐  │
                    │  │  Redis  │    │  OpenAI   │  │
                    │  │  Cache  │    │    API    │  │
                    │  └─────────┘    └───────────┘  │
                    └─────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │      GLPI       │
                    │  (REST API)     │
                    └─────────────────┘
```

## Project Structure

```
chat_glpi/
├── backend/
│   ├── app/
│   │   ├── api/           # FastAPI routes and middleware
│   │   ├── core/          # Configuration and logging
│   │   ├── models/        # Pydantic schemas
│   │   ├── services/      # GLPI client, LLM orchestrator
│   │   └── tests/         # Unit and integration tests
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── app/           # Next.js app router
│   │   ├── components/    # React components
│   │   ├── hooks/         # Custom hooks
│   │   ├── services/      # API client
│   │   └── types/         # TypeScript types
│   ├── Dockerfile
│   └── package.json
├── infra/
│   ├── docker-compose.prod.yml
│   └── nginx/             # Nginx configuration
├── docs/
│   ├── ARCHITECTURE.md    # System design
│   ├── SECURITY.md        # Security checklist
│   ├── OBSERVABILITY.md   # Logging and metrics
│   ├── DEPLOYMENT.md      # Deployment guide
│   └── EXAMPLES.md        # Example conversations
├── docker-compose.yml     # Development compose
├── .env.example           # Environment template
└── README.md
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chat` | Send message, get AI response |
| POST | `/api/ticket` | Create support ticket |
| GET | `/api/session/{id}` | Get session history |
| DELETE | `/api/session/{id}` | Delete session |
| GET | `/health` | Health check |
| GET | `/health/ready` | Readiness check |

## Chat Request/Response

### Request
```json
{
  "message": "How do I reset my password?",
  "session_id": null,
  "context": {
    "user_email": "user@example.com"
  }
}
```

### Response
```json
{
  "response": "Based on KB #142, here's how to reset...",
  "session_id": "uuid",
  "references": [
    {"type": "kb", "id": 142, "title": "Password Reset Guide"}
  ],
  "suggested_actions": [],
  "metadata": {
    "processing_time_ms": 1234,
    "sources_consulted": ["kb", "tickets"]
  }
}
```

## Configuration

All configuration via environment variables. See `.env.example` for complete list.

### Key Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GLPI_BASE_URL` | Yes | GLPI instance URL |
| `GLPI_APP_TOKEN` | Yes | GLPI API application token |
| `GLPI_USERNAME` | Yes | GLPI API username |
| `GLPI_PASSWORD` | Yes | GLPI API password |
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `OPENAI_MODEL` | Yes | Model to use (e.g., gpt-4.1-mini) |
| `APP_ALLOWED_ORIGINS` | No | CORS origins (default: localhost:3000) |
| `APP_RATE_LIMIT_RPM` | No | Rate limit per minute (default: 30) |

## Testing

```bash
# Run backend tests
cd backend
pip install -r requirements.txt
pytest

# Run with coverage
pytest --cov=app --cov-report=html
```

## Security

- All secrets via environment variables
- PII masked in logs
- Rate limiting enabled
- Guardrails block malicious prompts
- HTTPS required in production

See [SECURITY.md](docs/SECURITY.md) for the complete security checklist.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) - System design and decisions
- [Deployment](docs/DEPLOYMENT.md) - Deployment guide
- [Security](docs/SECURITY.md) - Security checklist
- [Observability](docs/OBSERVABILITY.md) - Logging and monitoring
- [Examples](docs/EXAMPLES.md) - Example conversations

## License

Proprietary - SkillNet

## Support

For issues and feature requests, contact: support@skillnet.com.co
