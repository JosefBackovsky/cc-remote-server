import sys
import types
import unittest
from unittest.mock import MagicMock

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

    def _make_flow(self, host, url, path="/"):
        flow = MagicMock()
        flow.request.pretty_host = host
        flow.request.url = url
        flow.request.path = path
        flow.request.method = "GET"
        flow.response = None
        return flow

    def test_allowed_domain_passes(self):
        flow = self._make_flow("github.com", "https://github.com/user/repo", "/user/repo")
        self.addon.request(flow)
        self.assertIsNone(flow.response)

    def test_blocked_domain_gets_403(self):
        flow = self._make_flow("evil.com", "https://evil.com/exfil", "/exfil")
        self.addon.request(flow)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)

    def test_git_push_blocked(self):
        flow = self._make_flow("github.com", "https://github.com/user/repo.git/git-receive-pack", "/user/repo.git/git-receive-pack")
        self.addon.request(flow)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)

    def test_git_pull_allowed(self):
        flow = self._make_flow("github.com", "https://github.com/user/repo.git/git-upload-pack", "/user/repo.git/git-upload-pack")
        self.addon.request(flow)
        self.assertIsNone(flow.response)


if __name__ == "__main__":
    unittest.main()
