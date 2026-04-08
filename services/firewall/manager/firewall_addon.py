"""mitmproxy addon for domain-based whitelist filtering.

Phase 1: functional equivalent of Squid whitelist.
Reads whitelist from whitelist.py (shared with FastAPI), reloads periodically,
blocks non-whitelisted domains with 403.
"""

import json
import logging
import time

try:
    from mitmproxy import http
except ImportError:  # pragma: no cover — only absent in unit-test environments
    http = None  # type: ignore[assignment]

from whitelist import read_whitelist

logger = logging.getLogger("firewall")

RELOAD_INTERVAL = 5  # seconds


def _is_whitelisted(domain: str, whitelist: set[str]) -> bool:
    """Check if domain is allowed by the whitelist.

    Supports exact match and .suffix match (e.g. .github.com matches sub.github.com).
    """
    domain = domain.lower()
    if domain in whitelist:
        return True
    for entry in whitelist:
        if entry.startswith(".") and domain.endswith(entry):
            return True
    return False


class WhitelistAddon:
    def __init__(self):
        self._whitelist = set(d.lower() for d in read_whitelist())
        self._last_reload = time.monotonic()
        logger.info("Loaded %d whitelist entries", len(self._whitelist))

    def _maybe_reload(self):
        """Reload whitelist every RELOAD_INTERVAL seconds.

        Note: there is a potential ~5s window where a newly-approved domain
        is still blocked. This matches the old Squid checksum watcher behavior.
        """
        last = getattr(self, "_last_reload", None)
        if last is None:
            return  # __init__ not called (e.g. unit tests using __new__)
        now = time.monotonic()
        if now - last >= RELOAD_INTERVAL:
            self._whitelist = set(d.lower() for d in read_whitelist())
            self._last_reload = now

    def request(self, flow: http.HTTPFlow) -> None:
        self._maybe_reload()
        domain = flow.request.pretty_host
        if _is_whitelisted(domain, self._whitelist):
            return  # allowed
        # Block with 403
        flow.response = http.Response.make(
            403,
            json.dumps({
                "blocked": True,
                "domain": domain,
                "decision": "blocked",
                "reasoning": f"Domain {domain} is not on the whitelist",
            }),
            {"Content-Type": "application/json"},
        )
        logger.warning("Blocked: %s %s", flow.request.method, flow.request.url)


addons = [WhitelistAddon()]
