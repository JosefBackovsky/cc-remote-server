# Firewall LLM Triage — Phase 2: Rule Engine + Auth

> **For agentic workers:** REQUIRED SUB-SKILL: Use cf-powers:subagent-driven-development (recommended) or cf-powers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace flat whitelist file with a granular rule engine stored in SQLite, add bearer token auth on management API, and block git push via URL pattern rule.

**Architecture:** Rules are stored in SQLite `rules` table and loaded into an in-memory snapshot at startup and on every mutation. The mitmproxy addon checks rules from memory (zero DB queries on the hot path). API endpoints for CRUD are protected by `MANAGER_AUTH_TOKEN`. The existing whitelist file is imported into rules on first start. A hardcoded block rule for `git-receive-pack` prevents git push.

**Tech Stack:** Python 3.12, FastAPI, SQLite, mitmproxy addon

**Index:** [`plan-index.md`](./2026-04-08-firewall-llm-triage-plan-index.md)

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `services/firewall/manager/rule_engine.py` | In-memory rule matching (domain, path_prefix, path_pattern) | Create |
| `services/firewall/manager/test_rule_engine.py` | Tests for rule engine | Create |
| `services/firewall/manager/database.py` | Add `rules` table, CRUD functions | Modify |
| `services/firewall/manager/main.py` | Add Rules CRUD endpoints + auth middleware, remove legacy endpoints | Modify |
| `services/firewall/manager/firewall_addon.py` | Replace whitelist file check with rule engine check | Modify |
| `services/firewall/manager/whitelist.py` | Delete (replaced by rule engine) | Delete |
| `services/firewall/manager/templates/index.html` | Add Rules management UI section | Modify |
| `generator/src/templates/base/docker-compose.yml.ejs` | Add `MANAGER_AUTH_TOKEN` env var | Modify |

---

### Task 1: Rule engine module with tests

**Files:**
- Create: `services/firewall/manager/rule_engine.py`
- Create: `services/firewall/manager/test_rule_engine.py`

Tests to write:
- Exact domain match (allow/deny)
- `path_prefix` match (e.g. `vault.azure.net` + `/secrets/kv-dovera-local/`)
- `path_pattern` regex match (e.g. `.*/git-receive-pack$`)
- Priority: block rules beat allow rules
- No match → returns `None` (proceed to LLM)
- Regex length limit (>200 chars rejected at load time)
- Git push blocked: `github.com` + `/user/repo.git/git-receive-pack` → deny

TDD: write all tests first, then implement `rule_engine.py` with:
- `RuleEngine` class with `load(rules: list[dict])` and `check(domain, path, method) -> str|None`
- Pre-compiled regexes
- Block rules checked first, then allow rules

### Task 2: Database — rules table + CRUD

**Files:**
- Modify: `services/firewall/manager/database.py`

Add:
- `CREATE TABLE IF NOT EXISTS rules (...)` with index on domain
- `create_rule(domain, action, path_pattern, path_prefix, description) -> dict`
- `get_rule(rule_id) -> dict|None`
- `list_rules() -> list[dict]`
- `update_rule(rule_id, ...) -> dict|None`
- `delete_rule(rule_id) -> bool`
- `import_whitelist(domains: list[str])` — idempotent import of domain list as allow rules

### Task 3: Whitelist migration at startup

**Files:**
- Modify: `services/firewall/entrypoint.sh` or startup logic in `main.py`

At first start:
1. Check if `rules` table is empty
2. If empty: read `/data/whitelist.txt` (or fallback to `/opt/whitelist-default.txt`)
3. Import each domain as an allow rule
4. Import `EXTRA_DOMAINS` env var as allow rules
5. Add hardcoded block rule: `domain=*`, `path_pattern=.*/git-receive-pack$`, `action=deny`

### Task 4: Auth middleware

**Files:**
- Modify: `services/firewall/manager/main.py`

Add FastAPI dependency that checks `Authorization: Bearer <MANAGER_AUTH_TOKEN>` on all endpoints except `GET /` (dashboard). If `MANAGER_AUTH_TOKEN` is not set, log a warning and allow all requests (dev mode).

### Task 5: Rules CRUD API endpoints

**Files:**
- Modify: `services/firewall/manager/main.py`

Add endpoints:
- `GET /api/rules` — list all rules
- `POST /api/rules` — create rule (validate regex length ≤200)
- `PUT /api/rules/{id}` — update rule
- `DELETE /api/rules/{id}` — delete rule

Remove legacy endpoints:
- `POST /api/request`, `GET /api/requests/{id}`, `POST /api/requests/{id}/approve`, `POST /api/requests/{id}/deny`
- `POST /api/approve`, `DELETE /api/revoke`, `GET /api/whitelist`, `GET /api/blocked`

### Task 6: Update mitmproxy addon to use rule engine

**Files:**
- Modify: `services/firewall/manager/firewall_addon.py`

Replace `_load_whitelist()` / `_is_whitelisted()` with `RuleEngine`. The addon loads rules from DB at startup and reloads when notified (via a shared flag or reload endpoint).

### Task 7: Delete whitelist.py

**Files:**
- Delete: `services/firewall/manager/whitelist.py`

### Task 8: Dashboard — Rules management UI

**Files:**
- Modify: `services/firewall/manager/templates/index.html`

Add a "Rules" section with:
- Table showing all rules (domain, path_pattern/path_prefix, action, description)
- Add rule form (domain, action, optional path_pattern/path_prefix, description)
- Delete button per rule
- Remove "Claude's Requests" section (endpoint removed)
- Remove "Blocked Domains" section (logparser removed)

### Task 9: Generator template — MANAGER_AUTH_TOKEN

**Files:**
- Modify: `generator/src/templates/base/docker-compose.yml.ejs`

Add `MANAGER_AUTH_TOKEN` to the firewall service environment section.

### Task 10: Docker build + smoke test

Build image, verify:
- Rules CRUD works via curl with auth token
- Git push is blocked (`curl -X POST .../git-receive-pack` → 403)
- Whitelisted domains pass through
- Dashboard loads with rules section
