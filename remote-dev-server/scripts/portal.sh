#!/usr/bin/env bash
set -euo pipefail

DOCKER_IMAGE="josefbackovsky/cc-remote-portal:latest"

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Deploy the Server Portal dashboard container from Docker Hub.

Image: $DOCKER_IMAGE

Options:
  --domain DOMAIN       Custom domain for links (e.g. cc-ts.backovsky.eu)
  --cert-dir DIR        Let's Encrypt cert directory (e.g. /etc/letsencrypt/live/cc-ts.backovsky.eu)
                        Enables HTTPS on port 443. Expects fullchain.pem and privkey.pem.
  --rebuild             Force pull new image and recreate container
  -h, --help            Show this help
EOF
  exit 0
}

DOMAIN=""
CERT_DIR=""
REBUILD=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      [[ -z "${2:-}" || "$2" == --* ]] && { echo "ERROR: --domain requires a value" >&2; exit 1; }
      DOMAIN="$2"; shift 2 ;;
    --cert-dir)
      [[ -z "${2:-}" || "$2" == --* ]] && { echo "ERROR: --cert-dir requires a value" >&2; exit 1; }
      CERT_DIR="$2"; shift 2 ;;
    --rebuild)
      REBUILD=true; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# Force rebuild — inherit config from existing container if not overridden
if [[ "$REBUILD" == true ]]; then
  if docker ps -a --format '{{.Names}}' | grep -q '^portal$'; then
    if [[ -z "$DOMAIN" ]]; then
      DOMAIN=$(docker inspect portal --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^PORTAL_DOMAIN=' | cut -d= -f2- || true)
    fi
    if [[ -z "$CERT_DIR" ]]; then
      CERT_FILE=$(docker inspect portal --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^SSL_CERTFILE=' | cut -d= -f2- || true)
      if [[ -n "$CERT_FILE" ]]; then
        CERT_DIR=$(dirname "$CERT_FILE")
      fi
    fi
    echo "Removing existing portal container..."
    docker stop portal 2>/dev/null || true
    docker rm portal 2>/dev/null || true
  fi
fi

# Idempotent — if container exists, ensure it's running
if docker ps -a --format '{{.Names}}' | grep -q '^portal$'; then
  if ! docker ps --format '{{.Names}}' | grep -q '^portal$'; then
    echo "Portal is stopped, starting..."
    docker start portal
  else
    echo "Portal already running."
  fi
  exit 0
fi

echo "Pulling portal image..."
docker pull "$DOCKER_IMAGE"
docker tag "$DOCKER_IMAGE" server-portal

# Build docker run command
RUN_ARGS=(
  -d --name portal --restart=always
  -v /var/run/docker.sock:/var/run/docker.sock:ro
)

# Tailscale binary (for hostname detection fallback)
if [[ -f /usr/bin/tailscale ]]; then
  RUN_ARGS+=(-v /usr/bin/tailscale:/usr/bin/tailscale:ro)
  RUN_ARGS+=(-v /var/run/tailscale:/var/run/tailscale:ro)
fi

# Domain override
if [[ -n "$DOMAIN" ]]; then
  RUN_ARGS+=(-e "PORTAL_DOMAIN=$DOMAIN")
fi

# HTTPS with Let's Encrypt
if [[ -n "$CERT_DIR" ]]; then
  if [[ ! -f "$CERT_DIR/fullchain.pem" || ! -f "$CERT_DIR/privkey.pem" ]]; then
    echo "ERROR: Certificate files not found in $CERT_DIR" >&2
    echo "Expected: fullchain.pem, privkey.pem" >&2
    exit 1
  fi
  # Mount entire /etc/letsencrypt (live/ contains symlinks to archive/)
  RUN_ARGS+=(-v /etc/letsencrypt:/etc/letsencrypt:ro)
  RUN_ARGS+=(-e "SSL_CERTFILE=${CERT_DIR}/fullchain.pem")
  RUN_ARGS+=(-e "SSL_KEYFILE=${CERT_DIR}/privkey.pem")
  RUN_ARGS+=(-p 443:8443)
  echo "Starting portal container (HTTPS)..."
else
  RUN_ARGS+=(-p 80:8080)
  echo "Starting portal container (HTTP)..."
fi

docker run "${RUN_ARGS[@]}" server-portal

if [[ -n "$DOMAIN" ]]; then
  if [[ -n "$CERT_DIR" ]]; then
    echo "Portal running at https://$DOMAIN"
  else
    echo "Portal running at http://$DOMAIN"
  fi
else
  echo "Portal running at http://$(hostname)"
fi
