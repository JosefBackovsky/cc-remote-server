"""mitmproxy addon for domain-based rule engine filtering.

Phase 2: granular rules (domain, path_prefix, path_pattern).
Rules are loaded from SQLite at startup and reloaded periodically.
"""

import json
import logging
import os
import time
import asyncio
import sqlite3

try:
    from mitmproxy import http
except ImportError:
    http = None

from rule_engine import RuleEngine

logger = logging.getLogger("firewall")

DB_PATH = os.environ.get("DB_PATH", "/data/approval.db")
RELOAD_INTERVAL = 5  # seconds


def _load_rules_from_db() -> list[dict]:
    """Load rules from SQLite (synchronous — called from mitmproxy thread)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM rules ORDER BY created_at")
        rules = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rules
    except Exception as e:
        logger.error("Failed to load rules from DB: %s", e)
        return []


class FirewallAddon:
    def __init__(self):
        self._engine = RuleEngine()
        rules = _load_rules_from_db()
        self._engine.load(rules)
        self._last_reload = time.monotonic()
        logger.info("Loaded %d rules from database", len(rules))

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

    def request(self, flow: http.HTTPFlow) -> None:
        self._maybe_reload()
        domain = flow.request.pretty_host
        path = flow.request.path
        decision = self._engine.check(domain, path)

        if decision == "allow":
            return  # pass through

        if decision == "deny":
            flow.response = http.Response.make(
                403,
                json.dumps({
                    "blocked": True,
                    "domain": domain,
                    "decision": "deny",
                    "reasoning": f"Blocked by rule: {domain}{path}",
                }),
                {"Content-Type": "application/json"},
            )
            logger.warning("Denied by rule: %s %s", flow.request.method, flow.request.url)
            return

        # No rule matched — block for now (LLM evaluation comes in Phase 3)
        flow.response = http.Response.make(
            403,
            json.dumps({
                "blocked": True,
                "domain": domain,
                "decision": "escalate",
                "reasoning": f"No rule for domain {domain}, escalating",
            }),
            {"Content-Type": "application/json"},
        )
        logger.info("No rule match, blocking: %s %s", flow.request.method, flow.request.url)


addons = [FirewallAddon()]
