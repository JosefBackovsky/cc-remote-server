# DevContainer Generator

CLI nástroj pro generování oddělených devcontainer repozitářů s předinstalovaným Claude Code.

## Proč?

Definice vývojového prostředí nepatří do projektového repa:
- Dev prostředí (`.devcontainer/`, `.claude/`) nechceš verzovat v projektu
- Každý vývojář nebo tým může mít jiný setup
- Projektové repo zůstane čisté — žádné IDE/tooling soubory
- Snadná reprodukovatelnost prostředí na jiném stroji

Řešení: vygeneruj si **oddělené devcontainer repo**, které žije vedle projektového repa. Projekt zůstane čistý — žádné `.devcontainer/`, žádné `.claude/`.

## Předpoklady

- Node.js 20+
- Docker Desktop (nebo Docker Engine)
- VS Code s rozšířením [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

## Rychlý start

### 1. Nainstaluj závislosti

```bash
npm install
```

### 2. Vygeneruj devcontainer

```bash
node src/cli.js \
  --repo git@github.com:firma/mujprojekt.git \
  --stack nodejs \
  --services postgres \
  --output ~/projects/mujprojekt-devcontainer
```

### 3. Otevři ve VS Code

```bash
cd ~/projects/mujprojekt-devcontainer
code .
```

VS Code detekuje `.devcontainer/` a nabídne **"Reopen in Container"** (nebo přes Command Palette → `Dev Containers: Reopen in Container`).

Při prvním spuštění se automaticky:
1. Naklonuje projektové repo vedle devcontaineru
2. Vytvoří sdílený Docker volume `claude-credentials` (pokud neexistuje)
3. Postaví Docker image s vývojářskými nástroji a Claude Code
4. Spustí kontejner a Claude Code nastartuje v tmux session

### 4. Připoj se ke Claude Code

V kontejneru běží Claude Code automaticky v tmux session. Otevři terminál ve VS Code a připoj se:

```bash
tmux attach -t claude
```

Při prvním spuštění bude Claude čekat na OAuth přihlášení. Po přihlášení se credentials uloží do sdíleného volume a příště se Claude spustí automaticky.

> **Tip:** Devcontainer obsahuje i VS Code extension `anthropic.claude-code`, takže Claude Code můžeš použít i přímo ve VS Code.

### 5. Odpojení

```bash
# Ctrl+B, pak D — odpojí se od tmux, Claude dál pracuje
```

Můžeš zavřít VS Code a Claude pracuje dál. Při dalším otevření se jen znovu připojíš přes `tmux attach -t claude`.

## Jak to funguje

### Single-repo

```
~/projects/
  ├── mujprojekt-devcontainer/     ← vygenerované devcontainer repo
  │   ├── .devcontainer/
  │   │   ├── devcontainer.json    ← konfigurace VS Code, extensions, env
  │   │   ├── docker-compose.yml   ← app + služby, volumes, networking
  │   │   ├── Dockerfile           ← base image, nástroje, Claude Code
  │   │   ├── init-firewall.sh     ← iptables whitelist (pokud není --full-internet)
  │   │   └── init.sh              ← klonuje projektové repo, vytvoří volumes
  │   └── project.yml              ← metadata projektu (repo URL, branch)
  └── mujprojekt/                  ← projektové repo (naklonované automaticky)
```

### Multi-repo

```
~/projects/
  ├── mujprojekt-devcontainer/     ← vygenerované devcontainer repo
  │   ├── .devcontainer/
  │   │   └── ...
  │   └── project.yml              ← metadata projektu (seznam repozitářů)
  └── mujprojekt/                  ← workspace adresář
      ├── backend/                 ← první repo (naklonované automaticky)
      └── frontend/                ← druhý repo (naklonované automaticky)
```

Každý repo se mountuje jako `/workspace/<repoName>/` uvnitř kontejneru.

### Tři vrstvy dat

| Volume | Mount | Účel | Sdílení |
|--------|-------|------|---------|
| `claude-credentials` | `/home/node/.claude` | OAuth tokeny, globální nastavení | Across všechny projekty |
| `<nazev>-claude-project` | `/workspace/.claude` | CLAUDE.md, projektové nastavení | Per projekt |
| `<nazev>-commandhistory` | `/commandhistory` | Bash/zsh historie | Per projekt |
| Bind mount | `/workspace` | Zdrojový kód projektu | — |

Všechny volumes přežijí rebuild kontejneru. `claude-credentials` se vytvoří automaticky při prvním spuštění.

## CLI parametry

| Parametr | Povinný | Default | Popis |
|----------|---------|---------|-------|
| `--repo` | ano | — | Git URL repa (opakovatelný, viz [Multi-repo](#multi-repo)). Per-repo branch: `--repo url#branch` |
| `--output` | ano | — | Cílový adresář pro vygenerovaný devcontainer |
| `--name` | ne | z repo URL | Název projektu (odvozen automaticky z URL). Povinný při multi-repo |
| `--branch` | ne | `main` | Git branch (globální default, per-repo `#branch` má přednost) |
| `--stack` | ne | `nodejs` | SDK/runtime (`nodejs`, `python`, `dotnet`) |
| `--services` | ne | — | Služby oddělené čárkou (`postgres`, `redis`, `mongo`, `azurite`) |
| `--full-internet` | ne | `false` | Vypne firewall — plný přístup k internetu |
| `--include-compose` | ne | `false` | Zahrne projektový `docker-compose.yml` přes Docker Compose `include` (jen single-repo) |
| `--local-claude` | ne | `false` | Mountne `.claude` z devcontainer repa místo Docker volume |
| `--ssh-port` | ne | `2222` | SSH port pro přístup z JetBrains IDE (PyCharm Gateway apod.) |
| `--port-prefix` | ne | — | Prefix portů (např. `82` → SSH `8222`, firewall `8280`). Má přednost před `--ssh-port` |

## Stacky (SDK/runtime)

| Stack | Base image | Popis |
|-------|-----------|-------|
| `nodejs` | `node:22` | Node.js LTS |
| `python` | `python:3.12` | Python 3.12 |
| `dotnet` | `mcr.microsoft.com/dotnet/sdk:9.0` | .NET 9 |

Každý stack automaticky nainstaluje Claude Code (vyžaduje Node.js — u non-Node stacků se doinstaluje automaticky).

## Služby

Libovolná kombinace přes `--services postgres,redis,mongo,azurite`:

| Služba | Image | Port |
|--------|-------|------|
| `postgres` | `postgres:17` | 5432 |
| `mongo` | `mongo:7` | 27017 |
| `redis` | `redis:7` | 6379 |
| `azurite` | Azure Storage Emulator | 10000-10002 |

## Příklady

### Node.js projekt s PostgreSQL a Redis

```bash
node src/cli.js \
  --repo git@github.com:firma/eshop.git \
  --stack nodejs \
  --services postgres,redis \
  --output ~/projects/eshop-devcontainer
```

### .NET projekt s plným internetem a projektovým docker-compose

```bash
node src/cli.js \
  --repo git@github.com:firma/erp.git \
  --stack dotnet \
  --full-internet \
  --include-compose \
  --output ~/projects/erp-devcontainer
```

### Python projekt bez služeb

```bash
node src/cli.js \
  --repo git@github.com:firma/ml-pipeline.git \
  --stack python \
  --output ~/projects/ml-pipeline-devcontainer
```

### Multi-repo projekt s port prefixem

```bash
node src/cli.js \
  --repo https://github.com/firma/backend.git \
  --repo https://github.com/firma/frontend.git#develop \
  --name mujprojekt \
  --stack python \
  --services postgres \
  --port-prefix 82 \
  --output ~/projects/mujprojekt-devcontainer
```

## Multi-repo

Generátor podporuje více repozitářů v jednom devcontaineru — opakuj `--repo`:

```bash
node src/cli.js \
  --repo https://github.com/firma/backend.git \
  --repo https://github.com/firma/frontend.git#develop \
  --name mujprojekt \
  --stack nodejs \
  --output ~/projects/mujprojekt-devcontainer
```

- `--name` je **povinný** při více repech (nelze odvodit z URL)
- Per-repo branch se specifikuje přes `#branch` suffix (např. `url#develop`), jinak se použije globální `--branch`
- Každý repo musí mít unikátní název (basename z URL)
- Workspace layout: `/workspace/backend/`, `/workspace/frontend/`
- `--include-compose` v multi-repo režimu neincluduje automaticky — po generování se vypíše warning s cestami ke compose souborům

## Port prefix

Pro projekty běžící na vzdáleném serveru je užitečné mít porty v určitém rozsahu:

```bash
--port-prefix 82   # → SSH 8222:22, firewall 8280:8080
--port-prefix 83   # → SSH 8322:22, firewall 8380:8080
```

Bez `--port-prefix` se použijí defaulty (SSH `2222`, firewall `8180`). `--port-prefix` má přednost před `--ssh-port`.

## Firewall

Ve výchozím stavu kontejner povoluje jen:
- **Claude API** — `api.anthropic.com`, `statsig.anthropic.com`, `sentry.io`
- **Git** — `github.com`, `gitlab.com`
- **Package managers** — npm, yarn, pip, nuget
- **DNS a SSH**

Vše ostatní je blokováno přes iptables (kontejner má `NET_ADMIN` capability). Pro plný přístup k internetu použij `--full-internet` — firewall se vůbec nevytvoří.

### Blokování git push pro Claude Code

Pokud chceš aby Claude Code nemohl pushovat do vzdáleného repozitáře (např. při `--dangerously-skip-permissions`), odeber git remote domény z `init-firewall.sh`. Claude běží jako neprivilegovaný uživatel `node` a nemá sudo přístup k iptables — firewall nemůže obejít.

```bash
# V init-firewall.sh odeber/zakomentuj domény git remote:
# dev.azure.com
# ssh.dev.azure.com
# github.com  (pokud je to tvůj remote)
```

Claude může normálně commitovat a vytvářet větve — workspace je bind mount z hostu. Ty pak pushuješ z hostitelského stroje:

```bash
# Na hostu (mimo kontejner)
cd ~/projects/mujprojekt
git log     # vidíš commity vytvořené Claudem
git push    # pushuješ ty
```

> **Pozn.:** Bez přístupu k git remote nemůže Claude ani `git pull`/`git fetch`. Před zahájením session udělej `git pull` na hostu.

## Přístup k portům (VS Code Remote + Docker Compose)

Při práci přes VS Code Remote SSH + Dev Containers existují **dva typy portů** s různým způsobem přístupu:

### Porty uvnitř devcontaineru (VS Code forwardPorts)

Porty aplikací, které **spouštíš uvnitř devcontaineru** (tvůj backend, frontend atd.). Tyto VS Code umí forwardovat automaticky přes `forwardPorts` v `devcontainer.json`:

```json
"forwardPorts": [8001, 8002, 4321],
"portsAttributes": {
  "8001": { "label": "backend", "onAutoForward": "silent" }
}
```

→ Přístup přes **localhost:8001** ve VS Code.

### Porty sibling kontejnerů (přímý přístup přes síť)

Porty ostatních Docker Compose services (databáze, Langfuse, Squid, approval-app atd.) jsou mapované na **Docker hostu**, ne uvnitř devcontaineru. VS Code `forwardPorts` na ně **nefunguje**.

Přístup závisí na síťové konfiguraci:

- **Tailscale / LAN:** `http://<hostname>:<port>` přímo z prohlížeče
- **SSH tunel:** `ssh -L <port>:localhost:<port> <host>` → `localhost:<port>`
- **Portainer:** webové UI pro správu kontejnerů na `https://<hostname>:9443`

Příklad — wiki-chatbot na Tailscale:

| Služba | Port | Přístup |
|--------|------|---------|
| Langfuse web | 8100 | `http://<tailscale-hostname>:8100` |
| PostgreSQL | 8132 | `<tailscale-hostname>:8132` |
| Proxy approval | 8180 | `http://<tailscale-hostname>:8180` |
| Portainer | 9443 | `https://<tailscale-hostname>:9443` |

> **Pravidlo:** Do `forwardPorts` dávej jen porty které **běží uvnitř devcontaineru**. Porty sibling services tam nedávej — nebudou fungovat.

## Práce s Claude Code

### Tmux session

Claude Code se automaticky spustí v tmux session při startu kontejneru:

```bash
# Připojení
tmux attach -t claude

# Odpojení (Claude dál pracuje)
Ctrl+B, pak D

# Z jiného stroje přes SSH
docker exec -it <kontejner> bash
tmux attach -t claude
```

### Typický workflow

1. **Ráno:** VS Code → "Reopen in Container" → terminál → `tmux attach -t claude`
2. **Přes den:** zadáváš úkoly, sleduješ výstup
3. **Odcházíš:** `Ctrl+B, D` — Claude pracuje dál, můžeš zavřít VS Code
4. **Z telefonu:** SSH na stroj → `docker exec -it <kontejner> bash` → `tmux attach -t claude`
5. **Další den:** VS Code znovu → `tmux attach -t claude` → Claude má hotovo

### Projektové instrukce (CLAUDE.md)

Volume `<nazev>-claude-project` se mountuje na `/workspace/.claude`. Vytvoř v něm `CLAUDE.md` s projektovými instrukcemi:

```bash
# Uvnitř kontejneru
echo "# Projektové instrukce" > /workspace/.claude/CLAUDE.md
```

Soubor přežije rebuild kontejneru a projektové repo zůstane čisté (volume překryje adresář).

## Vývoj

```bash
npm install
npm test
```
