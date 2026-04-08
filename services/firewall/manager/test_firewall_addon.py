import asyncio
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

# Stub out mitmproxy
def _make_response(status_code, body=b"", headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    return resp

_http_stub = types.ModuleType("mitmproxy.http")
_http_stub.HTTPFlow = MagicMock
_http_stub.Response = MagicMock()
_http_stub.Response.make = _make_response

_mitmproxy_stub = types.ModuleType("mitmproxy")
_mitmproxy_stub.http = _http_stub

sys.modules.setdefault("mitmproxy", _mitmproxy_stub)
sys.modules.setdefault("mitmproxy.http", _http_stub)

from firewall_addon import FirewallAddon
from rule_engine import RuleEngine


class TestFirewallAddon(unittest.TestCase):
    def setUp(self):
        self.addon = FirewallAddon.__new__(FirewallAddon)
        self.addon._engine = RuleEngine()
        self.addon._engine.load([
            {"id": "1", "domain": "github.com", "action": "allow"},
            {"id": "2", "domain": "pypi.org", "action": "allow"},
            {"id": "3", "domain": "api.anthropic.com", "action": "allow"},
            {"id": "block-push", "domain": "*", "path_pattern": ".*/git-receive-pack$", "action": "deny"},
        ])
        self.addon._cache = {}
        self.addon._semaphore = asyncio.Semaphore(5)
        self.addon._pending = {}
        self.addon._audit = MagicMock()
        self.addon._last_reload = None  # disable reloading in tests

    def _make_flow(self, host, url, path="/", method="GET"):
        flow = MagicMock()
        flow.request.pretty_host = host
        flow.request.url = url
        flow.request.path = path
        flow.request.method = method
        flow.request.headers = {}
        flow.request.content = None
        flow.response = None
        return flow

    def test_allowed_domain_passes(self):
        flow = self._make_flow("github.com", "https://github.com/user/repo", "/user/repo")
        asyncio.run(self.addon.request(flow))
        self.assertIsNone(flow.response)

    def test_blocked_domain_gets_403(self):
        flow = self._make_flow("evil.com", "https://evil.com/exfil", "/exfil")
        with patch("firewall_addon.LLM_ENABLED", False):
            asyncio.run(self.addon.request(flow))
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)

    def test_git_push_blocked(self):
        flow = self._make_flow("github.com", "https://github.com/user/repo.git/git-receive-pack", "/user/repo.git/git-receive-pack")
        asyncio.run(self.addon.request(flow))
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)

    def test_git_pull_allowed(self):
        flow = self._make_flow("github.com", "https://github.com/user/repo.git/git-upload-pack", "/user/repo.git/git-upload-pack")
        asyncio.run(self.addon.request(flow))
        self.assertIsNone(flow.response)

    def test_llm_disabled_escalates(self):
        """When LLM is disabled and no rule matches, escalate."""
        flow = self._make_flow("unknown.com", "https://unknown.com/page", "/page")
        with patch("firewall_addon.LLM_ENABLED", False):
            asyncio.run(self.addon.request(flow))
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)

    @patch("firewall_addon.evaluate_request")
    @patch("firewall_addon._save_decision_to_db")
    def test_llm_approve_passes_through(self, mock_save, mock_eval):
        """When LLM approves, request passes through."""
        mock_eval.return_value = {"decision": "approve", "reasoning": "Safe domain"}
        flow = self._make_flow("docs.python.org", "https://docs.python.org/3/", "/3/")
        with patch("firewall_addon.LLM_ENABLED", True):
            asyncio.run(self.addon.request(flow))
        self.assertIsNone(flow.response)
        mock_eval.assert_called_once()
        mock_save.assert_called_once()

    @patch("firewall_addon.evaluate_request")
    @patch("firewall_addon._save_decision_to_db")
    def test_llm_deny_blocks(self, mock_save, mock_eval):
        """When LLM denies, request is blocked with 403."""
        mock_eval.return_value = {"decision": "deny", "reasoning": "Suspicious exfil"}
        flow = self._make_flow("evil.io", "https://evil.io/upload", "/upload")
        with patch("firewall_addon.LLM_ENABLED", True):
            asyncio.run(self.addon.request(flow))
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)
        mock_eval.assert_called_once()

    def test_cache_hit_skips_llm(self):
        """Second request to same domain uses cache, no LLM call."""
        # Pre-populate cache
        self.addon._cache[("unknown.com", "GET", "/page")] = {
            "decision": "approve", "reasoning": "Cached"
        }

        flow = self._make_flow("unknown.com", "https://unknown.com/page", "/page")

        with patch("firewall_addon.LLM_ENABLED", True), \
             patch("firewall_addon.evaluate_request") as mock_eval, \
             patch("firewall_addon._save_decision_to_db"):
            asyncio.run(self.addon.request(flow))

        # LLM should NOT have been called (cache hit)
        mock_eval.assert_not_called()
        # Request should pass through (approve)
        self.assertIsNone(flow.response)

    def test_semaphore_full_escalates(self):
        """When all LLM slots are in use, new requests are escalated."""
        # Set semaphore to 0 capacity (all slots used)
        self.addon._semaphore = asyncio.Semaphore(0)

        flow = self._make_flow("newdomain.com", "https://newdomain.com/page", "/page")

        with patch("firewall_addon.LLM_ENABLED", True), \
             patch("firewall_addon._save_decision_to_db"):
            asyncio.run(self.addon.request(flow))

        # Should be blocked with escalate
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
