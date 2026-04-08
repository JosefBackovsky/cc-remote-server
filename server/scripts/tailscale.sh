#!/usr/bin/env bash
set -euo pipefail

AUTH_KEY="${1:?Usage: tailscale.sh <auth_key> [hostname]}"
HOSTNAME="${2:-devbox}"

# Idempotence — pokud Tailscale už běží, přeskočit
if command -v tailscale &>/dev/null && tailscale status &>/dev/null; then
  echo "Tailscale already installed and running, skipping."
  exit 0
fi

curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --auth-key="$AUTH_KEY" --ssh --hostname="$HOSTNAME"
