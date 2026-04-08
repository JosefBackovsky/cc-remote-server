# Firewall

Combined mitmproxy + Firewall Manager for devcontainer network isolation.

**Docker Hub:** [`josefbackovsky/cc-remote-firewall`](https://hub.docker.com/r/josefbackovsky/cc-remote-firewall)

## What it does

- **mitmproxy** on port 3128 — HTTPS-inspecting proxy with domain whitelist filtering
- **Firewall Manager** on port 8080 — web dashboard + API for whitelist approval workflow
- **CA certificate** auto-generated and shared with devcontainer for TLS interception

## Usage

```yaml
# docker-compose.yml
firewall:
  image: josefbackovsky/cc-remote-firewall:latest
  ports:
    - "8180:8080"
  volumes:
    - firewall-data:/data
    - firewall-certs:/data/certs
  environment:
    - EXTRA_DOMAINS=custom.domain.com,another.domain.com
```

The devcontainer must mount the cert volume and install the CA certificate:
```yaml
devcontainer:
  volumes:
    - firewall-certs:/certs:ro
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EXTRA_DOMAINS` | (empty) | Comma-separated project-specific domains to add to whitelist |
| `WHITELIST_PATH` | `/data/whitelist.txt` | Runtime whitelist file path |
| `DB_PATH` | `/data/approval.db` | SQLite database path |
