#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${1:?Usage: certbot.sh <domain> <azure-credentials-file> <email>}"
CREDENTIALS_FILE="${2:?Usage: certbot.sh <domain> <azure-credentials-file> <email>}"
EMAIL="${3:?Usage: certbot.sh <domain> <azure-credentials-file> <email>}"

# Idempotence — skip if certificate already exists
if [[ -d "/etc/letsencrypt/live/${DOMAIN}" ]]; then
  echo "Certificate for ${DOMAIN} already exists, skipping."
  exit 0
fi

# Validate credentials file
if [[ ! -f "$CREDENTIALS_FILE" ]]; then
  echo "ERROR: Azure credentials file not found: ${CREDENTIALS_FILE}" >&2
  exit 1
fi
chmod 600 "$CREDENTIALS_FILE"

# Prerequisites
apt-get update
apt-get install -y python3 python3-venv python3-pip libffi-dev

# Install certbot into venv (idempotent — pip handles existing packages)
python3 -m venv /opt/certbot
/opt/certbot/bin/pip install --upgrade pip
/opt/certbot/bin/pip install certbot certbot-dns-azure
# Workaround: azure-mgmt-dns 9.x is incompatible with certbot-dns-azure
/opt/certbot/bin/pip install azure-mgmt-dns==8.2.0

# Obtain certificate
/opt/certbot/bin/certbot certonly \
  --authenticator dns-azure \
  --dns-azure-credentials "$CREDENTIALS_FILE" \
  --dns-azure-propagation-seconds 120 \
  -d "$DOMAIN" \
  --non-interactive \
  --agree-tos \
  -m "$EMAIL"

# Auto-renewal cron (twice daily, Let's Encrypt recommendation)
cat > /etc/cron.d/certbot-renew <<'CRON'
0 3,15 * * * root /opt/certbot/bin/certbot renew --quiet
CRON

# Post-renewal hooks — restart containers to pick up new certificate
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/restart-tls-containers.sh <<'HOOK'
#!/usr/bin/env bash
# Restart containers that use TLS after certificate renewal
for name in portainer portal; do
  if docker ps --format '{{.Names}}' | grep -q "^${name}$"; then
    docker restart "$name"
  fi
done
HOOK
chmod +x /etc/letsencrypt/renewal-hooks/deploy/restart-tls-containers.sh
# Clean up old single-container hook if it exists
rm -f /etc/letsencrypt/renewal-hooks/deploy/restart-portainer.sh

echo "Certificate for ${DOMAIN} obtained successfully."
echo "Auto-renewal cron installed at /etc/cron.d/certbot-renew"
