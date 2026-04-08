# Firewall LLM Triage — Phase 3: LLM Evaluation + Audit

> **For agentic workers:** REQUIRED SUB-SKILL: Use cf-powers:subagent-driven-development (recommended) or cf-powers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LLM-based automatic evaluation of unknown requests via Azure OpenAI (GPT-5.4-mini), with escalation UI, auto-approval review flow, and JSONL forensic audit log.

**Architecture:** When a request doesn't match any rule, the mitmproxy addon calls Azure OpenAI to evaluate it. The LLM sees domain, URL, method, headers, and body (~4KB). It returns approve/deny/escalate. Results are cached in-memory (TTLCache on the addon). All requests are logged to a JSONL audit file on a separate Docker volume. Escalated requests appear in the dashboard for developer review. Auto-approved requests have a pending review status that the developer can confirm or block.

**Tech Stack:** Python 3.12, Azure OpenAI (`openai` SDK), FastAPI, SQLite, mitmproxy addon, cachetools

**Index:** [`plan-index.md`](./2026-04-08-firewall-llm-triage-plan-index.md)

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `services/firewall/manager/llm_evaluator.py` | Azure OpenAI API client, prompt construction | Create |
| `services/firewall/manager/test_llm_evaluator.py` | Tests for LLM evaluator | Create |
| `services/firewall/manager/audit_logger.py` | JSONL append logger for forensic audit | Create |
| `services/firewall/manager/test_audit_logger.py` | Tests for audit logger | Create |
| `services/firewall/manager/firewall_addon.py` | Add LLM evaluation, cache, concurrency, dedup, audit logging | Modify |
| `services/firewall/manager/database.py` | Add `llm_decisions` table with indexes + retention | Modify |
| `services/firewall/manager/main.py` | Add escalation + review endpoints | Modify |
| `services/firewall/manager/templates/index.html` | Add Escalated Requests + Auto-Approved Review sections | Modify |
| `services/firewall/manager/requirements.txt` | Add `openai`, `cachetools` | Modify |
| `generator/src/templates/base/docker-compose.yml.ejs` | Add Azure env vars, audit volume | Modify |

---

### Task 1: LLM evaluator module with tests

**Files:**
- Create: `services/firewall/manager/llm_evaluator.py`
- Create: `services/firewall/manager/test_llm_evaluator.py`

Tests to write (mock the OpenAI client):
- Valid approve response → returns `{"decision": "approve", "reasoning": "..."}`
- Valid deny response → returns deny
- Valid escalate response → returns escalate
- Invalid JSON from LLM → returns escalate (safe fallback)
- Timeout → returns escalate
- API error → returns escalate
- Body truncation at ~4KB
- Headers filtered (no auth tokens in prompt)

Implementation:
- `async def evaluate_request(domain, url, method, headers, body, project_context) -> dict`
- Uses `openai.AsyncAzureOpenAI` client
- System prompt from analysis
- `reasoning_effort="none"` parameter
- Timeout via `asyncio.wait_for(..., timeout=LLM_TIMEOUT)`

### Task 2: Audit logger module with tests

**Files:**
- Create: `services/firewall/manager/audit_logger.py`
- Create: `services/firewall/manager/test_audit_logger.py`

Tests:
- Log entry is valid JSONL (one line, parseable JSON)
- Contains all required fields (ts, domain, url, method, headers, body_sha256, body_preview, decision, reasoning, source, review_status, latency_ms)
- body_sha256 is SHA256 of full body
- body_preview truncated to ~4KB
- Append mode (file grows, existing content preserved)

Implementation:
- `AuditLogger` class with `log(domain, url, method, headers, body, decision, reasoning, source, review_status, latency_ms)`
- Writes to `AUDIT_LOG_PATH` (default `/audit/firewall.jsonl`)
- Opens file in append mode per write (simple, no buffering needed for dev traffic)

### Task 3: Database — llm_decisions table

**Files:**
- Modify: `services/firewall/manager/database.py`

Add:
- `CREATE TABLE IF NOT EXISTS llm_decisions (...)` with all indexes from analysis
- `create_decision(domain, url, method, decision, reasoning, source, review_status) -> dict`
- `list_decisions(limit=50, offset=0) -> list[dict]`
- `list_pending_review() -> list[dict]`
- `list_escalated() -> list[dict]`
- `update_review_status(decision_id, status) -> dict|None`
- `cleanup_old_decisions(days=30)` — retention policy
- Enable WAL mode: `PRAGMA journal_mode=WAL` at init

### Task 4: Update mitmproxy addon — LLM integration

**Files:**
- Modify: `services/firewall/manager/firewall_addon.py`

Add to `FirewallAddon`:
- `self._cache = cachetools.TTLCache(maxsize=10000, ttl=int(os.environ.get("LLM_CACHE_TTL", "3600")))`
- `self._semaphore = asyncio.Semaphore(int(os.environ.get("LLM_MAX_CONCURRENT", "5")))`
- `self._pending: dict[str, asyncio.Event] = {}` for deduplication
- `self._audit = AuditLogger()`

Update `request()` hook to follow the full decision flow from analysis:
1. Rule engine check (existing from Phase 2)
2. Cache check (skip for POST/PUT/PATCH with body)
3. Deduplication check
4. Concurrency gate
5. LLM evaluation
6. Apply decision + log to audit + log to DB

If `LLM_ENABLED=false`, skip steps 2-5 and escalate everything.

### Task 5: Escalation + review API endpoints

**Files:**
- Modify: `services/firewall/manager/main.py`

Add endpoints:
- `GET /api/escalated` — list escalated decisions (decision=escalate, not yet approved/denied)
- `POST /api/escalated/{id}/approve` — approve → create allow rule in rules table
- `POST /api/escalated/{id}/deny` — deny (mark as denied)
- `GET /api/decisions` — paginated list of all decisions
- `GET /api/decisions/pending-review` — auto-approved, pending developer review
- `POST /api/decisions/{id}/review` — mark as reviewed
- `POST /api/decisions/{id}/block` — mark as blocked → create deny rule

### Task 6: Dashboard — Escalated + Review sections

**Files:**
- Modify: `services/firewall/manager/templates/index.html`

Add sections:
1. **Auto-Approved (pending review)** — table with domain, URL, method, body preview, LLM reasoning, Reviewed/Block buttons
2. **Escalated Requests** — table with domain, URL, reasoning, Approve/Deny buttons
3. **Recent Decisions** — simple list of last 20 LLM decisions

### Task 7: Requirements + generator templates

**Files:**
- Modify: `services/firewall/manager/requirements.txt` — add `openai>=1.0`, `cachetools>=5.0`
- Modify: `generator/src/templates/base/docker-compose.yml.ejs` — add Azure env vars (`AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION`, `PROJECT_CONTEXT`, `AUDIT_LOG_PATH`), add `audit-log` volume

### Task 8: Docker build + end-to-end test

Build image, verify:
- Whitelisted domain passes immediately (no LLM call)
- Unknown safe domain → LLM approve → passes (~1-2s delay)
- Request with credentials in body → LLM deny → 403
- LLM escalate → appears in dashboard → developer approves → creates allow rule
- Auto-approved request appears in "pending review" → developer clicks Reviewed
- JSONL audit log grows with each request
- `LLM_ENABLED=false` → all unknown domains escalated (no LLM calls)
