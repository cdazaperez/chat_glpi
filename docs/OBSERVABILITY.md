# Observability Documentation

## Overview

Helpdesk AI implements three pillars of observability:
1. **Logging** - Structured JSON logs with correlation IDs
2. **Metrics** - Request counts, latencies, error rates
3. **Tracing** - Distributed tracing (optional, via OpenTelemetry)

## Logging

### Log Format

All logs are output in JSON format for easy parsing:

```json
{
  "timestamp": "2024-01-15T10:30:45.123456+00:00",
  "level": "INFO",
  "logger": "app.services.glpi_client",
  "message": "Searching GLPI KB",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "location": {
    "file": "glpi_client.py",
    "line": 142,
    "function": "search_kb"
  },
  "data": {
    "query": "password reset",
    "category_id": null
  }
}
```

### Log Levels

| Level | Description | When to Use |
|-------|-------------|-------------|
| DEBUG | Detailed diagnostic information | Development only |
| INFO | General operational events | Normal operations |
| WARNING | Unexpected but handled events | Potential issues |
| ERROR | Error events that allow continued operation | Failures requiring attention |
| CRITICAL | Severe errors causing shutdown | System failures |

### Correlation ID

Every request is assigned a unique correlation ID that:
- Propagates through all log entries for that request
- Is returned in the `X-Correlation-ID` response header
- Can be used to trace requests across services

Example usage in logs:
```bash
# Find all logs for a specific request
cat logs.json | jq 'select(.correlation_id == "550e8400-e29b-41d4-a716-446655440000")'
```

### PII Masking

The following patterns are automatically masked in logs:

| Pattern | Replacement |
|---------|-------------|
| Email addresses | `[EMAIL_MASKED]` |
| Phone numbers | `[PHONE_MASKED]` |
| API keys (sk-*) | `[API_KEY_MASKED]` |
| Bearer tokens | `Bearer [TOKEN_MASKED]` |
| Passwords in URLs | `password=[MASKED]` |

### Log Configuration

```bash
# Set log level via environment variable
APP_LOG_LEVEL=debug  # debug, info, warn, error
```

## Metrics

### Available Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `chat_requests_total` | Counter | Total chat requests |
| `chat_requests_success` | Counter | Successful chat requests |
| `chat_requests_error` | Counter | Failed chat requests |
| `chat_response_time_seconds` | Histogram | Response latency |
| `glpi_requests_total` | Counter | GLPI API calls |
| `glpi_request_duration_seconds` | Histogram | GLPI API latency |
| `glpi_errors_total` | Counter | GLPI API errors |
| `openai_requests_total` | Counter | OpenAI API calls |
| `openai_tokens_used` | Counter | Total tokens consumed |
| `cache_hits_total` | Counter | Cache hits |
| `cache_misses_total` | Counter | Cache misses |
| `rate_limit_exceeded_total` | Counter | Rate limit violations |

### Prometheus Integration (Optional)

Enable metrics endpoint:
```bash
METRICS_ENABLED=true
METRICS_PORT=9090
```

Scrape config for Prometheus:
```yaml
scrape_configs:
  - job_name: 'helpdesk-ai'
    static_configs:
      - targets: ['backend:9090']
    metrics_path: '/metrics'
```

### Example Grafana Dashboard

Key panels to create:
1. **Request Rate** - `rate(chat_requests_total[5m])`
2. **Error Rate** - `rate(chat_requests_error[5m]) / rate(chat_requests_total[5m])`
3. **P99 Latency** - `histogram_quantile(0.99, chat_response_time_seconds)`
4. **Token Usage** - `increase(openai_tokens_used[1h])`
5. **Cache Hit Rate** - `cache_hits_total / (cache_hits_total + cache_misses_total)`

## Tracing (OpenTelemetry)

### Enable Tracing

```bash
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
OTEL_SERVICE_NAME=helpdesk-ai
```

### Trace Structure

A typical chat request creates the following spans:

```
[POST /api/chat] (root span)
├── [validate_request]
├── [get_session]
├── [llm_orchestrator.process_message]
│   ├── [check_guardrails]
│   ├── [openai.chat.completions.create]
│   ├── [execute_tool: glpi_kb_search]
│   │   └── [glpi_client.search_kb]
│   │       └── [http_request: GLPI API]
│   ├── [execute_tool: glpi_ticket_search]
│   │   └── [glpi_client.search_tickets]
│   │       └── [http_request: GLPI API]
│   └── [openai.chat.completions.create] (final response)
└── [save_session]
```

## Health Checks

### Endpoints

| Endpoint | Purpose | Checks |
|----------|---------|--------|
| `/health` | Liveness probe | API is running |
| `/health/ready` | Readiness probe | GLPI + Redis connectivity |

### Kubernetes Probes

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 30

readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
```

### Health Response Format

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:45.123456",
  "version": "1.0.0",
  "components": {
    "api": "ok",
    "glpi": "ok",
    "cache": "ok"
  }
}
```

## Alerting Recommendations

### Critical Alerts

| Condition | Threshold | Action |
|-----------|-----------|--------|
| Error rate > 10% | 5 minutes | Page on-call |
| P99 latency > 30s | 5 minutes | Investigate |
| GLPI connection failed | Any | Check GLPI status |
| Rate limit exceeded | > 100/min | Review traffic |

### Warning Alerts

| Condition | Threshold | Action |
|-----------|-----------|--------|
| Cache miss rate > 50% | 15 minutes | Check Redis |
| Token usage spike | 2x normal | Review usage |
| Error rate > 5% | 10 minutes | Monitor |

## Log Aggregation

### ELK Stack Example

Filebeat configuration:
```yaml
filebeat.inputs:
  - type: container
    paths:
      - /var/lib/docker/containers/*/*.log
    processors:
      - decode_json_fields:
          fields: ["message"]
          target: ""
          overwrite_keys: true

output.elasticsearch:
  hosts: ["elasticsearch:9200"]
  index: "helpdesk-ai-%{+yyyy.MM.dd}"
```

### Loki Example

Promtail configuration:
```yaml
scrape_configs:
  - job_name: helpdesk-ai
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
    relabel_configs:
      - source_labels: ['__meta_docker_container_name']
        target_label: 'container'
    pipeline_stages:
      - json:
          expressions:
            level: level
            correlation_id: correlation_id
```

## Debugging Tips

### Common Issues

1. **High Latency**
   - Check GLPI response times in logs
   - Review cache hit rate
   - Check OpenAI API status

2. **Rate Limit Errors**
   - Review `APP_RATE_LIMIT_RPM` setting
   - Check for traffic spikes in metrics
   - Consider per-user limits

3. **GLPI Connection Issues**
   - Verify GLPI credentials in environment
   - Check network connectivity
   - Review GLPI server logs

4. **Memory Issues**
   - Check conversation history size
   - Review Redis memory usage
   - Consider message limit reduction

### Debug Mode

Enable debug logging for troubleshooting:
```bash
APP_LOG_LEVEL=debug
```

**Warning:** Debug mode may log sensitive information. Use only in development.
