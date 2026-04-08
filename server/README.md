# server

Setup scripts for remote development host — Docker, Portainer, Portal dashboard, and optionally Tailscale + Let's Encrypt TLS. Supports both Azure VM (Terraform) and Debian home server.

## Architecture

```
MacBook (VS Code / PyCharm / browser)
│
│ Tailscale VPN / LAN
│
Dev Host (Azure VM or Debian server)
├── Docker Engine
├── Tailscale (optional on Debian)
├── Let's Encrypt certs (optional, via certbot + Azure DNS)
├── Portal (server dashboard, port 80/443)
├── Portainer (web UI, port 9443)
├── devcontainer per project (SSH ports 2222+)
├── Docker volumes (claude-shared, per-project)
└── ~/projects/
```

## Quick Start: Debian Home Server

```bash
# 1. Copy to server
scp -r scripts/ debian/ user@server:~/cc-remote-server/

# 2. SSH and install
ssh user@server
cd ~/cc-remote-server

# Minimal (Docker + Portainer + Portal)
./debian/install.sh

# With Tailscale
./debian/install.sh --tailscale KEY

# With Let's Encrypt TLS (requires Azure DNS for validation)
./debian/install.sh --tailscale KEY \
  --domain myhost.example.com \
  --azure-credentials /path/to/azure-dns-creds.ini \
  --certbot-email user@example.com

# All options
./debian/install.sh --help

# 3. Re-login (for Docker group), then verify:
docker run --rm hello-world
```

**Note:** If a local firewall (`ufw`, `nftables`) is running, open ports 80 (Portal), 443 (Portal HTTPS), and 9443 (Portainer).

## Quick Start: Azure VM

```bash
cd azure

# 1. Configure
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — set resource_group_name

# 2. Set Tailscale auth key
export TF_VAR_tailscale_auth_key=$(security find-generic-password -a "$USER" -s "tailscale-auth-key" -w)

# 3. Deploy
az login
terraform init
terraform plan
terraform apply

# 4. Wait ~3 minutes for cloud-init, then:
#    - Find Tailscale IP: https://login.tailscale.com/admin/machines
#    - Portainer: https://<tailscale_ip>:9443
#    - SSH: ssh devuser@devbox
```

## Project Structure

```
server/
├── scripts/                    # Shared setup scripts
│   ├── docker.sh               # Install Docker Engine (Ubuntu + Debian)
│   ├── tailscale.sh            # Install and configure Tailscale
│   ├── certbot.sh              # Let's Encrypt cert via Azure DNS challenge
│   ├── portainer.sh            # Run Portainer container (with optional TLS)
│   ├── portal.sh               # Deploy Portal from Docker Hub image
│   └── shared-volumes.sh      # Create claude-shared volume + ~/projects
├── azure/                      # Azure VM target (Terraform)
│   ├── main.tf
│   ├── variables.tf
│   ├── vm.tf
│   ├── outputs.tf
│   ├── cloud-init.tpl
│   └── terraform.tfvars.example
├── debian/                     # Debian server target
│   └── install.sh
└── README.md
```

## Shared Scripts

All scripts in `scripts/` are idempotent (safe to run multiple times), distro-agnostic (Ubuntu/Debian), and parameterized via arguments.

| Script | Purpose | Parameters |
|--------|---------|------------|
| `docker.sh` | Install Docker Engine + compose plugin | `<username>` |
| `tailscale.sh` | Install Tailscale + `tailscale up --ssh` | `<auth_key> [hostname]` |
| `certbot.sh` | Let's Encrypt cert via Azure DNS challenge | `<domain> <azure-credentials-file> <email>` |
| `portainer.sh` | Run Portainer CE container (TLS if domain given) | `[domain]` |
| `portal.sh` | Deploy Portal from Docker Hub image | `[--domain D] [--cert-dir DIR] [--rebuild]` |
| `shared-volumes.sh` | Create `claude-shared` volume + `~/projects` | `<username>` |

## Portal Dashboard

The Portal is a lightweight web dashboard (Python/FastAPI) that auto-discovers all running Docker containers and displays them grouped by Docker Compose project with clickable links.

**Features:**
- Auto-discovery via Docker socket — no manual configuration
- Groups services by Docker Compose project
- Status indicators (running/healthy/unhealthy/stopped)
- Clickable port links with correct hostname
- Auto-refresh every 10 seconds
- Optional HTTPS with Let's Encrypt certificates

**Source code:** [`services/portal/`](../services/portal) (built via GitHub Actions, pushed to Docker Hub)

**Deploy:**

```bash
# HTTP only
scripts/portal.sh

# With custom domain (used in generated links)
scripts/portal.sh --domain cc-ts.backovsky.eu

# With HTTPS (Let's Encrypt cert)
scripts/portal.sh --domain cc-ts.backovsky.eu \
  --cert-dir /etc/letsencrypt/live/cc-ts.backovsky.eu

# Pull new image from Docker Hub and recreate container
scripts/portal.sh --rebuild
```

**Hostname detection priority:** `PORTAL_DOMAIN` env var → Tailscale DNS name → system hostname.

## Let's Encrypt TLS

Optional TLS certificate via certbot with Azure DNS validation. Used by both Portainer and Portal.

```bash
# Obtain certificate
sudo scripts/certbot.sh myhost.example.com /path/to/azure-dns-creds.ini user@example.com

# Azure DNS credentials file format (INI):
# dns_azure_sp_client_id = ...
# dns_azure_sp_client_secret = ...
# dns_azure_tenant_id = ...
# dns_azure_environment = AzurePublicCloud
# dns_azure_zone1 = example.com:/subscriptions/.../resourceGroups/.../providers/Microsoft.Network/dnsZones/example.com
```

Auto-renewal runs via cron (twice daily). Post-renewal hook restarts Portainer to pick up the new cert.

## Azure Variables

| Variable | Default | Description |
|---|---|---|
| `resource_group_name` | *(required)* | Name of an existing Azure Resource Group |
| `tailscale_auth_key` | *(required)* | Tailscale auth key (sensitive) |
| `vm_name` | `"devbox"` | VM name in Azure and Tailscale hostname |
| `location` | `"westeurope"` | Azure region |
| `vm_size` | `"Standard_B4as_v2"` | VM size (4 vCPU, 16 GB RAM) |
| `os_disk_size_gb` | `128` | OS disk size in GB |
| `os_disk_type` | `"StandardSSD_LRS"` | Disk type (StandardSSD_LRS / Premium_LRS) |
| `admin_username` | `"devuser"` | VM admin username |
| `ssh_public_key` | `"~/.ssh/id_ed25519_devbox.pub"` | Path to SSH public key |
| `auto_shutdown_time` | `"2200"` | Auto-shutdown time (HHMM) |
| `auto_shutdown_timezone` | `"Central Europe Standard Time"` | Timezone for auto-shutdown |

## Azure Outputs

| Output | Description |
|---|---|
| `vm_id` | Azure resource ID of the VM |
| `vm_private_ip` | Private IP in Azure VNet (not the Tailscale IP) |
| `tailscale_note` | Instructions to find the Tailscale IP |
| `portainer_url` | Portainer web UI URL |
| `ssh_command` | SSH command using Tailscale hostname |

## Changing OS Disk

Disk size and type can be changed via `os_disk_size_gb` and `os_disk_type` variables without recreating the VM. Terraform will automatically deallocate the VM, update the disk, and start it again (same as Azure Portal).

```bash
# Example: switch to Premium SSD
# In terraform.tfvars: os_disk_type = "Premium_LRS"
terraform apply
```

## Cost Estimate

| Item | Cost |
|---|---|
| B4as_v2 compute (~242h/month) | ~€37/month |
| 128 GB Standard SSD (24/7) | ~€8/month |
| **Total** | **~€45/month** |

Assumes weekday usage 7:00–18:00 (~242h/month). Auto-shutdown at 22:00 as safety net.

## Debian Install Options

| Flag | Description |
|------|-------------|
| `--username USER` | User for Docker group and ~/projects (default: current user) |
| `--tailscale KEY` | Install Tailscale with the given auth key |
| `--tailscale-hostname H` | Tailscale hostname (default: `devbox`) |
| `--domain DOMAIN` | Domain for Let's Encrypt TLS certificate |
| `--azure-credentials FILE` | Path to Azure DNS credentials file (required with `--domain`) |
| `--certbot-email EMAIL` | Email for Let's Encrypt registration (required with `--domain`) |

When `--domain` is provided, the install script will:
1. Obtain a Let's Encrypt certificate via Azure DNS challenge
2. Start Portainer with TLS using the certificate
3. Start Portal with HTTPS and the domain in generated links

## Network Prerequisites

- Server must have internet access during installation
- If installation fails midway, re-run the install script — all scripts are idempotent
- For Debian: if `ufw` or `nftables` is active, ensure ports 80 (Portal), 443 (Portal HTTPS), and 9443 (Portainer) are open

## Cleanup

```bash
terraform destroy
```

This removes all Azure resources created by this configuration (VM, disk, NIC, NSG, VNet).
