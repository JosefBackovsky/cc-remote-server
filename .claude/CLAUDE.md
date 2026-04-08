# cc-remote-server

Monorepo for the cc-remote platform — isolated Claude Code sandboxes on a remote server.

## Architecture

```
cc-remote-server/
├── generator/     CLI (Node.js) for generating devcontainer repositories
├── server/        Setup scripts + Terraform for the remote dev host
├── services/      Docker images (Portal, Firewall)
└── setup-skill/   Claude Code skill for onboarding new projects
```

### How modules interact

```
setup-skill (onboarding workflow)
    │
    ├── generator (generates devcontainer repo for a project)
    │     └── uses firewall image from services/
    │
    ├── server (infrastructure for running devcontainers)
    │     └── deploys portal image from services/
    │
    └── services (Docker images: portal + firewall)
          └── CI build → Docker Hub
```

## Modules

### generator/

Node.js CLI tool that generates devcontainer repositories for customer projects.

- **Stack:** Node.js 20+, ES modules, Commander, EJS, js-yaml
- **Tests:** `cd generator && npm test` (Node.js test runner)
- **Conventions:** no TypeScript, no linter, English function names

### server/

Setup scripts for the remote development host (Azure VM or Debian server).

- **Scripts (`scripts/`):** idempotent, distro-agnostic, parameterized
- **Azure (`azure/`):** Terraform >= 1.5, AzureRM >= 3.0
- **Conventions:** `set -euo pipefail`, shellcheck clean

### services/

Docker images — Portal (dashboard) and Firewall (Squid proxy + approval manager).

- **Stack:** Python, FastAPI
- **CI:** GitHub Actions in `.github/workflows/` (root), path-filtered builds
- **Images:** `josefbackovsky/cc-remote-portal`, `josefbackovsky/cc-remote-firewall`

### setup-skill/

Claude Code skill for end-to-end onboarding of new projects onto the cc-remote platform.

## Conventions

- Commit messages: conventional commits (`feat`, `fix`, `refactor`, `chore`, `docs`)
- Scope: module name (`generator`, `server`, `services`, `ci`)
- Sensitive data never in git
