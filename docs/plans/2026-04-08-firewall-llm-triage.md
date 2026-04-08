# Firewall LLM Triage — Automatické vyhodnocování síťových požadavků pomocí LLM

## Popis

Rozšíření Firewall služby o inteligentní vrstvu, která pomocí LLM (GPT-5.4-mini na Azure OpenAI, reasoning effort: none) automaticky vyhodnocuje síťové požadavky z devcontaineru. Místo aktuálního modelu „vše zablokovat → developer manuálně schválí" přechází systém na inline evaluaci: neznámý požadavek se pozdrží, LLM ho vyhodnotí, a pokud je bezpečný, projde bez blokace.

**Klíčové design decisions (po cross-check review):**
- **LLM auto-approve zůstává** — bez něj je feature nepoužitelná (ekvivalent dnešního stavu)
- **Azure OpenAI** místo Anthropic API — data zůstávají pod naší kontrolou, žádné logování třetí stranou
- **GPT-5.4-mini s reasoning effort: none** — minimální latence na hot path
- **Request body jde do LLM** — nutné pro detekci exfiltrace (šifrované/encodované tokeny regex nechytí, LLM posoudí request jako celek)
- **Prompt injection mitigace na úrovni modelu** — Azure OpenAI řeší na platform level

### Mimo scope

- Non-HTTP protokoly (raw TCP, UDP tunneling)
- DNS-over-HTTPS detekce
- WebSocket traffic inspekce
- Response body inspekce (jen request body)
- Filtrace inter-container traffic (zůstává na Docker network level)

### Proč

- **Approval fatigue:** Developer musí manuálně schvalovat každý nový domain, což vede k rubber-stamping a snížené bezpečnosti
- **Latence workflow:** Claude/nástroje musí čekat na manuální schválení, což zpomaluje práci o minuty až hodiny
- **Data exfiltrace:** Hlavní threat model — malicious software nebo Claude sám odešle PAT token, credentials nebo citlivá data na externí server
- **Git push útok (Shai-Hulud):** Útočník může pushovat škodlivý kód přes GitHub, nutné blokovat `git push` na úrovni HTTP
- **Nedostatečná inspekce:** Squid v CONNECT režimu vidí jen domain name, ne obsah HTTPS požadavků

## Aktuální stav

### Architektura

Firewall služba běží jako jeden Docker kontejner se dvěma procesy:

1. **Squid proxy** (port 3128) — forward proxy s domain-based ACL whitelistem
2. **Firewall Manager** (port 8080) — FastAPI web dashboard + REST API pro approval workflow

Devcontainer má nastaven `http_proxy`/`https_proxy` na `http://firewall:3128` a iptables pravidla blokují veškerý přímý internet — vše musí jít přes proxy.

### Request flow (aktuální)

```
Claude/nástroj → HTTP(S) request
    → Squid proxy (port 3128)
        → domain v whitelistu? → pustit
        → domain není v whitelistu? → TCP_DENIED + ERR_BLOCKED
            → Claude pošle POST /api/request {domain, reason}
            → Developer manuálně schválí/zamítne přes dashboard
            → domain přidán do whitelistu → squid -k reconfigure
            → Claude retry → request projde
```

### Klíčové soubory

| Soubor | Účel |
|--------|------|
| `services/firewall/Dockerfile:1-37` | Docker image — ubuntu/squid + Python + FastAPI |
| `services/firewall/squid.conf:1-38` | Squid konfigurace — ACL whitelist, porty, logy |
| `services/firewall/entrypoint.sh:1-79` | Startup — squid + whitelist watcher + uvicorn |
| `services/firewall/manager/main.py:1-127` | FastAPI app — API endpointy, dashboard |
| `services/firewall/manager/database.py:1-73` | SQLite — requests tabulka, CRUD |
| `services/firewall/manager/whitelist.py:1-38` | Whitelist file I/O (čtení, přidání, odebrání) |
| `services/firewall/manager/logparser.py:1-73` | Parsování Squid access logu (TCP_DENIED) |
| `services/firewall/manager/templates/index.html:1-210` | Web dashboard — requests, blocked, whitelist |
| `services/firewall/whitelist-default.txt:1-25` | Výchozí whitelist (Anthropic, GitHub, PyPI, npm...) |
| `services/firewall/ERR_BLOCKED:1-15` | Custom error page pro zablokované domény |
| `generator/src/templates/base/docker-compose.yml.ejs:57-73` | Docker Compose template — firewall service definice |
| `generator/src/templates/base/init-firewall.sh.ejs:1-31` | iptables pravidla v devcontaineru |
| `.github/workflows/build-firewall.yml:1-43` | CI — build + push Docker image |

### Omezení aktuálního řešení

| Aspekt | Současný stav | Navrhovaný stav |
|--------|--------------|-----------------|
| Vyhodnocování | Manuální (developer) | LLM triage (auto-approve / auto-deny / escalate) |
| HTTPS inspekce | Žádná (Squid vidí jen domain z SNI) | Plná (mitmproxy SSL bump — URL, headers, body) |
| Git push ochrana | Žádná (github.com je whitelisted) | Blokace `git-receive-pack` na URL úrovni |
| Pravidla | Flat domain whitelist | Granulární pravidla (domain, URL pattern, HTTP method) |
| Latence schválení | Minuty-hodiny (čeká na developera) | ~1-2s pro LLM evaluaci, instant pro cached |
| Proxy engine | Squid (domain-only filtering) | mitmproxy (plná HTTPS inspekce + Python API) |

## Návrh řešení

### Architektura

```
Devcontainer → HTTP(S) request
    → mitmproxy (port 3128, SSL bump)
        → Rule engine check:
            │
            ├── static whitelist match? → pustit okamžitě (0ms overhead)
            │
            ├── static block rule match? → zablokovat okamžitě
            │   (např. git-receive-pack, known malicious patterns)
            │
            ├── cached LLM rozhodnutí? → použít cache (0ms overhead)
            │
            └── neznámý request → LLM evaluace (~1-2s)
                  │
                  ├── auto-approve (LLM confident safe)
                  │     → přidat do cache, pustit request
                  │
                  ├── auto-deny (LLM confident risky)
                  │     → zablokovat, zalogovat, notifikovat dashboard
                  │
                  └── escalate (LLM uncertain)
                        → zablokovat, vytvořit pending request pro developera
                        → developer schválí/zamítne přes dashboard

    + Claude fast-track: POST /api/request {domain, reason}
        → LLM evaluace s extra kontextem (reason)
        → stejné 3 výstupy (approve/deny/escalate)
```

### Přechod ze Squid na mitmproxy

**Proč mitmproxy:**
- Plný Python API — addon systém s async hooky pro interceptování requestů
- SSL bump nativně — automatická generace CA certifikátu, MITM transparentně
- Vidíme **vše**: domain, URL path, query params, headers, request body
- Programatické rozhodování — `flow.kill()` pro blokaci, async hooks pro LLM volání
- Stejný jazyk jako Firewall Manager (Python) — jednodušší architektura

**Co se mění:**
- Squid proxy → mitmproxy (port 3128 zůstává stejný)
- `squid.conf` → mitmproxy addon (Python)
- Whitelist watcher (checksum loop) → přímá integrace v addon kódu
- Squid access log → mitmproxy logging v addon

**Co zůstává:**
- FastAPI Firewall Manager (port 8080) — dashboard + API
- SQLite databáze — requests tracking
- Docker image structure — jeden kontejner, dva procesy
- iptables v devcontaineru — beze změn
- Docker Compose template interface — stejné porty, volumes, env vars

### CA certifikát (trust chain)

mitmproxy automaticky generuje CA certifikát při prvním startu (`~/.mitmproxy/mitmproxy-ca.pem`). Devcontainer musí tomuto CA důvěřovat:

1. `entrypoint.sh` explicitně vygeneruje CA cert PŘED startem mitmproxy (`mitmdump --dump-cert-path /data/certs/`)
2. Na shared volume `/data/certs/` se vystaví **pouze veřejný certifikát** (`mitmproxy-ca-cert.pem`), nikoli privátní klíč
3. Privátní klíč zůstává v `/root/.mitmproxy/` uvnitř firewall kontejneru
4. Devcontainer mountuje shared volume jako read-only
5. `init-firewall.sh` (runtime, ne build-time) nainstaluje cert do trust store:
   - `cp /certs/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/ && update-ca-certificates`
   - `export NODE_EXTRA_CA_CERTS=/certs/mitmproxy-ca-cert.pem`
   - `export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt`
   - `export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt`
   - `export GIT_SSL_CAINFO=/etc/ssl/certs/ca-certificates.crt`
6. Healthcheck v docker-compose ověří existenci cert souboru: `test -f /data/certs/mitmproxy-ca-cert.pem`

**DŮLEŽITÉ:** CA cert instalace je čistě runtime (v `init-firewall.sh.ejs`), NE build-time (ne v `Dockerfile.ejs`). Cert neexistuje v build time — generuje se při startu firewall kontejneru.

### mitmproxy addon — `firewall_addon.py`

Hlavní komponenta — Python addon pro mitmproxy, který implementuje veškerou logiku:

**Hooks:**
- `async def request(self, flow: http.HTTPFlow)` — hlavní hook, volaný pro každý request
- Addon má přístup k: `flow.request.url`, `flow.request.headers`, `flow.request.content`, `flow.request.method`

**Rozhodovací logika (v `request` hooku):**

```
1. Parse domain + URL path z flow.request
2. Check static rules (rule engine, in-memory snapshot):
   a. Block rule match (domain/pattern) → deny (NEJVYŠŠÍ PRIORITA)
   b. Whitelist match (domain/pattern) → allow (skip body buffering)
3. Body credential scan (regex):
   → Skenovat prvních 64KB body na token/credential patterny
   → Match → automatic deny bez LLM
4. Check LLM cache (klíč: domain + method + path)
   → hit → apply cached decision
   → POZOR: POST/PUT/PATCH s body se NIKDY neservírují z cache
5. Deduplication check:
   → Pokud už běží LLM evaluace pro stejný domain → čekat na výsledek (asyncio.Event)
6. Concurrency gate (max 5 in-flight LLM calls, semaphore):
   → Pokud plný → escalate (blokovat, pending request)
7. Async LLM call (Azure OpenAI GPT-5.4-mini, reasoning_effort: none, timeout: 5s):
   → Send: domain, URL, method, headers, body (truncated ~4KB), project context
   → Receive: {decision: "approve"|"deny"|"escalate", reasoning: "..."}
   → Timeout/error → escalate (fallback)
8. Apply decision:
   - approve → allow flow, cache result
   - deny → flow.response = HTTP 403, log
   - escalate → flow.response = HTTP 403 s instrukcemi, create pending request
```

**Poznámka k body v LLM promptu:** Request body se posílá do LLM záměrně — je nutné pro detekci exfiltrace. Attacker může base64-encodovat, šifrovat nebo jinak obfuskovat credentials; regex to nikdy nechytí. LLM posoudí request jako celek (proč Python app posílá POST s binary payloadem na neznámý server?). Prompt injection mitigace je na úrovni Azure OpenAI platform.

### Rule engine — granulární pravidla

Pravidla se ukládají v SQLite a konfigurují přes dashboard/API. Typy pravidel:

```yaml
# Celý domain — whitelist
- domain: "docs.python.org"
  action: allow

# URL path prefix
- domain: "vault.azure.net"
  path_prefix: "/secrets/kv-dovera-local/"
  action: allow

# URL pattern (regex)
- domain: "github.com"
  path_pattern: ".*/git-receive-pack$"
  action: deny  # blokuje git push

# Celý domain kromě specifických paths
- domain: "example.com"
  path_prefix: "/api/safe/"
  action: allow
  # vše ostatní na example.com jde přes LLM evaluaci
```

**Priorita vyhodnocení:**
1. Block rules (nejvyšší priorita — bezpečnost)
2. Allow rules (whitelist)
3. LLM cache
4. LLM evaluace (fallback)

### LLM evaluace — prompt design

LLM (GPT-5.4-mini na Azure OpenAI, reasoning_effort: none) dostane maximum informací pro rozhodnutí:

**Input:**
- Domain name
- Full URL (path + query params)
- HTTP method
- Request headers (filtrované — bez auth tokenů v promptu)
- Request body (truncated na ~4KB, pro velké payloady jen začátek)
- Project context (env var `PROJECT_CONTEXT`, např. "Python FastAPI web app")
- Reason (pokud přišel přes `POST /api/request`)

**Instrukce pro LLM (systémový prompt):**

```
You are a security evaluator for a development sandbox firewall.
Your job is to decide if an outbound HTTP request is safe or represents
a data exfiltration risk.

APPROVE if:
- Domain is a well-known developer resource (docs, package registry, API docs)
- Request is clearly development-related (fetching dependencies, reading docs)
- No sensitive data visible in URL, headers, or body

DENY if:
- Request body contains tokens, API keys, passwords, or credentials
- Domain appears to be a data exfiltration endpoint (webhook, pastebin, file sharing)
- Domain is typosquatting a legitimate domain
- Request is git-receive-pack (push) to any host
- Request body contains high-entropy strings that could be encoded credentials

ESCALATE if:
- You're not confident in your assessment
- Domain is legitimate but request content is unusual
- Request goes to a cloud API that could be used for both legitimate and malicious purposes

Respond with JSON: {"decision": "approve|deny|escalate", "reasoning": "..."}
```

**Output:**
```json
{"decision": "approve", "reasoning": "docs.python.org is the official Python documentation site, request is a GET for asyncio docs page"}
```

**Response contract pro `POST /api/request` (Claude fast-track):**

| LLM rozhodnutí | Response | Claude akce |
|----------------|----------|-------------|
| approve | `{"id": "...", "status": "approved", "llm_reasoning": "..."}` | Retry request — projde |
| deny | `{"id": "...", "status": "denied", "llm_reasoning": "..."}` | Informovat uživatele |
| escalate | `{"id": "...", "status": "pending", "llm_reasoning": "..."}` | Pollovat `GET /api/requests/{id}` jako dnes |

**Error response (mitmproxy 403) pro deny/escalate:**

Při deny/escalate mitmproxy vrátí HTTP 403 s JSON body:
```json
{
  "blocked": true,
  "domain": "example.com",
  "decision": "escalate",
  "reasoning": "Unknown domain, escalating to developer",
  "request_url": "http://firewall:8080/api/request",
  "hint": "Submit POST /api/request with {domain, reason} for fast-track evaluation"
}
```

### Audit log

Každé LLM rozhodnutí se loguje do SQLite pro audit trail:

```sql
CREATE TABLE IF NOT EXISTS llm_decisions (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    domain TEXT NOT NULL,
    url TEXT NOT NULL,
    method TEXT NOT NULL,
    decision TEXT NOT NULL,        -- approve|deny|escalate
    reasoning TEXT NOT NULL,       -- LLM reasoning
    source TEXT NOT NULL,          -- "auto" | "request:{id}"
    cached BOOLEAN DEFAULT FALSE
);
```

### Databázové změny

#### Nová tabulka: `rules`

```sql
CREATE TABLE IF NOT EXISTS rules (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    path_pattern TEXT,             -- regex pattern pro URL path (NULL = celý domain)
    path_prefix TEXT,              -- prefix match pro URL path (NULL = celý domain)
    action TEXT NOT NULL,          -- allow|deny
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_rules_domain ON rules(domain);
```

**In-memory snapshot:** Pravidla se načtou do paměti při startu a při každé mutaci přes API (event-driven reload). `check_rules()` NIKDY nečte z DB na hot path — pracuje s in-memory snapshotem. Regex patterny se pre-kompilují při loadu pomocí `re2` (backtracking-safe). Délka regex patternů je omezena na 200 znaků.

#### Nová tabulka: `llm_decisions`

```sql
CREATE TABLE IF NOT EXISTS llm_decisions (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    domain TEXT NOT NULL,
    url TEXT NOT NULL,
    method TEXT NOT NULL,
    decision TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    source TEXT NOT NULL,
    cached BOOLEAN DEFAULT FALSE
);
CREATE INDEX idx_decisions_timestamp ON llm_decisions(timestamp);
CREATE INDEX idx_decisions_domain ON llm_decisions(domain);
CREATE INDEX idx_decisions_decision ON llm_decisions(decision, timestamp);
```

**Retention policy:** Při startu a pak každých 24h: `DELETE FROM llm_decisions WHERE timestamp < datetime('now', '-30 days')`. Maximum 100k řádků.

#### Úprava tabulky `requests`

Přidání sloupce pro LLM rozhodnutí:

```sql
ALTER TABLE requests ADD COLUMN llm_decision TEXT;      -- approve|deny|escalate|NULL
ALTER TABLE requests ADD COLUMN llm_reasoning TEXT;      -- LLM reasoning text
```

### Změny v servisní vrstvě

#### Nový modul: `llm_evaluator.py`

Zodpovědný za volání Azure OpenAI API (GPT-5.4-mini) a parsování odpovědi.

Signature:

```python
async def evaluate_request(
    domain: str,
    url: str,
    method: str,
    headers: dict,
    body: bytes | None,
    project_context: str,
    reason: str | None = None,
) -> dict:
    """Returns {"decision": "approve"|"deny"|"escalate", "reasoning": "..."}
    
    Uses Azure OpenAI GPT-5.4-mini with reasoning_effort=none.
    Timeout: 5s. On timeout/error → returns escalate.
    """
```

#### Nový modul: `rule_engine.py`

Vyhodnocení statických pravidel (whitelist, block rules).

Signatury:

```python
def check_rules(domain: str, path: str, method: str) -> str | None:
    """Returns "allow"|"deny"|None (None = no rule matched, proceed to LLM)
    
    Works with in-memory snapshot, NEVER queries DB on hot path.
    Regex patterns pre-compiled with re2 at load time.
    """

def load_rules() -> list[dict]:
    """Load all rules from DB into in-memory snapshot. Called at startup
    and on every rule mutation via API (event-driven reload)."""
```

#### Nový modul: `decision_cache.py`

In-memory LRU cache pro LLM rozhodnutí s TTL. Max 10k entries.

Signatury:

```python
def get_cached_decision(domain: str, method: str, path: str) -> dict | None:
    """Returns cached LLM decision or None.
    
    Cache key: (domain, method, path).
    POST/PUT/PATCH s body se NIKDY neservírují z cache — vždy re-evaluate.
    Uses cachetools.TTLCache(maxsize=10000, ttl=3600).
    """

def cache_decision(domain: str, method: str, path: str, decision: dict):
    """Cache an LLM decision. Only caches GET/HEAD/OPTIONS and deny decisions."""
```

#### Nový modul: `firewall_addon.py`

mitmproxy addon — hlavní interceptor.

```python
class FirewallAddon:
    async def request(self, flow: http.HTTPFlow) -> None:
        """Main hook — evaluates every request"""

    def _build_error_response(self, flow, decision, reasoning) -> None:
        """Set flow.response to 403 with explanation"""
```

#### Upravený modul: `main.py`

Nové API endpointy:

```python
# === Veřejné (bez auth) — devcontainer k nim má přístup ===
POST   /api/request            # Claude fast-track with reason → LLM evaluace
GET    /api/requests/{id}      # Claude polls status

# === Chráněné (MANAGER_AUTH_TOKEN) — jen developer/portal ===
# Rules CRUD
GET    /api/rules              # list all rules
POST   /api/rules              # create rule (triggers in-memory reload)
PUT    /api/rules/{id}         # update rule (triggers in-memory reload)
DELETE /api/rules/{id}         # delete rule (triggers in-memory reload)

# Request management
GET    /api/requests            # list all requests
POST   /api/requests/{id}/approve   # approve escalated request → creates allow rule
POST   /api/requests/{id}/deny      # deny escalated request

# LLM decisions audit log
GET    /api/decisions           # list (paginated, default 50)
GET    /api/decisions/stats     # aggregated stats

# Whitelist (legacy compatibility)
GET    /api/whitelist           # current allow rules
POST   /api/approve             # direct domain approve → creates allow rule
DELETE /api/revoke              # remove allow rule

# Dashboard
GET    /                        # web dashboard (bez auth — read-only view)
```

**Auth:** Management endpointy vyžadují `Authorization: Bearer <MANAGER_AUTH_TOKEN>` header. `POST /api/request` a `GET /api/requests/{id}` jsou bez auth (Claude k nim přistupuje z devcontaineru). Dashboard (`GET /`) je read-only bez auth.

**Osud existujících endpointů:**
- `POST /api/approve` → zachován, vytvoří allow rule v rules tabulce (místo zápisu do whitelist souboru)
- `DELETE /api/revoke` → zachován, smaže allow rule z rules tabulky
- `GET /api/blocked` → **nahrazen** — blocked domény se berou z `llm_decisions` (decision=deny|escalate) místo parsování Squid logů
- `GET /api/whitelist` → zachován, vrací allow rules z rules tabulky

#### Upravený modul: `database.py`

Nové funkce pro rules a decisions tabulky.

### Změny v UI

Dashboard (`index.html`) se rozšíří o nové sekce:

1. **Escalated Requests** — requesty kde LLM eskaloval na developera (approve/deny tlačítka)
2. **Rules** — CRUD pro pravidla (domain, URL pattern, action) s formulářem pro přidání
3. **LLM Decisions** — audit log s filtrováním (approve/deny/escalate, domain, časové rozmezí)
4. **Stats** — počet auto-approved, auto-denied, escalated za posledních 24h/7d

### Konfigurace

Nové environment variables:

| Variable | Default | Popis |
|----------|---------|-------|
| `AZURE_OPENAI_ENDPOINT` | (povinné) | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_API_KEY` | (povinné) | Azure OpenAI API klíč |
| `AZURE_OPENAI_DEPLOYMENT` | `gpt-5.4-mini` | Deployment name pro model |
| `AZURE_OPENAI_API_VERSION` | `2025-12-01-preview` | Azure OpenAI API verze |
| `PROJECT_CONTEXT` | (prázdné) | Popis projektu pro LLM kontext |
| `LLM_CACHE_TTL` | `3600` | TTL cache pro LLM rozhodnutí (sekundy) |
| `LLM_TIMEOUT` | `5` | Timeout pro LLM API call (sekundy) |
| `LLM_MAX_CONCURRENT` | `5` | Max souběžných LLM evaluací |
| `LLM_ENABLED` | `true` | Zapnout/vypnout LLM evaluaci (false = vše escalate) |
| `MITMPROXY_CA_DIR` | `/data/certs` | Adresář pro CA certifikát |
| `MANAGER_AUTH_TOKEN` | (povinné) | Bearer token pro management API endpointy |

## Dotčené soubory

### Nové soubory

- `services/firewall/manager/firewall_addon.py` — mitmproxy addon, hlavní interceptor
- `services/firewall/manager/llm_evaluator.py` — Claude API klient, prompt construction
- `services/firewall/manager/rule_engine.py` — statická pravidla (whitelist/block)
- `services/firewall/manager/decision_cache.py` — in-memory LLM decision cache

### Upravené soubory

- `services/firewall/Dockerfile:1-37` — base image změna (ubuntu/squid → python:3.12-slim + mitmproxy), nové závislosti
- `services/firewall/entrypoint.sh:1-79` — nahrazení squid startu za mitmproxy, generování CA certu, odstranění whitelist watcheru
- `services/firewall/manager/main.py:1-127` — nové API endpointy (rules CRUD, decisions, stats)
- `services/firewall/manager/database.py:1-73` — nové tabulky (rules, llm_decisions), migrace requests tabulky
- `services/firewall/manager/whitelist.py:1-38` — adaptace pro rule engine (whitelist se načítá z DB + default souboru)
- `services/firewall/manager/templates/index.html:1-210` — nové sekce (rules, decisions, escalated requests)
- `services/firewall/manager/requirements.txt:1-4` — přidání `mitmproxy`, `openai`, `cachetools`, `google-re2`
- `services/firewall/whitelist-default.txt:1-25` — zachováno, importuje se do rules při prvním startu
- `services/firewall/ERR_BLOCKED:1-15` — úprava textu (mitmproxy místo Squid)
- `services/firewall/README.md:1-36` — aktualizace dokumentace
- `generator/src/templates/base/docker-compose.yml.ejs:57-73` — nové env vars (AZURE_OPENAI_*, PROJECT_CONTEXT, MANAGER_AUTH_TOKEN), sdílený volume pro CA cert
- `generator/src/templates/base/init-firewall.sh.ejs:1-31` — přidání runtime instalace CA certifikátu + SSL env vars (NODE_EXTRA_CA_CERTS, REQUESTS_CA_BUNDLE, SSL_CERT_FILE, GIT_SSL_CAINFO)
- `.github/workflows/build-firewall.yml:1-43` — beze změn (build context stejný)

### Soubory k odstranění

- `services/firewall/squid.conf` — nahrazeno mitmproxy addonem
- `services/firewall/manager/logparser.py` — mitmproxy loguje přímo, blocked domény se berou z `llm_decisions` tabulky

### Soubory BEZ změn (důležité)

- `generator/src/templates/base/devcontainer.json.ejs` — proxy konfigurace se nemění (port 3128 zůstává)
- `generator/src/generator.js` — generátor nepotřebuje změny (nové env vars jdou přímo do docker-compose.yml.ejs template)
- `generator/src/templates/base/Dockerfile.ejs` — CA cert je runtime-only (init-firewall.sh), ne build-time

## Implementační fáze

### Fáze 1: Přechod ze Squid na mitmproxy

Nahrazení Squid proxy za mitmproxy se zachováním stávající funkcionality (whitelist-only, bez LLM).

- Nový Dockerfile s `python:3.12-slim` + mitmproxy
- Základní `firewall_addon.py` — whitelist check, blokace neznámých domén
- Nový `entrypoint.sh` — start mitmproxy + FastAPI
- CA certifikát generování a distribuce do devcontaineru
- Úprava `init-firewall.sh.ejs` — instalace CA certu
- Úprava `docker-compose.yml.ejs` — sdílený volume pro CA cert
- Adaptace `logparser.py` nebo jeho nahrazení (mitmproxy loguje jinak)
- Odstranění `squid.conf`
- Očekávaný výsledek: **funkčně ekvivalentní** stávajícímu řešení, jen na mitmproxy
- Závislosti: žádné
- [ ] Nový Dockerfile (base image, závislosti)
- [ ] Základní mitmproxy addon (whitelist only)
- [ ] Entrypoint script
- [ ] CA cert distribuce
- [ ] Generator template úpravy
- [ ] Smoke testy

### Fáze 2: Rule engine, auth a granulární pravidla

Přidání rule engine s podporou domain, URL pattern a HTTP method pravidel. Git push blokace. Auth na management API.

- Nový modul `rule_engine.py` s in-memory snapshot (reload při mutaci)
- Regex patterny pre-kompilované s `re2` (backtracking-safe), max 200 znaků
- DB tabulka `rules` + migrace + indexy
- Import `whitelist-default.txt` do rules při prvním startu (idempotentní)
- Import `EXTRA_DOMAINS` env var do rules při startu (zachování zpětné kompatibility)
- API endpointy pro rules CRUD (s `MANAGER_AUTH_TOKEN` auth)
- Auth middleware: Bearer token na všechny management endpointy, `POST /api/request` + `GET /api/requests/{id}` zůstávají bez auth
- Dashboard sekce pro správu pravidel
- Hardcoded block rule: `*/git-receive-pack` → deny (git push ochrana)
- Integrace do `firewall_addon.py`
- Schválení escalated requestu developerem → automaticky vytvoří allow rule v rules tabulce
- Očekávaný výsledek: granulární pravidla fungují, git push blokován, API chráněno tokenem
- Závislosti: Fáze 1
- [ ] Rule engine modul (in-memory, re2)
- [ ] DB schema + migrace + indexy
- [ ] Auth middleware (MANAGER_AUTH_TOKEN)
- [ ] EXTRA_DOMAINS migrace do rules
- [ ] API endpointy
- [ ] Dashboard UI
- [ ] Git push blokace
- [ ] Testy

### Fáze 3: LLM evaluace + základní escalation UI

Integrace Azure OpenAI API pro automatické vyhodnocování neznámých požadavků. Základní UI pro escalated requests.

- Nový modul `llm_evaluator.py` s Azure OpenAI klientem (GPT-5.4-mini, reasoning_effort: none)
- Timeout 5s, fallback na escalate
- Concurrency gate: `asyncio.Semaphore(LLM_MAX_CONCURRENT)` (default 5)
- Deduplication: `asyncio.Event` per domain — concurrent requests na stejný domain čekají na první evaluaci
- Prompt design a testování
- `decision_cache.py` — LRU cache s TTL (`cachetools.TTLCache(maxsize=10000)`), POST/PUT/PATCH s body nikdy z cache
- DB tabulka `llm_decisions` pro audit trail + indexy + retention policy (30 dní)
- Body credential scan (regex, prvních 64KB) jako krok před LLM — match → automatic deny
- Integrace do `firewall_addon.py` — async LLM call v request hooku
- Rozšíření `POST /api/request` o LLM pre-evaluaci (fast-track s reason) — nový response contract (viz výše)
- Úprava requests tabulky (llm_decision, llm_reasoning sloupce)
- **Escalated Requests UI v dashboardu** — developer musí mít možnost schválit/zamítnout escalated requests (bez toho je Fáze 3 neúplná)
- Úprava ERR_BLOCKED → JSON 403 response s instrukcemi pro Claude
- SQLite WAL mode pro concurrent access (mitmproxy addon + FastAPI manager)
- Očekávaný výsledek: LLM automaticky vyhodnocuje neznámé requesty, developer řeší jen escalated
- Závislosti: Fáze 1, Fáze 2
- [ ] LLM evaluator modul (Azure OpenAI)
- [ ] Concurrency gate + deduplication
- [ ] Decision cache (LRU, TTL)
- [ ] Body credential scan
- [ ] DB schema pro decisions + retention
- [ ] Integrace do addon
- [ ] Fast-track přes /api/request + nový response contract
- [ ] Escalated requests UI v dashboardu
- [ ] JSON 403 error responses
- [ ] SQLite WAL mode
- [ ] Prompt tuning

### Fáze 4: Rozšířený dashboard a audit

Rozšíření dashboardu o pokročilé filtrování, statistiky a vylepšený UX. Základní escalation UI je již ve Fázi 3.

- LLM decisions audit log s filtrováním (domain, decision type, časové rozmezí)
- API endpointy pro decisions (paginated list default 50, stats)
- Statistiky: auto-approved, auto-denied, escalated za 24h/7d
- Vyhledávání v decisions logu
- Očekávaný výsledek: developer má plný přehled a analytiku o LLM rozhodnutích
- Závislosti: Fáze 3
- [ ] Decisions API endpointy (paginated)
- [ ] Dashboard UI rozšíření (filtrování, vyhledávání)
- [ ] Statistiky
- [ ] Dokumentace

## Rizika a mitigace

| Riziko | Dopad | Pravděpodobnost | Mitigace |
|--------|-------|-----------------|----------|
| LLM false positive (schválí exfiltraci) | Vysoký — únik dat | Nízká | Konzervativní prompt (při pochybách escalate), audit log, hardcoded block rules pro known patterns (git push), body credential scan |
| LLM false negative (zablokuje legitimní request) | Střední — zpomalení práce | Střední | Escalate na developera (ne hard deny), developer může přidat allow rule |
| LLM API latence (>5s) | Střední — zpomalení requestů | Nízká | Timeout 5s s fallback na escalate, cache pro opakované domény |
| LLM API výpadek | Vysoký — proxy nefunguje | Nízká | Fallback: při nedostupnosti API → escalate vše (funguje jako dnes). Request je okamžitě blokován (403), NIKDY neprojde |
| mitmproxy CA cert — tools nepodporují custom CA | Střední — broken workflows | Střední | Runtime instalace + SSL env vars (`NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`, `GIT_SSL_CAINFO`) |
| Certificate pinning (Go binaries, Electron) | Střední — specifické tools selhávají | Nízká | Pro konkrétní domény lze přidat passthrough rule (mitmproxy `ignore_hosts` option) |
| npm install burst (20+ novel domains) | Střední — zpomalení | Střední | Concurrency cap (5 in-flight), deduplication per domain, pre-seed common CDN patterns v rules |
| mitmproxy performance — velké downloady | Nízký | Nízká | Whitelisted domény skip body buffering (allow v rule engine → no body read). mitmproxy streaming mode pro velké responses |
| Azure OpenAI náklady | Nízký | Nízká | Cache s 1h TTL, GPT-5.4-mini je levný, reasoning_effort: none |
| Body truncation — LLM nevidí celý payload | Střední — může přehlédnout exfiltraci ve velké body | Nízká | Regex credential scan na prvních 64KB PŘED LLM. Pro velké body (>64KB): skip regex, spoléhat na domain/URL rules |
| SQLite concurrent writes | Nízký — database is locked | Střední | WAL mode + retry logic. mitmproxy addon a FastAPI přistupují ke stejné DB |
| ReDoS v path_pattern pravidlech | Střední — proxy hang | Nízká | `re2` engine (no backtracking), max 200 znaků, validace při insertu |

## Testování

### Unit testy

- `rule_engine.py` — match/no-match pro domain, path_prefix, path_pattern pravidla
- `rule_engine.py` — priorita pravidel (block > allow)
- `rule_engine.py` — git-receive-pack blokace
- `llm_evaluator.py` — parsování LLM odpovědi (validní JSON, nevalidní JSON, timeout)
- `llm_evaluator.py` — truncace body, filtrování headers
- `decision_cache.py` — cache hit, miss, TTL expiry
- `database.py` — rules CRUD, decisions CRUD, migrace

### Integrační / manuální testy

- End-to-end: request na whitelisted domain → projde okamžitě (bez LLM)
- End-to-end: request na neznámý safe domain → LLM approve → projde (~1-2s)
- End-to-end: request s tokeny v body → LLM deny → zablokován
- End-to-end: `git push` → zablokován (rule engine, bez LLM)
- End-to-end: `git pull/fetch` → projde (whitelisted)
- End-to-end: LLM escalate → pending request v dashboardu → developer approve → retry projde
- End-to-end: Claude `POST /api/request` s reason → LLM evaluace s reason kontextem
- Dashboard: CRUD pravidel, decisions log, statistiky
- CA certifikát: pip install, npm install, curl HTTPS — vše funguje přes mitmproxy
- Fallback: LLM API nedostupné → vše escalate (chová se jako aktuální řešení)
- URL pattern: `vault.azure.net/secrets/kv-dovera-local/` povoleno, `vault.azure.net/other/` → LLM evaluace

### Verifikace

```bash
# Build a spuštění
cd services/firewall && docker build -t cc-remote-firewall:test .

# Unit testy
cd services/firewall/manager && python -m pytest

# Smoke test — proxy funguje
curl -x http://localhost:3128 https://api.anthropic.com/v1/models

# Smoke test — git push blokován
curl -x http://localhost:3128 -X POST https://github.com/user/repo.git/git-receive-pack
# → 403

# Smoke test — unknown domain → LLM evaluace
curl -x http://localhost:3128 https://docs.python.org/3/library/asyncio.html
# → 200 (LLM auto-approve)

# Kontrola — žádné hardcoded API klíče
grep -r "sk-ant-" services/firewall/
```

## Poznámky

- **Idempotence:** Rule engine pravidla a whitelist-default.txt se importují při prvním startu. Opakované restarty nesmí duplikovat pravidla (check existence before insert).
- **Zpětná kompatibilita:** Port 3128 zůstává, HTTP_PROXY/HTTPS_PROXY env vars beze změn. Devcontainer nevyžaduje úpravy kromě CA certifikátu (runtime).
- **EXTRA_DOMAINS migrace:** `EXTRA_DOMAINS` env var je zachována. Při startu se domény z ní importují do rules tabulky jako allow rules (stejně jako whitelist-default.txt). Existující docker-compose konfigurace funguje beze změn.
- **Body scanning:** Regex credential scan na prvních 64KB body jako defense-in-depth. Match → automatic deny. Ale hlavní ochrana je LLM evaluace celého request kontextu — regex je triviálně obejitelný (base64, šifrování).
- **Cache granularita:** Cache klíč je `(domain, method, path)`. POST/PUT/PATCH s body se NIKDY neservírují z cache — vždy se re-evaluují LLM. Toto zabraňuje cache poisoningu (GET schválí domain, pak POST s credentials projde z cache).
- **LLM_ENABLED=false:** Při vypnutém LLM se systém chová jako vylepšený Squid — rule engine + escalate vše neznámé. Umožňuje deployment bez Azure API klíče.
- **Migrace:** Stávající whitelist soubor se při prvním startu nové verze importuje do rules tabulky jako allow pravidla. Stávající requests v DB zůstávají.
- **Azure API key distribuce:** Klíč jde do firewall kontejneru (ne devcontaineru). Devcontainer ho nevidí — nemůže ho exfiltrovat.
- **mitmproxy vs Squid image size:** mitmproxy je větší (~200MB vs ~50MB pro Squid). Akceptovatelný trade-off za funkionalitu.
- **Whitelisted domains — no body buffering:** Pro domény matchující allow rule v rule engine: addon pustí request okamžitě BEZ čtení `flow.request.content`. Toto je kritické pro performance při `npm install` / `pip install` (stovky requestů na whitelisted registry).
- **Developer schválí escalated request:** Schválení vytvoří allow rule v rules tabulce → budoucí requesty na stejný domain projdou přes rule engine bez LLM. Developer tak "trénuje" systém.
- **Distribuce nových default domén:** `whitelist-default.txt` se importuje jen při prvním startu. Nové domény v budoucích verzích image se přidají přes diff — import jen domén, které ještě nejsou v rules tabulce.

## Reference

- [mitmproxy dokumentace — addon API](https://docs.mitmproxy.org/stable/addons/examples/)
- [mitmproxy — certifikáty](https://docs.mitmproxy.org/stable/concepts/certificates/)
- [Azure OpenAI Service](https://learn.microsoft.com/en-us/azure/ai-services/openai/)
- [ExitBox — AI agent sandbox](https://medium.com/@cloud-exit/introducing-exitbox-run-ai-coding-agents-in-complete-isolation-6013fb5bdd06)
- [INNOQ — dev sandbox network isolation](https://www.innoq.com/en/blog/2026/03/dev-sandbox-network/)
- [Claude Code sandboxing docs](https://code.claude.com/docs/en/sandboxing)
- [Anthropic — secure deployment](https://platform.claude.com/docs/en/agent-sdk/secure-deployment)
- [google-re2 — safe regex](https://github.com/google/re2)
- Stávající implementace: `services/firewall/` v tomto repozitáři
