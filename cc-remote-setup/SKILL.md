---
name: cc-remote-setup
description: >
  Use this skill whenever a user wants to set up remote development for a project using
  the cc-remote platform. Trigger when the user mentions devcontainer setup, adding a project
  to the cc-remote server, configuring remote development, or asks how to run a project
  with Claude Code on a remote server. Also trigger when the user has cloned repos into
  a project directory and wants to know how to develop them remotely. Use this skill even
  if the user just asks "how do I add this project to cc-remote" or "chci devcontainer
  pro tento projekt" — don't wait for explicit invocation.
---

# CC-Remote: New Project Setup

## What is cc-remote

A platform for running multiple isolated Claude Code sandboxes on a remote server. Each project gets its own devcontainer stack with:

- **Claude Code** running autonomously in a persistent tmux session
- **Firewall** (Squid proxy + Firewall Manager) restricting Claude's internet access to an approved domain whitelist
- **Project services** (postgres, redis, etc.) co-located in the same compose stack
- **SSH access** so the developer can connect from VS Code, JetBrains, or terminal

The developer doesn't sit next to Claude — they connect remotely, observe what Claude is doing via tmux, and review changes before pushing.

```
┌─────────────────────────────────────────────────────────┐
│  Remote Dev Server (cc-ts)                              │
│                                                         │
│  Portal :80   Portainer :9443   Tailscale VPN           │
│ ─────────────────────────────────────────────────────── │
│  Project A                   Project B                  │
│  ┌──────────────┐            ┌──────────────┐           │
│  │ devcontainer │            │ devcontainer │           │
│  │ Claude Code  │            │ Claude Code  │           │
│  │ SSH :8122    │            │ SSH :8222    │           │
│  ├──────────────┤            ├──────────────┤           │
│  │ firewall     │            │ firewall     │           │
│  │ :8180        │            │ :8280        │           │
│  ├──────────────┤            └──────────────┘           │
│  │ postgres     │                                       │
│  └──────────────┘                                       │
└─────────────────────────────────────────────────────────┘
```

## Key Concepts

### Portal
Auto-discovery dashboard running on the server at `http://<server-hostname>`. Shows all running containers across all projects with their ports and status. No manual configuration — just run `docker compose up -d` and the project appears automatically.
See: [cc-remote-services](https://github.com/JosefBackovsky/cc-remote-services)

### Firewall
Each devcontainer has its own `firewall` service (combined Squid proxy + Firewall Manager) deployed as part of the project's docker-compose stack. It:
- Routes all HTTP/HTTPS traffic from Claude through a domain whitelist
- Blocks direct internet access via iptables (proxy-mode)
- Provides a web dashboard (`http://<server-hostname>:8N80`) where the developer approves/denies domain requests
- When Claude hits a blocked domain, it receives instructions to submit a domain request via API — the developer approves it, and Claude retries

The generated devcontainer includes a `CLAUDE.md` explaining this workflow to Claude Code.

### tmux — Persistent Claude Code session
Claude Code starts automatically in a tmux session when the container starts. The developer can:
- Connect at any time: `tmux attach -t claude`
- Detach without stopping Claude: `Ctrl+B, D`
- Reconnect from a different machine (phone SSH, different computer)

### Git credentials — read-only for Claude, push via developer
Claude uses a **read-only PAT** stored in `~/.git-credentials` in the container for git pull operations. This prevents Claude from pushing without human review. The developer reviews Claude's changes and **pushes via VS Code** (using their own credentials) or from the host.

### claude-shared volume
A single Docker volume `claude-shared` is mounted at `/home/node/.claude` across all projects on the server. It stores Claude Code OAuth tokens and global settings — so Claude is already authenticated in every new devcontainer.

---

## Tools

| Tool | Repo | Purpose |
|------|------|---------|
| **claude-devcontainer-generator** | [github.com/JosefBackovsky/claude-devcontainer-generator](https://github.com/JosefBackovsky/claude-devcontainer-generator) | CLI that generates a ready-to-use devcontainer repo |
| **cc-remote-services** | [github.com/JosefBackovsky/cc-remote-services](https://github.com/JosefBackovsky/cc-remote-services) | Pre-built Docker images: portal, firewall |
| **remote-dev-server** | [github.com/JosefBackovsky/remote-dev-server](https://github.com/JosefBackovsky/remote-dev-server) | Server setup scripts |

Read each repo's README for up-to-date options. The READMEs are the authoritative reference — this skill covers the workflow.

---

## Prerequisites (one-time per server)

Before adding the first project, the server needs:
1. **Server setup** — follow [remote-dev-server](https://github.com/JosefBackovsky/remote-dev-server) README (Docker, Tailscale, Portal, Portainer)
2. **claude-shared volume** — `docker volume create claude-shared`
3. **SSH access** — server reachable via Tailscale as `cc-ts`
4. **Projects directory** — `~/projects/` on the server (e.g. `/home/josefbackovsky/projects/`)

---

## Phase 1: Explore the Project

Before proposing anything, read the project directory:
- How many repos? (monorepo / separate FE + BE / other)
- What tech stacks? (Node.js, Python, .NET, mixed)
- Does any repo have its own `docker-compose.yml` with services (DB, cache...)? **If yes, use `--include-compose` flag** — the generator will `include` it via Docker Compose, so those services run alongside the devcontainer without duplicating configuration.
- How coupled are the repos? (always develop together / independently)

---

## Phase 2: Propose Devcontainer Architecture

The generator supports **multiple repos** and **multiple stacks** in a single devcontainer. This is the preferred approach for tightly coupled projects.

**One devcontainer with multi-repo** — the default for most projects.
- Tightly coupled FE + BE, monorepo, or related microservices
- Use `--repo` multiple times to include all repos
- Use `--stack` multiple times if repos use different runtimes (e.g. `--stack python --stack nodejs`)
- First `--stack` determines the base Docker image, additional stacks install their tools on top
- Each repo is mounted as `/workspace/<repoName>/`

**Multiple devcontainers** — only when repos genuinely need full isolation.
- Fundamentally incompatible environments
- Independent deployment cycles or teams
- Different secrets or security requirements

When uncertain, propose one devcontainer with multiple repos. It's easier to split later than to merge.

Present your proposal with reasoning. Wait for user confirmation.

---

## Phase 3: Choose Port Range

Each project uses its own port range (81xx, 82xx, 83xx...) to avoid collisions. Ask the user which range to use.

The generator supports `--port-prefix` which automatically derives all ports from the prefix:

| Port | Purpose |
|------|---------|
| `8N22` | SSH into devcontainer |
| `8N80` | Firewall Manager dashboard |
| `8N01`–`8N19` | App ports (API, dev servers, etc.) |
| `8N32` | Database (if exposed to host) |

Example: `--port-prefix 82` → SSH=8222, Firewall=8280.

---

## Phase 4: Generate the Devcontainer(s)

Clone the generator repo if not available locally (`git clone git@github.com:JosefBackovsky/claude-devcontainer-generator.git`). Then run `npm install`.

### Single-repo example

```bash
cd <path-to-claude-devcontainer-generator>

node src/cli.js \
  --repo git@github.com:<org>/<repo>.git \
  --stack <stack> \
  --services <services> \
  --port-prefix <8N> \
  --output <destination>/devcontainer
```

### Multi-repo example

```bash
node src/cli.js \
  --repo https://github.com/<org>/<backend>.git \
  --repo https://github.com/<org>/<frontend>.git \
  --name <project-name> \
  --stack python \
  --stack nodejs \
  --services postgres \
  --port-prefix <8N> \
  --output <destination>/devcontainer
```

### CLI reference

| Flag | Repeatable | Default | When to use |
|------|-----------|---------|-------------|
| `--repo <url>` | yes | — | Git URL. Repeat for multi-repo. Use `url#branch` for per-repo branch. |
| `--name <name>` | no | from URL | Project name. **Required** when multiple repos. |
| `--stack <stack>` | yes | `nodejs` | Runtime: `nodejs`, `python`, `dotnet`. Repeat for mixed stacks (first = base image). |
| `--services <list>` | no | — | Comma-separated: `postgres`, `mongo`, `redis`, `azurite`. |
| `--port-prefix <NN>` | no | — | Port prefix (e.g. `82` → SSH `8222`, firewall `8280`). Preferred over `--ssh-port`. |
| `--ssh-port <port>` | no | `2222` | SSH port. Overridden by `--port-prefix`. |
| `--branch <name>` | no | `main` | Default branch for all repos. Per-repo `#branch` overrides. |
| `--full-internet` | no | `false` | Disable firewall. Only for fully trusted environments. |
| `--include-compose` | no | `false` | Include project's `docker-compose.yml` via compose `include`. |
| `--local-claude` | no | `false` | Mount `.project-claude/` for per-project `CLAUDE.md` in the devcontainer repo. |

**Stacks:** `nodejs` (Node 22) · `python` (Python 3.12) · `dotnet` (.NET 9)

**Services:** `postgres` (17) · `mongo` (7) · `redis` (7) · `azurite`

After generation, review `docker-compose.yml` (ports, volumes, services) and `Dockerfile` (base image).

---

## Phase 4b: Customize After Generation

The generator produces a generic devcontainer. Most projects need customization before deployment:

### Dockerfile — system dependencies

If the project needs system libraries beyond what the base stack provides (e.g. native extensions, OCR engines, PDF tools), add them to the `apt-get install` block in `.devcontainer/Dockerfile`. Check the project's production Dockerfile for required packages.

### docker-compose.yml — services

The generator creates generic service definitions. Review and adjust:
- **Database images** — replace generic `postgres:17` with project-specific images (e.g. pgvector, PostGIS) if needed
- **Credentials** — match the project's expected DB user/password/database names
- **Healthchecks** — add if the project depends on service readiness
- **Langfuse** — if adding Langfuse stack, set `NEXTAUTH_URL` to `http://<server-hostname>:<port>` (not `localhost`) — the developer accesses the dashboard remotely via the server hostname

### VS Code workspace file

For multi-repo projects, create a `.code-workspace` file in `.devcontainer/` with recommended extensions:

```json
{
  "folders": [
    { "path": "/workspace/<repo1>", "name": "<display-name-1>" },
    { "path": "/workspace/<repo2>", "name": "<display-name-2>" }
  ],
  "settings": {},
  "extensions": {
    "recommendations": [
      "ms-python.python",
      "ms-python.debugpy"
    ]
  }
}
```

**Mount the entire devcontainer repo** as a directory, then symlink the workspace file in the container's startup command:

```yaml
# In docker-compose.yml volumes:
- ..:/workspace/.devcontainer-repo:cached

# In docker-compose.yml command (before other commands):
ln -sf /workspace/.devcontainer-repo/.devcontainer/<name>.code-workspace /workspace/<name>.code-workspace
```

**NEVER bind-mount a single file** (e.g. `./file.json:/workspace/file.json`). When `git pull` updates the file on the host, it creates a new inode — but the bind mount still points to the old inode, so the container sees stale content. Always mount the parent directory instead.

### /workspace ownership

The generated Dockerfile sets `WORKDIR /workspace` but the directory is owned by root. Add `chown` before switching to the node user:

```dockerfile
WORKDIR /workspace
RUN chown node:node /workspace
USER node
```

Without this, VS Code and other tools cannot create files in `/workspace/`.

### Persistent git credentials inside devcontainer

Git credentials stored in the container filesystem are lost on recreate. The generator uses **auto-seeding from env var** + **named volume** for persistence:

1. The generator creates a named volume `<project>-persistent:/home/node/.persistent` and configures `credential.helper` in the Dockerfile.

2. The devcontainer startup command auto-seeds credentials from `GIT_CREDENTIALS_READONLY` env var:
```yaml
# In devcontainer command (generated automatically):
([ -n "$$GIT_CREDENTIALS_READONLY" ] && echo "$$GIT_CREDENTIALS_READONLY" > /home/node/.persistent/.git-credentials || true)
```

3. Set the credential line in `.env` on the server:
```bash
cd ~/projects/<project>-devcontainer/.devcontainer
echo 'GIT_CREDENTIALS_READONLY=https://<user>:<read-only-PAT>@<git-host>' >> .env
docker compose up -d --force-recreate devcontainer
```

Credentials are re-seeded on every container start — survives `docker compose down -v`.

**Important:** `git credential-store` erases credentials after auth failure (e.g. proxy 403). The auto-seeding (without `[ ! -s ]` guard) ensures credentials are restored on next container restart.

### Ungit write credentials via Docker Compose secrets

Ungit needs a **write PAT** for push operations. This PAT must be **isolated from Claude** (who must not be able to push). The generator uses **Docker Compose file-based secrets**:

1. The secret is stored on the host in a per-project directory:
```bash
mkdir -p ~/.secrets/<project> && chmod 700 ~/.secrets/<project>
echo "https://<user>:<write-PAT>@<git-host>" > ~/.secrets/<project>/git-credentials-write
chmod 600 ~/.secrets/<project>/git-credentials-write
```

2. The generator adds a `secrets:` declaration to docker-compose.yml — the secret is only mounted into the ungit container at `/run/secrets/git-credentials-write`. The devcontainer **never** declares this secret and has no access.

3. The ungit startup command copies the secret to the credential store with validation:
```yaml
# Generated automatically:
secrets:
  git-credentials-write:
    file: ${HOME}/.secrets/<project>/git-credentials-write
```

**Security model:**
- Claude (devcontainer) cannot access `/run/secrets/git-credentials-write` — not declared
- Claude cannot read `.env` write token — it's not there (only `GIT_CREDENTIALS_READONLY`)
- Claude cannot `docker exec` into ungit — no Docker socket access
- If secret file is missing on host, `docker compose up` fails fast (by design)

**Multi-project isolation:** Each project uses `~/.secrets/<project>/` — Docker Compose secrets are per-stack, so projects cannot see each other's secrets.

### Python interpreter — `python:*` base images

Docker `python:X.Y` images install Python X.Y at `/usr/local/bin/python3`, but the underlying Debian may also have a **different** system Python at `/usr/bin/python3`. VS Code auto-discovers both and often picks the wrong one (system Python with no packages).

Fix: explicitly set the interpreter path in `devcontainer.json` and workspace file:

```json
// In devcontainer.json customizations.vscode.settings:
"python.defaultInterpreterPath": "/usr/local/bin/python3"

// In .code-workspace settings:
"python.defaultInterpreterPath": "/usr/local/bin/python3"
```

Do NOT "fix" this by removing the system Python (`apt remove python3`) — it breaks Debian packages.

### Git push isolation — Ungit web GUI

Claude in the devcontainer should only have a **read-only PAT** (can pull, cannot push). The developer pushes via **Ungit**, a web-based git GUI running in a separate container. Separate container = hard credential isolation — Claude cannot access Ungit's filesystem.

Add an `ungit` service to `docker-compose.yml`:

```yaml
ungit:
  image: node:22-slim
  working_dir: /workspace
  volumes:
    - ../../<project>/<repo1>:/workspace/<repo1>:cached
    - ../../<project>/<repo2>:/workspace/<repo2>:cached
    - <project>-ungit-data:/home/node/.ungit-config
  ports:
    - "8N04:8448"
  command: >
    bash -c "apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/* && npm install -g ungit && echo '{\"port\": 8448, \"ungitBindIp\": \"0.0.0.0\", \"autoFetch\": false, \"defaultRepositories\": [\"/workspace/<repo1>\", \"/workspace/<repo2>\"]}' > /home/node/.ungitrc && git config --global credential.helper 'store --file /home/node/.ungit-config/.git-credentials' && su node -c ungit"
  restart: always
```

Key points:
- **Same bind mounts** as devcontainer — both see the same files
- **Separate credentials** — write PAT stored in `<project>-ungit-data` named volume, inaccessible from devcontainer
- **Port `8N04`** — follows port prefix pattern (e.g. `8104` for prefix `81`)
- **`ca-certificates`** required — `node:22-slim` has no CA certs, HTTPS will fail without them
- **`autoFetch: false`** — prevents background fetches that could conflict with Claude's git operations
- **No authentication** on Ungit web UI — access restricted to Tailscale VPN
- **First push** — Ungit prompts for credentials (username + PAT as password), `credential-store` saves them automatically

Also add the volume to the top-level `volumes:` section:
```yaml
<project>-ungit-data:
```

**IMPORTANT:** The devcontainer MUST NOT mount `/var/run/docker.sock`. If it did, Claude could `docker exec` into the ungit container and read the write PAT.

### Credentials and secrets

**Never commit secrets to the devcontainer repo.** Credentials are configured on the server after deployment:

1. **`.env` file** — create on the server next to `docker-compose.yml`, reference in compose via `env_file:` or variable substitution (`${VAR}`)
2. **git credentials (Claude)** — read-only PAT persisted in named volume (see Persistent git credentials above)
3. **git credentials (developer push)** — write PAT provisioned on first push via Ungit web UI (see Git push isolation above)
4. **API keys** (LLM providers, external services) — pass via `.env` or `environment:` in compose with `${VAR}` substitution

---

## Phase 5: Push to GitHub and Deploy

**1. Create GitHub repo and push:**
```bash
cd <project>/devcontainer
git init && git add .
git commit -m "feat: initial devcontainer setup"
git remote add origin git@github.com:<org>/<project>-devcontainer.git
git push -u origin main
```

**2. Clone and start on the server:**

IMPORTANT: `initializeCommand` from `devcontainer.json` only runs via VS Code "Reopen in Container", NOT via `docker compose up -d`. On the server you must run `init.sh` manually first to clone the project repos.

```bash
ssh cc-ts
cd ~/projects
git clone git@github.com:<org>/<project>-devcontainer.git
cd <project>-devcontainer

# Clone project repos (init.sh does NOT run automatically with docker compose)
.devcontainer/init.sh

# Start containers — MUST be AFTER init.sh
cd .devcontainer
docker compose up -d
```

**ORDER MATTERS:** Repos must be cloned (init.sh) BEFORE `docker compose up -d`. If docker compose runs first, Docker creates empty directories for bind mounts. When init.sh later clones repos, the bind mounts still point to the old empty inodes — the container sees empty `/workspace/<repo>/` even though the host has content. Fix: `docker compose up -d --force-recreate devcontainer`.

**3. Verify:**
```bash
docker compose ps                              # all services healthy?
docker compose logs firewall --tail=20         # squid + firewall manager up?
docker compose logs devcontainer --tail=20     # Claude Code starting in tmux?
```

---

## Phase 6: Verify Access and Configure

### 6.1 Verify connectivity

- **Connect to Claude Code:** `ssh -p 8N22 node@cc-ts` → `tmux attach -t claude`
- **Firewall dashboard:** `http://<server-hostname>:8N80`
- **Ungit (git push):** `http://<server-hostname>:8N04`
- **Portal:** `http://<server-hostname>` — project appears automatically

### 6.2 Git credentials on the server (one-time setup)

Use **fine-grained PATs** (one per GitHub organization) with `Contents: Read-only` permission. Classic PATs don't support read-only repo access.

Route each organization to its own credential file using git config pattern matching:

```bash
# Each org gets its own credential file (config pattern matching uses path prefix)
git config --global credential.https://github.com/<org1>.helper 'store --file ~/.git-credentials-<org1>'
git config --global credential.https://github.com/<org2>.helper 'store --file ~/.git-credentials-<org2>'

# Store PAT in each file (domain only, no path — the config pattern handles routing)
echo "https://<user>:<PAT-for-org1>@github.com" > ~/.git-credentials-<org1>
echo "https://<user>:<PAT-for-org2>@github.com" > ~/.git-credentials-<org2>
```

How it works: when git needs credentials for `github.com/<org1>/repo.git`, the config pattern `credential.https://github.com/<org1>` matches by prefix and routes to the correct file. No `useHttpPath` needed — do NOT set it, it breaks credential-store file matching.

**Azure DevOps repos** — same pattern, different domain:

```bash
git config --global credential.https://dev.azure.com/<org>.helper 'store --file ~/.git-credentials-<org>'
echo "https://<user>:<PAT>@dev.azure.com" > ~/.git-credentials-<org>
```

**IMPORTANT:** Always clone Azure DevOps repos via HTTPS (`https://...`), not SSH (`git@...`). SSH requires an SSH key on the server; PAT credentials only work with HTTPS URLs.

### 6.3 Git credentials inside the devcontainer

Claude needs a **read-only PAT** to pull project repos. Credentials are auto-seeded from `.env` (see Phase 4b):

```bash
cd ~/projects/<project>-devcontainer/.devcontainer
echo 'GIT_CREDENTIALS_READONLY=https://<user>:<read-only-PAT>@<git-host>' >> .env
docker compose up -d --force-recreate devcontainer
```

This PAT only needs read access to the project repos. Stored in `.env` — **survives recreate and `down -v`**. Credentials are re-seeded at every container start.

### 6.4 Ungit write credentials

Ungit needs a **write PAT** for push operations. Use Docker Compose secrets (see Phase 4b):

```bash
mkdir -p ~/.secrets/<project> && chmod 700 ~/.secrets/<project>
echo "https://<user>:<write-PAT>@<git-host>" > ~/.secrets/<project>/git-credentials-write
chmod 600 ~/.secrets/<project>/git-credentials-write
docker compose up -d --force-recreate ungit
```

The write PAT is isolated from Claude — only the ungit container can access it. Verify isolation:
```bash
docker exec -u node <project>-devcontainer-1 cat /run/secrets/git-credentials-write 2>&1
# Expected: No such file or directory
```

### 6.5 Configure .env

Create `.env` on the server with read-only credentials and any project-specific vars:

```bash
cd ~/projects/<project>-devcontainer/.devcontainer
cp .env.example .env
# Add read-only git credentials:
echo 'GIT_CREDENTIALS_READONLY=https://<user>:<read-only-PAT>@<git-host>' >> .env
docker compose up -d --force-recreate devcontainer
```

**IMPORTANT:** Never put write PAT in `.env` — it's mounted into the devcontainer and visible to Claude. Write credentials use Docker secrets (see Phase 6.4).

Note: env vars from `env_file` are visible to processes started by Docker (Claude Code in tmux) but **NOT in SSH sessions**. To verify: `docker compose exec devcontainer env | grep <VAR>`.

---

## Ongoing: Updating the Devcontainer

When the devcontainer repo changes (new dependencies, config updates):

**From developer's machine:**
```bash
cd <project>/devcontainer
# make changes to Dockerfile, docker-compose.yml, etc.
git add . && git commit -m "update: ..." && git push
```

**On the server:**
```bash
ssh cc-ts
cd ~/projects/<project>-devcontainer/.devcontainer
git pull
docker compose up -d --build    # rebuild if Dockerfile changed
# or just: docker compose up -d  # if only compose/config changed
```

Volumes (database data, Claude credentials, command history) survive rebuilds. Only the container image is rebuilt.

**Warning:** `--force-recreate` kills the tmux session. Claude Code will restart but may require re-login. Git credentials inside the container (stored in filesystem, not volume) must be re-set after recreate.

