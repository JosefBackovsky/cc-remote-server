#!/usr/bin/env bash
# shellcheck disable=SC1091  # /etc/os-release exists only on target Linux
set -euo pipefail

# Parametr: username, který se přidá do docker skupiny
DOCKER_USER="${1:?Usage: docker.sh <username>}"

# Idempotence — pokud Docker už je nainstalovaný, přeskočit
if command -v docker &>/dev/null; then
  echo "Docker already installed, skipping."
  exit 0
fi

# Detekce distro (ubuntu/debian)
DISTRO=$(. /etc/os-release && echo "$ID")
CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")

# Docker GPG + repo
install -m 0755 -d /etc/apt/keyrings
curl -fsSL "https://download.docker.com/linux/${DISTRO}/gpg" \
  -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${DISTRO} ${CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list

# Logging config — zapsat PŘED instalací, protože docker-ce postinst startuje Docker
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'DAEMON'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
DAEMON

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

usermod -aG docker "$DOCKER_USER"
systemctl enable docker
