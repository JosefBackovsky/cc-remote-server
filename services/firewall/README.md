# Firewall

Combined Squid proxy + Firewall Manager for devcontainer network isolation.

**Docker Hub:** [`josefbackovsky/cc-remote-firewall`](https://hub.docker.com/r/josefbackovsky/cc-remote-firewall)

**Status:** Active. See [architecture docs](https://github.com/JosefBackovsky/cc-remote/blob/main/docs/architecture/squid-proxy.md) for design.

## What it does

- **Squid proxy** on port 3128 — domain-based whitelist filtering for HTTP/HTTPS
- **Firewall Manager** on port 8080 — web dashboard + API for whitelist approval workflow

## Usage

```yaml
# docker-compose.yml
firewall:
  image: josefbackovsky/cc-remote-firewall:latest
  ports:
    - "8180:8080"
  volumes:
    - firewall-data:/data
  environment:
    - EXTRA_DOMAINS=custom.domain.com,another.domain.com
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EXTRA_DOMAINS` | (empty) | Comma-separated project-specific domains to add to whitelist |
| `WHITELIST_PATH` | `/data/whitelist.txt` | Runtime whitelist file path |
| `ACCESS_LOG_PATH` | `/data/logs/access.log` | Squid access log path |
| `DB_PATH` | `/data/approval.db` | SQLite database path |
