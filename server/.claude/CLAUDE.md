# server

## Co to je

Setup skripty pro remote development host. Podporuje dva targety:
- **Azure VM** — Terraform provisioning s cloud-init
- **Debian server** — přímá instalace přes shell skript

## Architektura

### Repo struktura

```
scripts/           sdílené skripty (Docker, Tailscale, Portainer, volumes)
  ↑                   ↑
  │                   │
azure/             debian/
cloud-init.tpl     install.sh
(embedduje         (volá skripty
 skripty přes       přímo z disku)
 write_files)
```

### Stav serveru s projekty

```
Dev Host (Azure VM nebo Debian server)
├── Docker Engine
├── Tailscale
├── Portainer (web UI, port 9443)
│
├── projekt-a (docker-compose)
│   ├── devcontainer (SSH :2222)
│   ├── postgres
│   └── redis
│
├── projekt-b (docker-compose)
│   ├── devcontainer (SSH :2223)
│   └── mongo
│
├── Docker volumes
│   ├── claude-shared             (sdílené credentials)
│   ├── projekt-a-claude-project
│   ├── projekt-a-commandhistory
│   ├── projekt-b-claude-project
│   ├── ...
│   └── portainer_data
│
└── ~/projects/
    ├── projekt-a-devcontainer/
    ├── projekt-a/
    ├── projekt-b-devcontainer/
    └── projekt-b/
```

Každý skript v `scripts/` je:
- **Idempotentní** — bezpečný pro opakované spuštění
- **Distro-agnostický** — detekuje Ubuntu/Debian přes `/etc/os-release`
- **Parametrizovaný** — konfigurace přes argumenty příkazové řádky

## Sdílené skripty

| Skript | Guard | Chování |
|--------|-------|---------|
| `docker.sh <user>` | `command -v docker` | Instalace Docker CE, daemon.json (před startem), user do docker group |
| `tailscale.sh <key> [hostname]` | `tailscale status` | Instalace + `tailscale up --ssh` |
| `portainer.sh [domain]` | `docker ps -a` + TLS mismatch | Nový kontejner (s/bez TLS), `docker start` pokud stopped, recreate při TLS změně |
| `certbot.sh <domain> <credentials> <email>` | `/etc/letsencrypt/live/$domain` | Certbot venv, cert via Azure DNS challenge, cron renewal, post-renewal hook |
| `portal.sh [--domain D] [--cert-dir DIR] [--rebuild]` | `docker ps -a` pro kontejner `portal` | Build + run Portal dashboard, HTTP nebo HTTPS |
| `shared-volumes.sh <user>` | Přirozeně idempotentní | `docker volume create claude-shared`, `mkdir -p ~/projects` |

## Azure target

Terraform soubory v `azure/`. `cloud-init.tpl` embeduje skripty přes `write_files` (Terraform `file()` + `indent()`).

Důležité:
- `vm.tf` má `lifecycle { ignore_changes = [custom_data] }` — změna skriptů nevynutí re-create VM
- Terraform `file()` čte skripty z `../scripts/` relativně k `azure/`

### Co Terraform vytvoří

1. **Virtual Network + Subnet** — izolovaná síť pro VM
2. **Network Security Group** — povolený jen Tailscale UDP 41641 inbound, vše ostatní deny
3. **Network Interface** — bez veřejné IP adresy
4. **Linux VM** (Standard_B4as_v2) — Ubuntu 24.04 LTS
5. **OS Disk** — 128 GB Standard SSD (Premium SSD volitelně)
6. **Auto-shutdown schedule** — deallocate VM ve 22:00

### Cloud-init provisioning

Při prvním startu VM cloud-init:
1. Nainstaluje prerequisity (curl, ca-certificates, gnupg, git)
2. Zapíše sdílené skripty do `/opt/setup/` přes `write_files`
3. Spustí skripty v pořadí: docker → tailscale → portainer → shared-volumes

### Denní workflow (Azure)

```bash
# Ráno — nastartujte VM (pokud byla auto-shutdown)
az vm start -g <resource_group> -n devbox

# VM naběhne, Tailscale se automaticky připojí, Portainer a kontejnery běží

# Večer — VM se vypne automaticky ve 22:00 (auto-shutdown)
# Nebo ručně:
az vm deallocate -g <resource_group> -n devbox
```

`deallocate` (ne `stop`) uvolní compute hardware a přestanete platit za CPU. Disk zůstává (~€8/měsíc za 128 GB Standard SSD). Data přežijí deallocate.

## Debian target

`debian/install.sh` orchestruje volání skriptů:
1. Kontrola: ne-root + sudo přístup
2. Prerequisity: `curl`, `ca-certificates`, `gnupg`, `git`
3. Docker (přeskočí pokud existuje)
4. Tailscale (volitelný, `--tailscale KEY`)
5. Certbot (volitelný, `--domain DOMAIN --azure-credentials FILE --certbot-email EMAIL`)
6. Portainer (s TLS pokud je `--domain`)
7. Shared volumes
8. Portal

Konfigurace přes CLI flags (`--username`, `--tailscale`, `--tailscale-hostname`, `--domain`, `--azure-credentials`, `--certbot-email`).

## Jak se připojit

### VS Code (přes Docker socket)

1. Remote-SSH → `<user>@<tailscale_ip_nebo_hostname>`
2. SSH session na hostu (port 22)
3. Otevřete projekt → "Reopen in Container" → VS Code přes `docker exec` spustí server uvnitř kontejneru
4. Víc VS Code oken = víc SSH sessions přes stejný port 22

### PyCharm / JetBrains (přes SSH port do kontejneru)

JetBrains IDE neumí Dev Containers. Používá SSH Remote Interpreter přímo do kontejneru:
- Host: `<tailscale_ip>`, Port: 2222 (nebo 2223, 2224...), User: `node`
- Každý kontejner má unikátní SSH port

### Portainer (prohlížeč)

- `https://<hostname>:9443`
- Start/stop kontejnerů, logy, resource monitoring

### Terminál

- SSH na host → `docker exec -it <kontejner> bash`

## Bezpečnost

- **Azure:** žádná veřejná IP — přístup výhradně přes Tailscale VPN
- NSG povoluje jen Tailscale UDP port 41641 (přímé P2P spojení)
- **Debian:** přístup přes LAN nebo Tailscale
- Tailscale SSH umožňuje přístup bez správy SSH klíčů (`tailscale up --ssh`)
- Portainer přístupný jen z Tailscale sítě / LAN
- Let's Encrypt certifikáty (volitelné) — validní TLS pro Portainer, auto-renewal přes cron
- Azure DNS credentials (pro certbot) — permissions 600
- VM/server uživatel je v `docker` skupině, ne root
- Sensitive data nikdy v gitu (terraform.tfvars v .gitignore)

## Konvence

- Bash skripty: `set -euo pipefail`, `shellcheck` clean
- Terraform: >= 1.5, AzureRM >= 3.0, flat struktura v `azure/`
- Sensitive data: nikdy v gitu (terraform.tfvars v .gitignore)
- Commit messages: conventional commits (feat/fix/docs)
