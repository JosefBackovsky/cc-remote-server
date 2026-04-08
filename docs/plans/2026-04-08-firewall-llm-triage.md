# Firewall LLM Triage — Automatické vyhodnocování síťových požadavků pomocí LLM

## Popis

Rozšíření Firewall služby o inteligentní vrstvu, která pomocí LLM (Claude Sonnet 4.6) automaticky vyhodnocuje síťové požadavky z devcontaineru. Místo aktuálního modelu „vše zablokovat → developer manuálně schválí" přechází systém na inline evaluaci: neznámý požadavek se pozdrží, LLM ho vyhodnotí, a pokud je bezpečný, projde bez blokace.

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

1. mitmproxy vygeneruje CA cert do `/data/certs/mitmproxy-ca-cert.pem`
2. Certifikát se namountuje do devcontaineru přes shared volume
3. `init-firewall.sh` ho přidá do trust store (`update-ca-certificates`)
4. Nástroje jako `pip`, `npm`, `curl` pak důvěřují MITM certifikátu

### mitmproxy addon — `firewall_addon.py`

Hlavní komponenta — Python addon pro mitmproxy, který implementuje veškerou logiku:

**Hooks:**
- `async def request(self, flow: http.HTTPFlow)` — hlavní hook, volaný pro každý request
- Addon má přístup k: `flow.request.url`, `flow.request.headers`, `flow.request.content`, `flow.request.method`

**Rozhodovací logika (v `request` hooku):**

```
1. Parse domain + URL path z flow.request
2. Check static rules (rule engine):
   a. Whitelist match (domain/pattern) → allow
   b. Block rule match (domain/pattern) → deny
3. Check LLM cache (domain/URL → previous decision)
   → hit → apply cached decision
4. Async LLM call (Claude Sonnet 4.6):
   → Send: domain, URL, method, headers, body (truncated), project context
   → Receive: {decision: "approve"|"deny"|"escalate", reasoning: "..."}
5. Apply decision:
   - approve → allow flow, cache result
   - deny → flow.response = HTTP 403, log
   - escalate → flow.response = HTTP 403 s instrukcemi, create pending request
```

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

LLM dostane maximum informací pro rozhodnutí:

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
```

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
```

#### Úprava tabulky `requests`

Přidání sloupce pro LLM rozhodnutí:

```sql
ALTER TABLE requests ADD COLUMN llm_decision TEXT;      -- approve|deny|escalate|NULL
ALTER TABLE requests ADD COLUMN llm_reasoning TEXT;      -- LLM reasoning text
```

### Změny v servisní vrstvě

#### Nový modul: `llm_evaluator.py`

Zodpovědný za volání Claude API a parsování odpovědi.

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
    """Returns {"decision": "approve"|"deny"|"escalate", "reasoning": "..."}"""
```

#### Nový modul: `rule_engine.py`

Vyhodnocení statických pravidel (whitelist, block rules).

Signatury:

```python
def check_rules(domain: str, path: str, method: str) -> str | None:
    """Returns "allow"|"deny"|None (None = no rule matched, proceed to LLM)"""

def load_rules() -> list[dict]:
    """Load all rules from DB"""
```

#### Nový modul: `decision_cache.py`

In-memory cache pro LLM rozhodnutí s TTL.

Signatury:

```python
def get_cached_decision(domain: str, path: str) -> dict | None:
    """Returns cached LLM decision or None"""

def cache_decision(domain: str, path: str, decision: dict, ttl: int = 3600):
    """Cache an LLM decision"""
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
# Rules CRUD
GET    /api/rules              # list all rules
POST   /api/rules              # create rule
PUT    /api/rules/{id}         # update rule
DELETE /api/rules/{id}         # delete rule

# LLM decisions audit log
GET    /api/decisions           # list LLM decisions (paginated)
GET    /api/decisions/stats     # aggregated stats

# Updated request submission (now triggers LLM evaluation)
POST   /api/request            # Claude fast-track with reason
```

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
| `ANTHROPIC_API_KEY` | (povinné) | API klíč pro Claude Sonnet 4.6 |
| `LLM_MODEL` | `claude-sonnet-4-6-20250514` | Model pro evaluaci |
| `PROJECT_CONTEXT` | (prázdné) | Popis projektu pro LLM kontext |
| `LLM_CACHE_TTL` | `3600` | TTL cache pro LLM rozhodnutí (sekundy) |
| `LLM_ENABLED` | `true` | Zapnout/vypnout LLM evaluaci (false = vše escalate) |
| `MITMPROXY_CA_DIR` | `/data/certs` | Adresář pro CA certifikát |

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
- `services/firewall/manager/requirements.txt:1-4` — přidání `mitmproxy`, `anthropic`
- `services/firewall/whitelist-default.txt:1-25` — zachováno, importuje se do rules při prvním startu
- `services/firewall/ERR_BLOCKED:1-15` — úprava textu (mitmproxy místo Squid)
- `services/firewall/README.md:1-36` — aktualizace dokumentace
- `generator/src/templates/base/docker-compose.yml.ejs:57-73` — nové env vars (ANTHROPIC_API_KEY, PROJECT_CONTEXT), sdílený volume pro CA cert
- `generator/src/templates/base/init-firewall.sh.ejs:1-31` — přidání instalace CA certifikátu z shared volume
- `generator/src/templates/base/Dockerfile.ejs` — přidání `ca-certificates` balíčku, kopie CA certu
- `.github/workflows/build-firewall.yml:1-43` — beze změn (build context stejný)

### Soubory BEZ změn (důležité)

- `services/firewall/squid.conf` — **odstraní se** (nahrazeno mitmproxy addonem)
- `generator/src/templates/base/devcontainer.json.ejs` — proxy konfigurace se nemění (port 3128 zůstává)
- `generator/src/generator.js` — generátor nepotřebuje změny (nové env vars jdou přes stávající mechanismus)
- `services/firewall/manager/logparser.py` — **odstraní se** (mitmproxy loguje přímo, nepotřebujeme parsovat Squid logy)

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

### Fáze 2: Rule engine a granulární pravidla

Přidání rule engine s podporou domain, URL pattern a HTTP method pravidel. Git push blokace.

- Nový modul `rule_engine.py`
- DB tabulka `rules` + migrace
- Import `whitelist-default.txt` do rules při prvním startu
- API endpointy pro rules CRUD
- Dashboard sekce pro správu pravidel
- Hardcoded block rule: `*/git-receive-pack` → deny (git push ochrana)
- Integrace do `firewall_addon.py`
- Očekávaný výsledek: granulární pravidla fungují, git push blokován
- Závislosti: Fáze 1
- [ ] Rule engine modul
- [ ] DB schema + migrace
- [ ] API endpointy
- [ ] Dashboard UI
- [ ] Git push blokace
- [ ] Testy

### Fáze 3: LLM evaluace

Integrace Claude API pro automatické vyhodnocování neznámých požadavků.

- Nový modul `llm_evaluator.py` s Claude API klientem
- Prompt design a testování
- `decision_cache.py` — in-memory cache s TTL
- DB tabulka `llm_decisions` pro audit trail
- Integrace do `firewall_addon.py` — async LLM call v request hooku
- Rozšíření `POST /api/request` o LLM pre-evaluaci (fast-track s reason)
- Úprava requests tabulky (llm_decision, llm_reasoning sloupce)
- Očekávaný výsledek: LLM automaticky vyhodnocuje neznámé requesty
- Závislosti: Fáze 1, Fáze 2
- [ ] LLM evaluator modul
- [ ] Decision cache
- [ ] DB schema pro decisions
- [ ] Integrace do addon
- [ ] Fast-track přes /api/request
- [ ] Prompt tuning

### Fáze 4: Dashboard a audit

Rozšíření dashboardu o LLM decisions, statistiky a vylepšený UX.

- Dashboard sekce: escalated requests, LLM decisions log, statistiky
- API endpointy pro decisions (paginated list, stats)
- Filtrování a vyhledávání v decisions logu
- Očekávaný výsledek: developer má plný přehled o LLM rozhodnutích
- Závislosti: Fáze 3
- [ ] Decisions API endpointy
- [ ] Dashboard UI rozšíření
- [ ] Statistiky
- [ ] Dokumentace

## Rizika a mitigace

| Riziko | Dopad | Pravděpodobnost | Mitigace |
|--------|-------|-----------------|----------|
| LLM false positive (schválí exfiltraci) | Vysoký — únik dat | Nízká | Konzervativní prompt (při pochybách escalate), audit log, hardcoded block rules pro known patterns (git push, token patterns) |
| LLM false negative (zablokuje legitimní request) | Střední — zpomalení práce | Střední | Escalate na developera (ne hard deny), developer může přidat allow rule |
| LLM API latence (>5s) | Střední — zpomalení requestů | Nízká | Timeout s fallback na escalate, cache pro opakované domény |
| LLM API výpadek | Vysoký — proxy nefunguje | Nízká | Fallback: při nedostupnosti API → escalate vše (funguje jako dnes) |
| mitmproxy CA cert — tools nepodporují custom CA | Střední — broken workflows | Střední | Testovat s pip, npm, curl, git; v init-firewall.sh nastavit `NODE_EXTRA_CA_CERTS`, `REQUESTS_CA_BUNDLE` |
| mitmproxy performance overhead | Nízký — MITM je dražší než Squid forward | Nízká | mitmproxy zvládá stovky concurrent connections; dev traffic je nízký |
| Anthropic API náklady | Nízký | Nízká | Cache s 1h TTL, většina traffic jde na known domains (cache hit), Sonnet je levný |
| Body truncation — LLM nevidí celý payload | Střední — může přehlédnout exfiltraci ve velké body | Nízká | Skenovat celý body na token/credential patterns regex PŘED truncací pro LLM |

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

- **Idempotence:** Rule engine pravidla a whitelist-default.txt se importují při prvním startu. Opakované restarty nesmí duplikovat pravidla.
- **Zpětná kompatibilita:** Port 3128 zůstává, HTTP_PROXY/HTTPS_PROXY env vars beze změn. Devcontainer nevyžaduje úpravy kromě CA certifikátu.
- **Body scanning:** Před odesláním body do LLM se celý payload prohledá regex patterny na tokeny/credentials. Pokud match → automatic deny bez LLM (rychlejší, levnější, spolehlivější).
- **Cache granularita:** Cache klíč je `(domain, path_prefix)`, ne plný URL s query params. Tím se cachují rozhodnutí pro celé endpointy, ne individuální requesty.
- **LLM_ENABLED=false:** Při vypnutém LLM se systém chová jako vylepšený Squid — rule engine + escalate vše neznámé. Umožňuje deployment bez API klíče.
- **Migrace:** Stávající whitelist soubor se při prvním startu nové verze importuje do rules tabulky jako allow pravidla. Stávající requests v DB zůstávají.
- **ANTHROPIC_API_KEY distribuce:** Klíč jde do firewall kontejneru (ne devcontaineru). Devcontainer ho nevidí — nemůže ho exfiltrovat.
- **mitmproxy vs Squid image size:** mitmproxy je větší (~200MB vs ~50MB pro Squid). Akceptovatelný trade-off za funkionalitu.

## Reference

- [mitmproxy dokumentace — addon API](https://docs.mitmproxy.org/stable/addons/examples/)
- [mitmproxy — certifikáty](https://docs.mitmproxy.org/stable/concepts/certificates/)
- [ExitBox — AI agent sandbox](https://medium.com/@cloud-exit/introducing-exitbox-run-ai-coding-agents-in-complete-isolation-6013fb5bdd06)
- [INNOQ — dev sandbox network isolation](https://www.innoq.com/en/blog/2026/03/dev-sandbox-network/)
- [Claude Code sandboxing docs](https://code.claude.com/docs/en/sandboxing)
- [Anthropic — secure deployment](https://platform.claude.com/docs/en/agent-sdk/secure-deployment)
- Stávající implementace: `services/firewall/` v tomto repozitáři
