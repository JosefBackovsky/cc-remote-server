# Firewall LLM Triage — Phase 1: Squid → mitmproxy

> **For agentic workers:** REQUIRED SUB-SKILL: Use cf-powers:subagent-driven-development (recommended) or cf-powers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Squid proxy with mitmproxy while maintaining functional equivalence — same whitelist behavior, same dashboard, same ports.

**Architecture:** mitmproxy runs as MITM proxy on port 3128 with a Python addon that checks domains against `whitelist.txt`. Unknown domains are blocked with HTTP 403. FastAPI dashboard continues to run on port 8080 for manual whitelist management. CA cert is generated at startup and shared with devcontainer via volume.

**Tech Stack:** Python 3.12, mitmproxy, FastAPI, SQLite, Docker

**Index:** [`plan-index.md`](./2026-04-08-firewall-llm-triage-plan-index.md)

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `services/firewall/Dockerfile` | Docker image build | Rewrite (python:3.12-slim + mitmproxy) |
| `services/firewall/entrypoint.sh` | Container startup | Rewrite (mitmproxy + uvicorn) |
| `services/firewall/manager/firewall_addon.py` | mitmproxy addon — whitelist check | Create |
| `services/firewall/manager/requirements.txt` | Python deps | Modify (add mitmproxy) |
| `services/firewall/squid.conf` | Squid config | Delete |
| `services/firewall/ERR_BLOCKED` | Squid error page | Delete |
| `generator/src/templates/base/docker-compose.yml.ejs` | Compose template | Modify (cert volume, healthcheck) |
| `generator/src/templates/base/init-firewall.sh.ejs` | Devcontainer firewall init | Modify (CA cert install + SSL env vars) |
| `services/firewall/manager/main.py` | FastAPI app | Minor modify (remove logparser import for blocked endpoint) |
| `services/firewall/manager/logparser.py` | Squid log parser | Delete (replaced by mitmproxy logging) |

Files that remain unchanged: `whitelist.py`, `database.py`, `whitelist-default.txt`, `templates/index.html`, `generator.js`, `devcontainer.json.ejs`, `Dockerfile.ejs`, `build-firewall.yml`.

---

### Task 1: Create basic mitmproxy addon with whitelist check

**Files:**
- Create: `services/firewall/manager/firewall_addon.py`
- Create: `services/firewall/manager/test_firewall_addon.py`

- [ ] **Step 1: Write the failing test**

```python
# services/firewall/manager/test_firewall_addon.py
import unittest
from unittest.mock import MagicMock, patch
from firewall_addon import WhitelistAddon


class TestWhitelistAddon(unittest.TestCase):
    def setUp(self):
        self.addon = WhitelistAddon.__new__(WhitelistAddon)
        self.addon._whitelist = {"github.com", "pypi.org", "api.anthropic.com"}

    def test_allowed_domain_passes(self):
        flow = MagicMock()
        flow.request.pretty_host = "github.com"
        flow.request.url = "https://github.com/user/repo"
        flow.response = None
        self.addon.request(flow)
        self.assertIsNone(flow.response)

    def test_blocked_domain_gets_403(self):
        flow = MagicMock()
        flow.request.pretty_host = "evil.com"
        flow.request.url = "https://evil.com/exfil"
        flow.response = None
        self.addon.request(flow)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)

    def test_subdomain_not_matched(self):
        """Whitelist contains github.com, but sub.github.com should be blocked."""
        flow = MagicMock()
        flow.request.pretty_host = "sub.github.com"
        flow.request.url = "https://sub.github.com/path"
        flow.response = None
        self.addon.request(flow)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)

    def test_parent_domain_whitelisted_with_dot_prefix(self):
        """Whitelist entry .github.com should match sub.github.com."""
        self.addon._whitelist = {".github.com", "pypi.org"}
        flow = MagicMock()
        flow.request.pretty_host = "sub.github.com"
        flow.request.url = "https://sub.github.com/path"
        flow.response = None
        self.addon.request(flow)
        self.assertIsNone(flow.response)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/services/firewall/manager && python -m unittest test_firewall_addon -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'firewall_addon'`

- [ ] **Step 3: Write minimal implementation**

```python
# services/firewall/manager/firewall_addon.py
"""mitmproxy addon for domain-based whitelist filtering.

Phase 1: functional equivalent of Squid whitelist.
Reads whitelist from whitelist.py (shared with FastAPI), reloads periodically,
blocks non-whitelisted domains with 403.
"""

import json
import logging
import time

from mitmproxy import http
from whitelist import read_whitelist

logger = logging.getLogger("firewall")

RELOAD_INTERVAL = 5  # seconds


def _is_whitelisted(domain: str, whitelist: set[str]) -> bool:
    """Check if domain is allowed by the whitelist.

    Supports exact match and .suffix match (e.g. .github.com matches sub.github.com).
    """
    domain = domain.lower()
    if domain in whitelist:
        return True
    for entry in whitelist:
        if entry.startswith(".") and domain.endswith(entry):
            return True
    return False


class WhitelistAddon:
    def __init__(self):
        self._whitelist = set(d.lower() for d in read_whitelist())
        self._last_reload = time.monotonic()
        logger.info("Loaded %d whitelist entries", len(self._whitelist))

    def _maybe_reload(self):
        """Reload whitelist every RELOAD_INTERVAL seconds.
        
        Note: there is a potential ~5s window where a newly-approved domain
        is still blocked. This matches the old Squid checksum watcher behavior.
        """
        now = time.monotonic()
        if now - self._last_reload >= RELOAD_INTERVAL:
            self._whitelist = set(d.lower() for d in read_whitelist())
            self._last_reload = now

    def request(self, flow: http.HTTPFlow) -> None:
        self._maybe_reload()
        domain = flow.request.pretty_host
        if _is_whitelisted(domain, self._whitelist):
            return  # allowed
        # Block with 403
        flow.response = http.Response.make(
            403,
            json.dumps({
                "blocked": True,
                "domain": domain,
                "decision": "blocked",
                "reasoning": f"Domain {domain} is not on the whitelist",
            }),
            {"Content-Type": "application/json"},
        )
        logger.warning("Blocked: %s %s", flow.request.method, flow.request.url)


addons = [WhitelistAddon()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /workspace/services/firewall/manager && python -m unittest test_firewall_addon -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/firewall/manager/firewall_addon.py services/firewall/manager/test_firewall_addon.py
git commit -m "feat(firewall): add mitmproxy whitelist addon with tests"
```

---

### Task 2: New Dockerfile

**Files:**
- Modify: `services/firewall/Dockerfile`

- [ ] **Step 1: Rewrite Dockerfile**

```dockerfile
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY manager/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Copy application code
WORKDIR /app
COPY manager/ /app/

# Copy default whitelist
COPY whitelist-default.txt /opt/whitelist-default.txt

# Copy entrypoint
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Persistent data directory
RUN mkdir -p /data/logs /data/certs /audit

EXPOSE 3128 8080

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
```

- [ ] **Step 2: Update requirements.txt**

```
fastapi==0.115.*
uvicorn[standard]==0.34.*
aiosqlite==0.21.*
jinja2==3.1.*
mitmproxy>=10.0,<12.0
```

- [ ] **Step 3: Verify Dockerfile builds**

Run: `cd /workspace/services/firewall && docker build -t cc-remote-firewall:test .`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add services/firewall/Dockerfile services/firewall/manager/requirements.txt
git commit -m "feat(firewall): new Dockerfile with mitmproxy instead of Squid"
```

---

### Task 3: New entrypoint script

**Files:**
- Modify: `services/firewall/entrypoint.sh`

- [ ] **Step 1: Rewrite entrypoint.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="/data"
WHITELIST="$DATA_DIR/whitelist.txt"
CERT_DIR="$DATA_DIR/certs"
DEFAULT_WHITELIST="/opt/whitelist-default.txt"

# Ensure directories exist
mkdir -p "$DATA_DIR/logs" "$CERT_DIR"

# Initialize whitelist if not exists (first run)
if [ ! -f "$WHITELIST" ]; then
    cp "$DEFAULT_WHITELIST" "$WHITELIST"
    echo "[entrypoint] Initialized whitelist from defaults."
fi

# Append extra domains from environment (idempotent)
if [ -n "${EXTRA_DOMAINS:-}" ]; then
    IFS=',' read -ra DOMAINS <<< "$EXTRA_DOMAINS"
    for domain in "${DOMAINS[@]}"; do
        domain=$(echo "$domain" | xargs)  # trim whitespace
        if [ -n "$domain" ] && ! grep -qxF "$domain" "$WHITELIST" 2>/dev/null; then
            echo "$domain" >> "$WHITELIST"
            echo "[entrypoint] Added extra domain: $domain"
        fi
    done
fi

# Generate mitmproxy CA certificate if not exists
if [ ! -f "$HOME/.mitmproxy/mitmproxy-ca.pem" ]; then
    echo "[entrypoint] Generating mitmproxy CA certificate..."
    # mitmdump with a dummy run to generate the CA cert
    timeout 5 mitmdump --set confdir="$HOME/.mitmproxy" -p 0 > /dev/null 2>&1 || true
    echo "[entrypoint] CA certificate generated."
fi

# Copy public CA cert to shared volume (devcontainer reads this)
if [ -f "$HOME/.mitmproxy/mitmproxy-ca-cert.pem" ]; then
    cp "$HOME/.mitmproxy/mitmproxy-ca-cert.pem" "$CERT_DIR/mitmproxy-ca-cert.pem"
    echo "[entrypoint] CA certificate available at $CERT_DIR/mitmproxy-ca-cert.pem"
else
    echo "[entrypoint] ERROR: CA certificate not found!" >&2
    exit 1
fi

# Background: mitmproxy
echo "[entrypoint] Starting mitmproxy on port 3128..."
mitmdump \
    --listen-host 0.0.0.0 \
    --listen-port 3128 \
    --set confdir="$HOME/.mitmproxy" \
    -s /app/firewall_addon.py \
    > "$DATA_DIR/logs/mitmproxy.log" 2>&1 &
MITM_PID=$!

# Wait for mitmproxy to be ready
for i in $(seq 1 30); do
    if bash -c 'echo > /dev/tcp/localhost/3128' 2>/dev/null; then
        echo "[entrypoint] mitmproxy ready on port 3128."
        break
    fi
    sleep 1
done

# Foreground: Firewall Manager
echo "[entrypoint] Starting Firewall Manager on port 8080..."
cd /app
exec uvicorn main:app --host 0.0.0.0 --port 8080
```

- [ ] **Step 2: Commit**

```bash
git add services/firewall/entrypoint.sh
git commit -m "feat(firewall): new entrypoint with mitmproxy + CA cert generation"
```

---

### Task 4: Update generator templates for CA cert distribution

**Files:**
- Modify: `generator/src/templates/base/docker-compose.yml.ejs`
- Modify: `generator/src/templates/base/init-firewall.sh.ejs`

- [ ] **Step 1: Update docker-compose.yml.ejs — add cert volume to firewall and devcontainer**

In `generator/src/templates/base/docker-compose.yml.ejs`, add cert volume mount to devcontainer service and firewall service. Also update healthcheck.

Find the devcontainer volumes section (around line 12-27) and add the cert volume:
```yaml
      - firewall-certs:/certs:ro
```

Find the firewall service section (around line 57-73) and:
1. Add cert volume mount:
```yaml
    volumes:
      - firewall-data:/data
      - firewall-certs:/data/certs
```
2. Update healthcheck to verify cert exists:
```yaml
    healthcheck:
      test: ["CMD-SHELL", "test -f /data/certs/mitmproxy-ca-cert.pem && bash -c 'echo > /dev/tcp/localhost/3128' && curl -sf http://localhost:8080/api/whitelist > /dev/null"]
```

Add `firewall-certs:` to the volumes section at the bottom.

- [ ] **Step 2: Update init-firewall.sh.ejs — install CA cert + SSL env vars**

Rewrite `generator/src/templates/base/init-firewall.sh.ejs`:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "Configuring firewall (proxy mode)..."

# Install mitmproxy CA certificate into trust store
CERT_PATH="/certs/mitmproxy-ca-cert.pem"
if [ -f "$CERT_PATH" ]; then
    echo "Installing mitmproxy CA certificate..."
    sudo cp "$CERT_PATH" /usr/local/share/ca-certificates/mitmproxy-ca-cert.crt
    sudo update-ca-certificates 2>/dev/null || true
    echo "CA certificate installed."
else
    echo "WARNING: mitmproxy CA certificate not found at $CERT_PATH"
fi

# Set SSL environment variables for common tools
export NODE_EXTRA_CA_CERTS="$CERT_PATH"
export REQUESTS_CA_BUNDLE="/etc/ssl/certs/ca-certificates.crt"
export SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt"
export GIT_SSL_CAINFO="/etc/ssl/certs/ca-certificates.crt"

# Persist SSL env vars so they survive shell restarts
cat >> /home/node/.container-env << 'ENVEOF'
export NODE_EXTRA_CA_CERTS="/certs/mitmproxy-ca-cert.pem"
export REQUESTS_CA_BUNDLE="/etc/ssl/certs/ca-certificates.crt"
export SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt"
export GIT_SSL_CAINFO="/etc/ssl/certs/ca-certificates.crt"
ENVEOF

# Flush existing rules
iptables -F OUTPUT
iptables -F INPUT

# Allow loopback
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A INPUT -i lo -j ACCEPT

# Allow established/related connections
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Allow Docker embedded DNS only
iptables -A OUTPUT -d 127.0.0.11 -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -d 127.0.0.11 -p tcp --dport 53 -j ACCEPT

# Allow Docker internal networks (proxy, services...)
iptables -A OUTPUT -d 10.0.0.0/8 -j ACCEPT
iptables -A OUTPUT -d 172.16.0.0/12 -j ACCEPT
iptables -A OUTPUT -d 192.168.0.0/16 -j ACCEPT

# Block everything else — forces HTTP/HTTPS through proxy
iptables -A OUTPUT -j DROP

echo "Firewall configured. All HTTP/HTTPS traffic routed through proxy."
```

- [ ] **Step 3: Run generator tests to verify templates are valid**

Run: `cd /workspace/generator && npm test`
Expected: Tests pass (or fail only on unrelated issues)

- [ ] **Step 4: Commit**

```bash
git add generator/src/templates/base/docker-compose.yml.ejs generator/src/templates/base/init-firewall.sh.ejs
git commit -m "feat(generator): add CA cert distribution for mitmproxy"
```

---

### Task 5: Update FastAPI app and dashboard — remove Squid-specific code

**Files:**
- Modify: `services/firewall/manager/main.py`
- Modify: `services/firewall/manager/templates/index.html`
- Delete: `services/firewall/manager/logparser.py`

- [ ] **Step 1: Update main.py — remove logparser dependency from blocked endpoint**

In `services/firewall/manager/main.py`:
1. Remove `from logparser import parse_blocked_domains` (line 10)
2. Update `get_blocked_domains()` endpoint (lines 98-104) to return empty list with a note:

```python
@app.get("/api/blocked")
async def get_blocked_domains():
    """Blocked domains — placeholder, will be replaced by LLM decisions in Phase 3."""
    return []
```

- [ ] **Step 2: Update dashboard — remove "Squid log" reference**

In `services/firewall/manager/templates/index.html`, find `No blocked domains in Squid log.` (around line 100) and change to `No blocked domains.`

- [ ] **Step 3: Delete logparser.py**

Run: `rm /workspace/services/firewall/manager/logparser.py`

- [ ] **Step 4: Run existing tests if any**

Run: `cd /workspace/services/firewall/manager && python -m pytest -v 2>/dev/null || echo "No existing test suite"`

- [ ] **Step 5: Commit**

```bash
git add services/firewall/manager/main.py services/firewall/manager/templates/index.html
git rm services/firewall/manager/logparser.py
git commit -m "refactor(firewall): remove Squid-specific logparser, stub blocked endpoint"
```

---

### Task 6: Clean up Squid artifacts

**Files:**
- Delete: `services/firewall/squid.conf`
- Delete: `services/firewall/ERR_BLOCKED`

- [ ] **Step 1: Remove Squid-specific files**

```bash
git rm services/firewall/squid.conf services/firewall/ERR_BLOCKED
```

- [ ] **Step 2: Commit**

```bash
git commit -m "chore(firewall): remove Squid config and error page"
```

---

### Task 7: Docker build + smoke test

**Files:** None (verification only)

- [ ] **Step 1: Build Docker image**

Run: `cd /workspace/services/firewall && docker build -t cc-remote-firewall:test .`
Expected: Build succeeds without errors

- [ ] **Step 2: Start container and verify both processes start**

```bash
docker run -d --name fw-test \
  -p 3128:3128 -p 8180:8080 \
  -v /tmp/fw-test-data:/data \
  cc-remote-firewall:test

# Wait for startup
sleep 5

# Check mitmproxy is running
docker exec fw-test bash -c 'echo > /dev/tcp/localhost/3128' && echo "mitmproxy OK" || echo "mitmproxy FAIL"

# Check FastAPI is running
curl -sf http://localhost:8180/api/whitelist > /dev/null && echo "FastAPI OK" || echo "FastAPI FAIL"

# Check CA cert was generated
docker exec fw-test test -f /data/certs/mitmproxy-ca-cert.pem && echo "CA cert OK" || echo "CA cert FAIL"
```

Expected: All three checks pass

- [ ] **Step 3: Test proxy allows whitelisted domain**

```bash
# Copy CA cert from container
docker cp fw-test:/data/certs/mitmproxy-ca-cert.pem /tmp/fw-ca.pem

# Test whitelisted domain (github.com is in whitelist-default.txt)
curl -sf --proxy http://localhost:3128 --cacert /tmp/fw-ca.pem https://github.com -o /dev/null -w "%{http_code}" && echo " - github.com OK"

# Test blocked domain
HTTP_CODE=$(curl -s --proxy http://localhost:3128 --cacert /tmp/fw-ca.pem https://evil-test-domain.example.com -o /dev/null -w "%{http_code}" 2>/dev/null || echo "000")
echo "evil-test-domain: $HTTP_CODE (expected 403)"
```

Expected: github.com returns 200, evil domain returns 403

- [ ] **Step 4: Test dashboard still works**

```bash
curl -sf http://localhost:8180/ | head -5
```

Expected: HTML response containing "Firewall Manager Dashboard"

- [ ] **Step 5: Clean up**

```bash
docker stop fw-test && docker rm fw-test
rm -rf /tmp/fw-test-data /tmp/fw-ca.pem
```

- [ ] **Step 6: Commit test results (if any test scripts were created)**

No code changes — this is verification only.

---

### Task 8: Update README

**Files:**
- Modify: `services/firewall/README.md`

- [ ] **Step 1: Update README to reflect mitmproxy**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add services/firewall/README.md
git commit -m "docs(firewall): update README for mitmproxy"
```
