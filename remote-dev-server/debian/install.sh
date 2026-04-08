#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install Docker, Portainer, and shared volumes on a Debian/Ubuntu server.

Options:
  --username USER         User for Docker group and ~/projects (default: current user)
  --tailscale KEY         Install Tailscale with the given auth key
  --tailscale-hostname H  Tailscale hostname (default: devbox)
  --domain DOMAIN         Domain for Let's Encrypt TLS certificate (e.g., myhost.example.com)
  --azure-credentials F   Path to Azure DNS credentials file (required with --domain)
  --certbot-email EMAIL   Email for Let's Encrypt registration (required with --domain)
  -h, --help              Show this help
EOF
  exit 0
}

# Defaults
USERNAME="$(whoami)"
TAILSCALE_AUTH_KEY=""
TAILSCALE_HOSTNAME="devbox"
DOMAIN=""
AZURE_CREDENTIALS=""
CERTBOT_EMAIL=""

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --username)
      [[ -z "${2:-}" || "$2" == --* ]] && { echo "ERROR: --username requires a value" >&2; exit 1; }
      USERNAME="$2"; shift 2 ;;
    --tailscale)
      [[ -z "${2:-}" || "$2" == --* ]] && { echo "ERROR: --tailscale requires a value" >&2; exit 1; }
      TAILSCALE_AUTH_KEY="$2"; shift 2 ;;
    --tailscale-hostname)
      [[ -z "${2:-}" || "$2" == --* ]] && { echo "ERROR: --tailscale-hostname requires a value" >&2; exit 1; }
      TAILSCALE_HOSTNAME="$2"; shift 2 ;;
    --domain)
      [[ -z "${2:-}" || "$2" == --* ]] && { echo "ERROR: --domain requires a value" >&2; exit 1; }
      DOMAIN="$2"; shift 2 ;;
    --azure-credentials)
      [[ -z "${2:-}" || "$2" == --* ]] && { echo "ERROR: --azure-credentials requires a value" >&2; exit 1; }
      AZURE_CREDENTIALS="$2"; shift 2 ;;
    --certbot-email)
      [[ -z "${2:-}" || "$2" == --* ]] && { echo "ERROR: --certbot-email requires a value" >&2; exit 1; }
      CERTBOT_EMAIL="$2"; shift 2 ;;
    -h|--help)            usage ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# Root/sudo check
if [[ $EUID -eq 0 ]]; then
  echo "ERROR: Do not run as root. Run as regular user (sudo will be used internally)." >&2
  exit 1
fi
if ! sudo -v 2>/dev/null; then
  echo "ERROR: This script requires sudo privileges." >&2
  exit 1
fi

# Validate certbot flag dependencies
if [[ -n "$DOMAIN" ]]; then
  MISSING=""
  [[ -z "$AZURE_CREDENTIALS" ]] && MISSING="${MISSING} --azure-credentials"
  [[ -z "$CERTBOT_EMAIL" ]] && MISSING="${MISSING} --certbot-email"
  if [[ -n "$MISSING" ]]; then
    echo "ERROR: --domain requires:${MISSING}" >&2
    exit 1
  fi
elif [[ -n "$AZURE_CREDENTIALS" || -n "$CERTBOT_EMAIL" ]]; then
  echo "WARNING: --azure-credentials and --certbot-email are ignored without --domain" >&2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="${SCRIPT_DIR}/../scripts"

echo "=== remote-dev-server: Debian install ==="
echo "User: ${USERNAME}"

# Prerequisity
echo "--- Installing prerequisites ---"
sudo apt-get update
sudo apt-get install -y curl ca-certificates gnupg git

# Docker
echo "--- Installing Docker ---"
sudo "${SCRIPTS_DIR}/docker.sh" "$USERNAME"

# Tailscale (only if --tailscale was provided)
if [[ -n "$TAILSCALE_AUTH_KEY" ]]; then
  echo "--- Installing Tailscale ---"
  sudo "${SCRIPTS_DIR}/tailscale.sh" "$TAILSCALE_AUTH_KEY" "$TAILSCALE_HOSTNAME"
else
  echo "--- Skipping Tailscale (use --tailscale KEY to install) ---"
fi

# Certbot (only if --domain was provided)
if [[ -n "$DOMAIN" ]]; then
  echo "--- Installing Certbot and obtaining certificate ---"
  sudo "${SCRIPTS_DIR}/certbot.sh" "$DOMAIN" "$AZURE_CREDENTIALS" "$CERTBOT_EMAIL"
else
  echo "--- Skipping Certbot (use --domain DOMAIN to install) ---"
fi

# Portainer
echo "--- Installing Portainer ---"
if [[ -n "$DOMAIN" ]]; then
  sudo "${SCRIPTS_DIR}/portainer.sh" "$DOMAIN"
else
  sudo "${SCRIPTS_DIR}/portainer.sh"
fi

# Shared volumes
echo "--- Creating shared volumes ---"
sudo "${SCRIPTS_DIR}/shared-volumes.sh" "$USERNAME"

# Portal (server dashboard)
echo "--- Installing Portal ---"
if [[ -n "$DOMAIN" ]]; then
  "${SCRIPTS_DIR}/portal.sh" --domain "$DOMAIN" --cert-dir "/etc/letsencrypt/live/${DOMAIN}"
else
  "${SCRIPTS_DIR}/portal.sh"
fi

echo ""
echo "=== Done! ==="
if [[ -n "$DOMAIN" ]]; then
  echo "Portal:    https://${DOMAIN}"
  echo "Portainer: https://${DOMAIN}:9443"
else
  echo "Portal:    http://$(hostname)"
  echo "Portainer: https://$(hostname):9443"
fi
echo ""
echo "IMPORTANT: Re-login or run 'newgrp docker' to use Docker without sudo."
