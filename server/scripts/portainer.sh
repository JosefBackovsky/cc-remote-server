#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${1:-}"

# Helper: check if existing container has TLS configured
has_tls_mount() {
  docker inspect portainer --format '{{range .Mounts}}{{.Source}}{{end}}' 2>/dev/null | grep -q '/etc/letsencrypt'
}

# Determine desired TLS state
if [[ -n "$DOMAIN" ]]; then
  WANT_TLS=true
else
  WANT_TLS=false
fi

# Idempotent — if container exists, check for TLS mismatch
if docker ps -a --format '{{.Names}}' | grep -q '^portainer$'; then
  CURRENT_TLS=false
  if has_tls_mount; then
    CURRENT_TLS=true
  fi

  # TLS config changed — recreate container
  if [[ "$WANT_TLS" != "$CURRENT_TLS" ]]; then
    echo "Portainer TLS configuration changed, recreating container..."
    docker stop portainer
    docker rm portainer
  else
    # No change — just ensure it's running
    if ! docker ps --format '{{.Names}}' | grep -q '^portainer$'; then
      echo "Portainer is stopped, starting..."
      docker start portainer
    else
      echo "Portainer already running."
    fi
    exit 0
  fi
fi

docker volume create portainer_data

if [[ "$WANT_TLS" == "true" ]]; then
  docker run -d --name portainer --restart=always \
    -p 9443:9443 \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v portainer_data:/data \
    -v /etc/letsencrypt:/etc/letsencrypt:ro \
    portainer/portainer-ce:latest \
    --tlscert "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" \
    --tlskey "/etc/letsencrypt/live/${DOMAIN}/privkey.pem"
else
  docker run -d --name portainer --restart=always \
    -p 9443:9443 \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v portainer_data:/data \
    portainer/portainer-ce:latest
fi
