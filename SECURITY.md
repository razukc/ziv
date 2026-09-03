# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in SkillForge, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please email: **security@skillforge.dev**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge receipt within 48 hours and provide a status update within 7 days.

## Scope

This security policy covers:

- The SkillForge application (frontend and backend)
- The API endpoints and authentication
- The pipeline generation and export functionality
- Generated ROS2 package artifacts

**Out of scope:**
- NVIDIA tool vulnerabilities (report to NVIDIA directly)
- Nebius Token Factory infrastructure (report to Nebius)
- Third-party dependencies (we will coordinate with upstream)

## Security Considerations

### API Keys

- SkillForge requires a `NEBIUS_API_KEY` for the Nemotron API
- Never commit `.env` files or API keys to version control
- Rotate keys immediately if compromised
- Use environment variables or secret managers in production

### Generated Artifacts

- Generated ROS2 packages execute code on the target robot
- Review generated `package.xml` and `CMakeLists.txt` before building
- Validate pipeline JSON before execution
- Use sandboxed environments for untrusted pipeline inputs

### Network Security

- The backend exposes API endpoints on port 8000
- In production, use HTTPS and restrict CORS origins
- Monitor for unusual API usage patterns

### Share-Link Rate Limiting

`GET /api/pipeline/{id}` — the endpoint behind share links — is rate limited to
prevent bulk scraping of composed pipelines:

- **Limit:** `SHARE_LINK_RATE_LIMIT` (default 30) requests per
  `SHARE_LINK_RATE_WINDOW_SECONDS` (default 60 seconds), per client.
- **Keying:** the budget is keyed on the client's direct peer IP
  (`request.client.host`). Spoofable headers such as `X-Forwarded-For` are
  **not** trusted, so a scraper cannot reset its budget by rotating headers.
- **Response:** once the budget is exhausted the endpoint returns `429 Too
  Many Requests` with a `Retry-After` header instead of hitting the store.
- **Scope:** the limiter is in-memory and per-process. Each server instance
  enforces its own window, so a deployment behind a load balancer with many
  instances multiplies the effective limit (a single client can spread
  requests across instances). Deployments behind a reverse proxy that needs
  per-real-IP keying should terminate trusted proxy handling and set the
  client IP explicitly; otherwise all proxied clients share the proxy's
  budget.
- **Threat model:** pipeline IDs are content hashes (`p` + 10 hex chars,
  2^40 possible values), so blind enumeration is already impractical. The
  limiter additionally caps how fast any one client can probe IDs and makes
  automated scraping detectable. It is a mitigation, not a guarantee — treat
  shared pipelines as unauthenticated public data and never put sensitive
  content in them.
- **Configuration:** adjust `SHARE_LINK_RATE_LIMIT` and
  `SHARE_LINK_RATE_WINDOW_SECONDS` in `agent/server.py` before deploying.

### Input Validation

- Task descriptions are passed to Nemotron for processing
- The backend validates skill IDs against the catalog
- Pipeline JSON is validated before export
- User inputs are sanitized for display

## Best Practices for Deployment

1. **Environment variables** — Never hardcode API keys
2. **HTTPS** — Always use TLS in production
3. **CORS** — Restrict origins to your domain
4. **Rate limiting** — `GET /api/pipeline/{id}` is limited per client (30 req / 60s); extend to other endpoints as needed
5. **Logging** — Monitor API usage and errors
6. **Updates** — Keep dependencies current

## Dependency Security

We use `pip-audit` and `npm audit` to check for known vulnerabilities:

```bash
# Python
pip-audit -r agent/requirements.txt

# Node.js
cd frontend && npm audit
```

## Authentication

The current version uses API key authentication via environment variables. Future versions may add:
- JWT-based authentication
- Role-based access control
- API key rotation

## Data Privacy

- Task descriptions are sent to Nebius Token Factory for processing
- No user data is stored persistently
- Pipeline history is session-only (cleared on page reload)
- Composed pipelines are cached (capped at 50) purely so share links work: in **Upstash Redis** (7-day TTL) when `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN` are set, otherwise in `agent/pipeline_store.json` locally — delete the file to clear the local cache
- Share-link reads are rate limited per client (see Share-Link Rate Limiting above); treat shared pipelines as public
- Generated packages contain no PII

## Compliance

SkillForge is designed for research and development use. For production deployments:
- Review NVIDIA tool licenses for compliance requirements
- Ensure generated code meets your organization's security standards
- Conduct thorough testing before deploying to physical robots
- Follow your industry's safety protocols for robotic systems

## Updates

Security patches will be released as needed. Subscribe to GitHub releases for notifications.

---

Last updated: September 2026
