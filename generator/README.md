# DevContainer Generator

CLI tool for generating separate devcontainer repositories with pre-installed Claude Code.

Based on [claude-devcontainer-generator](https://github.com/keeema/claude-devcontainer-generator) by [@keeema](https://github.com/keeema).

## Why?

Development environment definitions don't belong in the project repo:
- Dev environments (`.devcontainer/`, `.claude/`) shouldn't be versioned in the project
- Each developer or team may have a different setup
- The project repo stays clean — no IDE/tooling files
- Easy reproducibility on another machine

Solution: generate a **separate devcontainer repo** that lives alongside the project repo. The project stays clean — no `.devcontainer/`, no `.claude/`.

## Prerequisites

- Node.js 20+
- Docker Desktop (or Docker Engine)
- VS Code with the [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) extension

## Quick Start

### 1. Install dependencies

```bash
npm install
```

### 2. Generate devcontainer

```bash
node src/cli.js \
  --repo git@github.com:company/myproject.git \
  --stack nodejs \
  --services postgres \
  --output ~/projects/myproject-devcontainer
```

### 3. Open in VS Code

```bash
cd ~/projects/myproject-devcontainer
code .
```

VS Code detects `.devcontainer/` and offers **"Reopen in Container"** (or via Command Palette → `Dev Containers: Reopen in Container`).

On first run, it automatically:
1. Clones the project repo next to the devcontainer
2. Creates the shared Docker volume `claude-credentials` (if it doesn't exist)
3. Builds the Docker image with dev tools and Claude Code
4. Starts the container and launches Claude Code in a tmux session

### 4. Connect to Claude Code

Claude Code runs automatically in a tmux session inside the container. Open a terminal in VS Code and connect:

```bash
tmux attach -t claude
```

On first run, Claude will wait for OAuth login. After login, credentials are saved to the shared volume and Claude starts automatically next time.

> **Tip:** The devcontainer also includes the VS Code extension `anthropic.claude-code`, so you can use Claude Code directly in VS Code.

### 5. Disconnect

```bash
# Ctrl+B, then D — detaches from tmux, Claude keeps working
```

You can close VS Code and Claude keeps working. Next time, just reconnect via `tmux attach -t claude`.

## How It Works

### Single-repo

```
~/projects/
  ├── myproject-devcontainer/     ← generated devcontainer repo
  │   ├── .devcontainer/
  │   │   ├── devcontainer.json   ← VS Code config, extensions, env
  │   │   ├── docker-compose.yml  ← app + services, volumes, networking
  │   │   ├── Dockerfile          ← base image, tools, Claude Code
  │   │   ├── init-firewall.sh    ← iptables whitelist (unless --full-internet)
  │   │   └── init.sh             ← clones project repo if not present
  │   └── project.yml             ← project metadata (repo URL, branch)
  └── myproject/                  ← project repo (cloned automatically)
```

### Multi-repo

```
~/projects/
  ├── myproject-devcontainer/     ← generated devcontainer repo
  │   ├── .devcontainer/
  │   │   └── ...
  │   └── project.yml             ← project metadata (list of repos)
  └── myproject/                  ← workspace directory
      ├── backend/                ← first repo (cloned automatically)
      └── frontend/               ← second repo (cloned automatically)
```

Each repo is mounted as `/workspace/<repoName>/` inside the container.

### Three data layers

| Volume | Mount | Purpose | Sharing |
|--------|-------|---------|---------|
| `claude-credentials` | `/home/node/.claude` | OAuth tokens, global settings | Across all projects |
| `<name>-claude-project` | `/workspace/.claude` | CLAUDE.md, project settings | Per project |
| `<name>-commandhistory` | `/commandhistory` | Bash/zsh history | Per project |
| Bind mount | `/workspace` | Project source code | — |

All volumes survive container rebuilds. `claude-credentials` is created automatically on first run.

## CLI Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--repo` | yes | — | Git repo URL (repeatable, see [Multi-repo](#multi-repo)). Per-repo branch: `--repo url#branch` |
| `--output` | yes | — | Target directory for the generated devcontainer |
| `--name` | no | from repo URL | Project name (auto-derived from URL). Required for multi-repo |
| `--branch` | no | `main` | Git branch (global default, per-repo `#branch` takes precedence) |
| `--stack` | no | `nodejs` | SDK/runtime (`nodejs`, `python`, `dotnet`) |
| `--services` | no | — | Comma-separated services (`postgres`, `redis`, `mongo`, `azurite`) |
| `--full-internet` | no | `false` | Disable firewall — full internet access |
| `--include-compose` | no | `false` | Include project's `docker-compose.yml` via Docker Compose `include` (single-repo only) |
| `--local-claude` | no | `false` | Mount `.claude` from devcontainer repo instead of Docker volume |
| `--ssh-port` | no | `2222` | SSH port for JetBrains IDE access (PyCharm Gateway etc.) |
| `--port-prefix` | no | — | Port prefix (e.g. `82` → SSH `8222`, firewall `8280`). Takes precedence over `--ssh-port` |

## Stacks (SDK/runtime)

| Stack | Base image | Description |
|-------|-----------|-------------|
| `nodejs` | `node:22` | Node.js LTS |
| `python` | `python:3.12` | Python 3.12 |
| `dotnet` | `mcr.microsoft.com/dotnet/sdk:9.0` | .NET 9 |

Each stack automatically installs Claude Code (requires Node.js — for non-Node stacks it's installed automatically).

## Services

Any combination via `--services postgres,redis,mongo,azurite`:

| Service | Image | Port |
|---------|-------|------|
| `postgres` | `postgres:17` | 5432 |
| `mongo` | `mongo:7` | 27017 |
| `redis` | `redis:7` | 6379 |
| `azurite` | Azure Storage Emulator | 10000-10002 |

## Examples

### Node.js project with PostgreSQL and Redis

```bash
node src/cli.js \
  --repo git@github.com:company/eshop.git \
  --stack nodejs \
  --services postgres,redis \
  --output ~/projects/eshop-devcontainer
```

### .NET project with full internet and project docker-compose

```bash
node src/cli.js \
  --repo git@github.com:company/erp.git \
  --stack dotnet \
  --full-internet \
  --include-compose \
  --output ~/projects/erp-devcontainer
```

### Python project without services

```bash
node src/cli.js \
  --repo git@github.com:company/ml-pipeline.git \
  --stack python \
  --output ~/projects/ml-pipeline-devcontainer
```

### Multi-repo project with port prefix

```bash
node src/cli.js \
  --repo https://github.com/company/backend.git \
  --repo https://github.com/company/frontend.git#develop \
  --name myproject \
  --stack python \
  --services postgres \
  --port-prefix 82 \
  --output ~/projects/myproject-devcontainer
```

## Multi-repo

The generator supports multiple repositories in a single devcontainer — repeat `--repo`:

```bash
node src/cli.js \
  --repo https://github.com/company/backend.git \
  --repo https://github.com/company/frontend.git#develop \
  --name myproject \
  --stack nodejs \
  --output ~/projects/myproject-devcontainer
```

- `--name` is **required** with multiple repos (cannot be derived from URL)
- Per-repo branch is specified via `#branch` suffix (e.g. `url#develop`), otherwise the global `--branch` is used
- Each repo must have a unique name (basename from URL)
- Workspace layout: `/workspace/backend/`, `/workspace/frontend/`
- `--include-compose` in multi-repo mode doesn't auto-include — a warning with compose file paths is printed after generation

## Port prefix

Useful for projects running on a remote server to keep ports in a specific range:

```bash
--port-prefix 82   # → SSH 8222:22, firewall 8280:8080
--port-prefix 83   # → SSH 8322:22, firewall 8380:8080
```

Without `--port-prefix`, defaults are used (SSH `2222`, firewall `8180`). `--port-prefix` takes precedence over `--ssh-port`.

## Firewall

By default, the container only allows:
- **Claude API** — `api.anthropic.com`, `statsig.anthropic.com`, `sentry.io`
- **Git** — `github.com`, `gitlab.com`
- **Package managers** — npm, yarn, pip, nuget
- **DNS and SSH**

Everything else is blocked via iptables (the container has `NET_ADMIN` capability). For full internet access use `--full-internet` — no firewall is created.

### Blocking git push for Claude Code

If you want to prevent Claude Code from pushing to the remote repository (e.g. with `--dangerously-skip-permissions`), remove git remote domains from `init-firewall.sh`. Claude runs as unprivileged user `node` without sudo access to iptables — the firewall cannot be bypassed.

```bash
# In init-firewall.sh, remove/comment out git remote domains:
# dev.azure.com
# ssh.dev.azure.com
# github.com  (if that's your remote)
```

Claude can still commit and create branches — the workspace is a bind mount from the host. You push from the host machine:

```bash
# On the host (outside the container)
cd ~/projects/myproject
git log     # see commits made by Claude
git push    # you push
```

> **Note:** Without access to the git remote, Claude can't `git pull`/`git fetch` either. Do `git pull` on the host before starting a session.

## Port access (VS Code Remote + Docker Compose)

When working via VS Code Remote SSH + Dev Containers, there are **two types of ports** with different access methods:

### Ports inside the devcontainer (VS Code forwardPorts)

Ports of applications **running inside the devcontainer** (your backend, frontend, etc.). VS Code can forward these automatically via `forwardPorts` in `devcontainer.json`:

```json
"forwardPorts": [8001, 8002, 4321],
"portsAttributes": {
  "8001": { "label": "backend", "onAutoForward": "silent" }
}
```

→ Access via **localhost:8001** in VS Code.

### Sibling container ports (direct network access)

Ports of other Docker Compose services (databases, Langfuse, Squid, approval-app, etc.) are mapped on the **Docker host**, not inside the devcontainer. VS Code `forwardPorts` **does not work** for these.

Access depends on network configuration:

- **Tailscale / LAN:** `http://<hostname>:<port>` directly from the browser
- **SSH tunnel:** `ssh -L <port>:localhost:<port> <host>` → `localhost:<port>`
- **Portainer:** web UI for container management at `https://<hostname>:9443`

Example — wiki-chatbot on Tailscale:

| Service | Port | Access |
|---------|------|--------|
| Langfuse web | 8100 | `http://<tailscale-hostname>:8100` |
| PostgreSQL | 8132 | `<tailscale-hostname>:8132` |
| Proxy approval | 8180 | `http://<tailscale-hostname>:8180` |
| Portainer | 9443 | `https://<tailscale-hostname>:9443` |

> **Rule:** Only add ports that **run inside the devcontainer** to `forwardPorts`. Don't add sibling service ports — they won't work.

## Working with Claude Code

### Tmux session

Claude Code starts automatically in a tmux session when the container starts:

```bash
# Connect
tmux attach -t claude

# Disconnect (Claude keeps working)
Ctrl+B, then D

# From another machine via SSH
docker exec -it <container> bash
tmux attach -t claude
```

### Typical workflow

1. **Morning:** VS Code → "Reopen in Container" → terminal → `tmux attach -t claude`
2. **During the day:** assign tasks, watch output
3. **Leaving:** `Ctrl+B, D` — Claude keeps working, you can close VS Code
4. **From phone:** SSH to host → `docker exec -it <container> bash` → `tmux attach -t claude`
5. **Next day:** VS Code again → `tmux attach -t claude` → Claude is done

### Project instructions (CLAUDE.md)

Volume `<name>-claude-project` is mounted at `/workspace/.claude`. Create a `CLAUDE.md` with project instructions:

```bash
# Inside the container
echo "# Project instructions" > /workspace/.claude/CLAUDE.md
```

The file survives container rebuilds and the project repo stays clean (the volume overlays the directory).

## Development

```bash
npm install
npm test
```
