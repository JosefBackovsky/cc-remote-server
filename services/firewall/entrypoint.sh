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
# PYTHONPATH ensures addon script can import sibling modules (rule_engine, etc.)
export PYTHONPATH=/app:${PYTHONPATH:-}
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
