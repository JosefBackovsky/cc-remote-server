#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="/data"
WHITELIST="$DATA_DIR/whitelist.txt"
LOG_DIR="$DATA_DIR/logs"
SQUID_CONF="/opt/squid.conf"
DEFAULT_WHITELIST="/opt/whitelist-default.txt"
CHECKSUM_FILE="/tmp/whitelist.md5"

# Ensure directories exist
mkdir -p "$LOG_DIR"
chown -R proxy:proxy "$DATA_DIR"

# Ensure PID directory exists
mkdir -p /var/run/squid
chown proxy:proxy /var/run/squid

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

# Ensure whitelist is writable
chown proxy:proxy "$WHITELIST"
chmod 664 "$WHITELIST"

# Initialize squid cache directories
squid -z --foreground -f "$SQUID_CONF" 2>/dev/null || true

# Compute initial whitelist checksum
md5sum "$WHITELIST" > "$CHECKSUM_FILE" 2>/dev/null || echo "none" > "$CHECKSUM_FILE"

# Background: whitelist file watcher
(
    while true; do
        sleep 5
        NEW_SUM=$(md5sum "$WHITELIST" 2>/dev/null || echo "none")
        OLD_SUM=$(cat "$CHECKSUM_FILE" 2>/dev/null || echo "")
        if [ "$NEW_SUM" != "$OLD_SUM" ]; then
            echo "[whitelist-watcher] Whitelist changed, reconfiguring squid..."
            squid -k reconfigure -f "$SQUID_CONF" 2>/dev/null || true
            echo "$NEW_SUM" > "$CHECKSUM_FILE"
            echo "[whitelist-watcher] Squid reconfigured."
        fi
    done
) &

# Background: squid proxy
echo "[entrypoint] Starting squid proxy..."
squid --foreground -f "$SQUID_CONF" &
SQUID_PID=$!

# Wait for squid to be ready
for i in $(seq 1 30); do
    if bash -c 'echo > /dev/tcp/localhost/3128' 2>/dev/null; then
        echo "[entrypoint] Squid ready on port 3128."
        break
    fi
    sleep 1
done

# Foreground: Firewall Manager
echo "[entrypoint] Starting Firewall Manager on port 8080..."
cd /app
exec uvicorn main:app --host 0.0.0.0 --port 8080
