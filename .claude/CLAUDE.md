# cc-remote-server

Monorepo pro cc-remote platformu — izolované Claude Code sandboxes na remote serveru.

## Architektura

```
cc-remote-server/
├── generator/     CLI (Node.js) pro generování devcontainer repozitářů
├── server/        Setup skripty + Terraform pro remote dev host
├── services/      Docker images (Portal, Firewall)
└── setup-skill/   Claude Code skill pro onboarding nových projektů
```

### Jak moduly spolupracují

```
setup-skill (workflow pro onboarding)
    │
    ├── generator (generuje devcontainer repo pro projekt)
    │     └── používá firewall image z services/
    │
    ├── server (infrastruktura pro běh devcontainerů)
    │     └── deployuje portal image z services/
    │
    └── services (Docker images: portal + firewall)
          └── CI build → Docker Hub
```

## Moduly

### generator/

CLI nástroj v Node.js generující devcontainer repozitáře pro zákaznické projekty.

- **Stack:** Node.js 20+, ES modules, Commander, EJS, js-yaml
- **Testy:** `cd generator && npm test` (Node.js test runner)
- **Konvence:** žádný TypeScript, žádný linter, anglické funkce

### server/

Setup skripty pro remote development host (Azure VM nebo Debian server).

- **Skripty (`scripts/`):** idempotentní, distro-agnostické, parametrizované
- **Azure (`azure/`):** Terraform >= 1.5, AzureRM >= 3.0
- **Konvence:** `set -euo pipefail`, shellcheck clean

### services/

Docker images — Portal (dashboard) a Firewall (Squid proxy + approval manager).

- **Stack:** Python, FastAPI
- **CI:** GitHub Actions v `.github/workflows/` (root), path-filtered buildy
- **Images:** `josefbackovsky/cc-remote-portal`, `josefbackovsky/cc-remote-firewall`

### setup-skill/

Claude Code skill pro end-to-end onboarding nových projektů na cc-remote platformu.

## Konvence

- Commit messages: conventional commits (`feat`, `fix`, `refactor`, `chore`, `docs`)
- Scope: název modulu (`generator`, `server`, `services`, `ci`)
- Sensitive data nikdy v gitu
- Dokumentace česky, kód anglicky
