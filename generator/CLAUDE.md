# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Co to je

CLI nástroj v Node.js, který generuje kompletní devcontainer repozitáře pro zákaznické projekty. Výstupem je samostatné repo `<nazev>-devcontainer`, které žije vedle zákaznického repa — zákaznické repo zůstane čisté (žádný `.devcontainer/`, žádný `.claude/`).

## Příkazy

```bash
npm install              # instalace závislostí
npm test                 # spuštění všech testů (node --test)
node --test test/generator.test.js   # spuštění jednoho test souboru
node --test --test-name-pattern "postgres" test/generator.test.js  # spuštění konkrétního testu

# Generování devcontaineru
node src/cli.js \
  --repo git@github.com:firma/projekt.git \
  --stack nodejs \
  --services postgres,redis \
  --output ~/projects/projekt-devcontainer
```

## Konvence kódu

- ES modules (`"type": "module"` v package.json)
- Žádný TypeScript
- Funkce pojmenované anglicky, komentáře mohou být česky
- Testy pomocí Node.js test runner (`node --test`) — žádný jest, mocha, ani jiný framework
- Žádný linter/formatter nakonfigurovaný v projektu

## Architektura

### Průchod dat

```
CLI argumenty (cli.js)
  → parsuje Commander, volá generate()
    → stack-loader.js načte stack YAML + services YAML
    → generator.js renderuje EJS šablony s kontextem {name, repos, multiRepo, stack, services, ...}
      → výstup: .devcontainer/ složka s devcontainer.json, docker-compose.yml, Dockerfile, init.sh, [init-firewall.sh, CLAUDE.md]
```

### Klíčové moduly

- **`src/cli.js`** — vstupní bod, Commander definice, parsování `--services` na pole
- **`src/generator.js`** — renderuje EJS šablony, zapisuje soubory, vypisuje instrukce po vygenerování
- **`src/stack-loader.js`** — načítá YAML definice stacků a služeb, validuje povinná pole

### Šablony (`src/templates/`)

EJS šablony v `base/` generují výstupní soubory. Kontext předávaný do šablon:

```js
{ name, repos, multiRepo, stack, services, serviceVolumes, fullInternet, includeCompose, localClaude, sshPort, firewallPort }
```

- `stack` — objekt z YAML (name, base_image, tools, vscode_extensions, firewall_domains)
- `services` — objekt `{ název: definice }` z YAML souborů
- `serviceVolumes` — extrahované pojmenované volumes ze služeb

Stacky (`stacks/*.yml`) a služby (`services/*.yml`) jsou YAML soubory s pevnou strukturou — stack musí mít `name`, `base_image`, `tools`; služba musí mít `name`, `image`.

## Architektura generovaného devcontaineru

### Struktura výstupu

```
<nazev>-devcontainer/
  ├── .devcontainer/
  │   ├── devcontainer.json
  │   ├── docker-compose.yml
  │   ├── Dockerfile
  │   ├── init-firewall.sh       ← iptables + proxy režim (jen bez --full-internet)
  │   ├── CLAUDE.md              ← proxy instrukce pro Claude (jen bez --full-internet)
  │   └── init.sh                ← naklonuje zákaznické repo pokud neexistuje
  └── project.yml                ← konfigurace projektu (repo URL, branch)
```

### Síťová izolace — Squid proxy režim

Bez `--full-internet` se generuje dvouvrstvá izolace:

1. **Squid proxy** (`josefbackovsky/cc-remote-firewall:latest`) — sidecar kontejner, whitelist domén, approval API na portu 8080 (mapovaný na host 8180)
2. **iptables** (`init-firewall.sh`) — default-deny, povoleny jen Docker interní sítě (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) a Docker DNS (127.0.0.11). Žádné domény — vše jde přes proxy.

Devcontainer má nastavené `http_proxy`/`https_proxy` env vars na `http://firewall:3128` a `depends_on` firewall service s healthcheck. Git config má taky proxy. `no_proxy` obsahuje `localhost,127.0.0.1,firewall` + názvy služeb.

S `--full-internet`: žádný proxy, žádný firewall, žádné `NET_ADMIN`/`NET_RAW`, žádný `postStartCommand`.

### Docker Compose služby

- **`devcontainer`** — hlavní služba (ne `app`), build z Dockerfile, SSH server na portu 22 (mapovaný na `--ssh-port`, default 2222)
- **`firewall`** — Squid proxy (jen bez `--full-internet`)
- **Volitelné služby** — postgres, mongo, redis, azurite

### Volumes

| Volume | Mount | Popis |
|--------|-------|-------|
| `claude-shared` (external) | `/home/node/.claude` | OAuth tokeny, sdílený across projekty |
| `<nazev>-commandhistory` | `/commandhistory` | Zsh historie, per-projekt |
| `firewall-data` | `/data` (ve firewall) | Proxy data (jen bez --full-internet) |

S `--local-claude`: místo Docker volume pro projekt se mountne `.project-claude/` z devcontainer repa na `/workspace/.claude` (bind mount, commitovatelný do gitu). Přidá `.claude/` do git exclude zákaznického repa.

### Tmux auto-start

`command` v docker-compose spustí SSH server, reinstaluje Claude Code a nastartuje tmux session `claude` s `--dangerously-skip-permissions`. Kontejner drží `sleep infinity`.

### CLI flagy

| Flag | Default | Popis |
|------|---------|-------|
| `--repo` (min. 1) | — | Git URL repa (opakovatelný, `url#branch` pro per-repo branch) |
| `--output` (required) | — | Cílový adresář |
| `--name` | z repo URL | Název projektu (povinný při multi-repo) |
| `--branch` | `main` | Git branch (globální default) |
| `--stack` | `nodejs` | SDK/runtime: `nodejs`, `python`, `dotnet` |
| `--services` | — | Čárkou oddělené: `postgres`, `mongo`, `redis`, `azurite` |
| `--full-internet` | `false` | Vypne firewall a proxy |
| `--include-compose` | `false` | Zahrne zákaznický docker-compose přes compose `include` (jen single-repo) |
| `--local-claude` | `false` | Bind mount .claude místo Docker volume |
| `--ssh-port` | `2222` | SSH port pro JetBrains IDE |
| `--port-prefix` | — | Prefix portů (např. `82` → SSH `8222`, firewall `8280`). Přednost před `--ssh-port` |

## TODO

- [ ] Interaktivní režim (inquirer nebo prompts)
- [ ] Validace vstupů (repo URL format, existence stacku)
