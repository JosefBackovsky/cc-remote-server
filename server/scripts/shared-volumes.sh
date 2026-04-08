#!/usr/bin/env bash
set -euo pipefail

USERNAME="${1:?Usage: shared-volumes.sh <username>}"

mkdir -p "/home/${USERNAME}/projects"
chown "${USERNAME}:${USERNAME}" "/home/${USERNAME}/projects"
