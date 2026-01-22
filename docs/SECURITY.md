# Security Documentation

## Security Checklist

### Pre-Deployment

- [ ] **Environment Variables**
  - [ ] All secrets stored in environment variables, NOT in code
  - [ ] `.env` file excluded from version control (`.gitignore`)
  - [ ] `.env.example` contains placeholders only (no real values)
  - [ ] `APP_SECRET_KEY` generated with cryptographic randomness
  - [ ] OpenAI API key has appropriate permissions/limits

- [ ] **GLPI Configuration**
  - [ ] GLPI API user has minimal required permissions
  - [ ] GLPI App Token is restricted to necessary endpoints
  - [ ] GLPI user cannot modify system configuration
  - [ ] GLPI password meets complexity requirements

- [ ] **Network Security**
  - [ ] TLS/HTTPS enabled for all external communications
  - [ ] Internal services communicate over private network
  - [ ] Firewall rules restrict access to necessary ports only
  - [ ] CORS configured with specific allowed origins (not `*`)

- [ ] **Authentication (if enabled)**
  - [ ] JWT secret is sufficiently long (256+ bits)
  - [ ] Token expiry is reasonably short (1 hour default)
  - [ ] Refresh token mechanism in place (if needed)

### Application Security

- [ ] **Input Validation**
  - [ ] All user inputs validated with Pydantic models
  - [ ] Maximum message length enforced (4000 chars default)
  - [ ] HTML/script tags stripped from inputs
  - [ ] SQL injection not possible (no raw SQL queries)

- [ ] **Rate Limiting**
  - [ ] API rate limiting enabled (30 RPM default)
  - [ ] Rate limit headers returned to clients
  - [ ] Different limits for authenticated vs anonymous users

- [ ] **Guardrails**
  - [ ] Prompt injection patterns detected and blocked
  - [ ] Credential/password requests blocked
  - [ ] SQL/system command patterns blocked
  - [ ] Out-of-scope requests handled gracefully

- [ ] **Data Protection**
  - [ ] PII masked in logs (emails, phones, etc.)
  - [ ] No secrets logged (tokens, passwords, API keys)
  - [ ] Session data encrypted at rest (Redis)
  - [ ] Ticket data from GLPI minimized (no unnecessary fields)

### Operational Security

- [ ] **Logging**
  - [ ] Structured JSON logging enabled
  - [ ] Correlation IDs track requests across services
  - [ ] Log levels appropriate for environment (info in prod)
  - [ ] Logs do NOT contain sensitive data

- [ ] **Monitoring**
  - [ ] Health check endpoints exposed
  - [ ] Metrics collected (request count, latency, errors)
  - [ ] Alerting configured for error thresholds

- [ ] **Container Security**
  - [ ] Non-root user in Docker containers
  - [ ] Read-only filesystem where possible
  - [ ] Resource limits configured (CPU, memory)
  - [ ] Base images regularly updated

## Threat Model

### Assets

1. **GLPI Credentials** - Access to helpdesk system
2. **OpenAI API Key** - Access to AI services (cost implications)
3. **User Data** - Chat history, ticket information
4. **Session Tokens** - User authentication state

### Threats & Mitigations

| Threat | Impact | Likelihood | Mitigation |
|--------|--------|------------|------------|
| Credential exposure in logs | High | Medium | PII masking, log scrubbing |
| Prompt injection | Medium | High | Guardrails, input validation |
| Rate limit bypass | Medium | Medium | Per-IP and per-user limits |
| Session hijacking | High | Low | HTTPS, secure cookies, short TTL |
| GLPI data exfiltration | High | Low | Minimal permissions, audit logging |
| DDoS attack | Medium | Medium | Rate limiting, WAF, CDN |
| XSS attack | Medium | Low | Input sanitization, CSP headers |

### Security Headers

The application sets the following security headers:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; ...
Strict-Transport-Security: max-age=63072000 (production)
```

## Incident Response

### Security Incident Procedure

1. **Identify** - Detect and confirm the incident
2. **Contain** - Isolate affected systems
3. **Eradicate** - Remove the threat
4. **Recover** - Restore normal operations
5. **Lessons Learned** - Document and improve

### Key Actions

**If API keys are compromised:**
1. Immediately rotate affected keys
2. Review API usage logs for unauthorized access
3. Update environment variables in all deployments
4. Monitor for continued unauthorized access

**If user data is exposed:**
1. Assess scope of exposure
2. Notify affected users as required
3. Review and strengthen access controls
4. Document incident for compliance

## Compliance Considerations

### Data Retention

- Chat session data: Retained for session duration + TTL
- Logs: Retain per organizational policy (default: 30 days)
- No long-term storage of chat content by default

### Privacy

- PII is masked in all logs
- User data from GLPI is summarized, not stored verbatim
- No personal identifiers shared with OpenAI beyond necessary context

### Audit Trail

- All API requests logged with correlation ID
- GLPI operations logged (search, get, create)
- Token usage tracked per session

## Security Updates

### Dependency Management

1. Regularly update Python dependencies:
   ```bash
   pip install --upgrade -r requirements.txt
   ```

2. Check for vulnerabilities:
   ```bash
   pip-audit
   ```

3. Update Docker base images monthly

### Vulnerability Disclosure

Report security vulnerabilities to: security@skillnet.com.co

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested mitigation (if any)
