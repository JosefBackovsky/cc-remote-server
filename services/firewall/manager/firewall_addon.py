"""mitmproxy addon with rule engine + LLM evaluation.

Phase 3: full decision flow with caching, concurrency, dedup, audit.
"""

import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone

try:
    from mitmproxy import http
except ImportError:
    http = None

try:
    import cachetools
except ImportError:
    cachetools = None

from rule_engine import RuleEngine
from llm_evaluator import evaluate_request
from audit_logger import AuditLogger

logger = logging.getLogger("firewall")

DB_PATH = os.environ.get("DB_PATH", "/data/approval.db")
RELOAD_INTERVAL = 5
LLM_ENABLED = os.environ.get("LLM_ENABLED", "true").lower() == "true"
LLM_CACHE_TTL = int(os.environ.get("LLM_CACHE_TTL", "3600"))
LLM_MAX_CONCURRENT = int(os.environ.get("LLM_MAX_CONCURRENT", "5"))


def _load_rules_from_db() -> list[dict]:
    """Load rules from SQLite (synchronous)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM rules ORDER BY created_at")
        rules = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rules
    except Exception as e:
        # Warning, not error — mitmproxy exits on error-level logs during startup.
        # This happens on first start before init_db() creates the tables.
        # The addon will reload rules after 5s (by which time tables exist).
        logger.warning("Failed to load rules from DB: %s", e)
        return []


def _save_decision_to_db(domain, url, method, decision, reasoning, source,
                         cached=False, review_status=None):
    """Save LLM decision to DB (synchronous, fire-and-forget)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        decision_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO llm_decisions (id, timestamp, domain, url, method, decision, reasoning, source, cached, review_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (decision_id, now, domain, url, method, decision, reasoning, source, cached, review_status),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("Failed to save decision: %s", e)


def _make_403(domain, decision, reasoning):
    """Create a 403 response."""
    return http.Response.make(
        403,
        json.dumps({"blocked": True, "domain": domain, "decision": decision, "reasoning": reasoning}),
        {"Content-Type": "application/json"},
    )


class FirewallAddon:
    def __init__(self):
        self._engine = RuleEngine()
        rules = _load_rules_from_db()
        self._engine.load(rules)
        self._last_reload = time.monotonic()

        # LLM cache: TTLCache(maxsize, ttl)
        if cachetools:
            self._cache = cachetools.TTLCache(maxsize=10000, ttl=LLM_CACHE_TTL)
        else:
            self._cache = {}

        # Concurrency control
        self._semaphore = asyncio.Semaphore(LLM_MAX_CONCURRENT)
        self._pending = {}  # domain -> asyncio.Event for dedup

        # Audit
        self._audit = AuditLogger()

        logger.info("Loaded %d rules, LLM enabled=%s", len(rules), LLM_ENABLED)

    def _maybe_reload(self):
        """Reload rules every RELOAD_INTERVAL seconds."""
        last = getattr(self, "_last_reload", None)
        if last is None:
            return
        now = time.monotonic()
        if now - last >= RELOAD_INTERVAL:
            rules = _load_rules_from_db()
            self._engine.load(rules)
            self._last_reload = now

    def _get_headers_dict(self, flow):
        """Extract headers as a plain dict."""
        try:
            return dict(flow.request.headers)
        except Exception:
            return {}

    def _get_body(self, flow):
        """Get request body bytes, or None."""
        try:
            return flow.request.content
        except Exception:
            return None

    async def request(self, flow: http.HTTPFlow) -> None:
        start_ms = time.monotonic()
        self._maybe_reload()

        domain = flow.request.pretty_host
        path = flow.request.path
        method = flow.request.method
        url = flow.request.url

        # Step 1: Rule engine
        rule_decision = self._engine.check(domain, path)
        if rule_decision == "allow":
            self._audit.log(domain=domain, url=url, method=method,
                            headers=self._get_headers_dict(flow), body=None,
                            decision="allow", reasoning="Allowed by rule",
                            source="rule", latency_ms=self._elapsed(start_ms))
            return

        if rule_decision == "deny":
            flow.response = _make_403(domain, "deny", f"Blocked by rule: {domain}{path}")
            self._audit.log(domain=domain, url=url, method=method,
                            headers=self._get_headers_dict(flow), body=self._get_body(flow),
                            decision="deny", reasoning=f"Blocked by rule: {domain}{path}",
                            source="rule", latency_ms=self._elapsed(start_ms))
            logger.warning("Denied by rule: %s %s", method, url)
            return

        # Step 2: LLM enabled?
        if not LLM_ENABLED:
            flow.response = _make_403(domain, "escalate", "LLM disabled, escalating")
            self._audit.log(domain=domain, url=url, method=method,
                            headers=self._get_headers_dict(flow), body=self._get_body(flow),
                            decision="escalate", reasoning="LLM disabled",
                            source="disabled", latency_ms=self._elapsed(start_ms))
            _save_decision_to_db(domain, url, method, "escalate", "LLM disabled", "disabled")
            return

        # Step 3: Cache check
        body = self._get_body(flow)
        has_body = method in ("POST", "PUT", "PATCH") and body
        cache_key = (domain.lower(), method, path)

        if not has_body and cache_key in self._cache:
            cached = self._cache[cache_key]
            self._apply_decision(flow, domain, cached["decision"], cached["reasoning"],
                                 source="cache", start_ms=start_ms, body=body)
            return

        # Step 4-6: LLM evaluation with dedup and concurrency
        await self._evaluate_with_llm(flow, domain, url, path, method, body, cache_key,
                                       has_body, start_ms)

    async def _evaluate_with_llm(self, flow, domain, url, path, method, body,
                                  cache_key, has_body, start_ms):
        headers = self._get_headers_dict(flow)

        # Deduplication: wait if same domain is already being evaluated
        if domain in self._pending:
            event = self._pending[domain]
            await event.wait()
            # After wait, check cache
            if cache_key in self._cache:
                cached = self._cache[cache_key]
                self._apply_decision(flow, domain, cached["decision"], cached["reasoning"],
                                     source="cache", start_ms=start_ms, body=body)
                return

        # Set dedup event
        event = asyncio.Event()
        self._pending[domain] = event

        # Concurrency gate — non-blocking check via internal counter
        # We access the semaphore's internal state to avoid blocking.
        # If all slots are taken, escalate immediately.
        try:
            can_acquire = self._semaphore._value > 0
        except AttributeError:
            can_acquire = True  # fallback: assume available
        if not can_acquire:
            event.set()
            self._pending.pop(domain, None)
            flow.response = _make_403(domain, "escalate", "Too many concurrent evaluations")
            self._audit.log(domain=domain, url=url, method=method, headers=headers, body=body,
                            decision="escalate", reasoning="Concurrency limit reached",
                            source="concurrency_limit", latency_ms=self._elapsed(start_ms))
            _save_decision_to_db(domain, url, method, "escalate",
                                 "Concurrency limit reached", "concurrency_limit")
            return

        try:
            async with self._semaphore:
                result = await evaluate_request(
                    domain=domain, url=url, method=method,
                    headers=headers, body=body,
                )
        finally:
            event.set()
            self._pending.pop(domain, None)

        decision = result["decision"]
        reasoning = result["reasoning"]

        # Cache (skip for POST/PUT/PATCH with body, except deny which always caches)
        if not has_body or decision == "deny":
            self._cache[cache_key] = result

        # Determine review_status
        review_status = "pending" if decision == "approve" else None

        # Save to DB
        _save_decision_to_db(domain, url, method, decision, reasoning, "llm",
                             review_status=review_status)

        # Apply
        self._apply_decision(flow, domain, decision, reasoning, source="llm",
                             start_ms=start_ms, body=body, review_status=review_status)

    def _apply_decision(self, flow, domain, decision, reasoning, source,
                        start_ms, body=None, review_status=None):
        headers = self._get_headers_dict(flow)
        url = flow.request.url
        method = flow.request.method
        latency = self._elapsed(start_ms)

        if decision == "approve":
            self._audit.log(domain=domain, url=url, method=method, headers=headers, body=body,
                            decision="approve", reasoning=reasoning, source=source,
                            review_status=review_status, latency_ms=latency)
            return  # allow through

        # deny or escalate
        flow.response = _make_403(domain, decision, reasoning)
        self._audit.log(domain=domain, url=url, method=method, headers=headers, body=body,
                        decision=decision, reasoning=reasoning, source=source,
                        review_status=review_status, latency_ms=latency)
        logger.info("%s: %s %s (%s)", decision.upper(), method, url, reasoning[:100])

    def _elapsed(self, start_ms):
        return int((time.monotonic() - start_ms) * 1000)


addons = [FirewallAddon()]
