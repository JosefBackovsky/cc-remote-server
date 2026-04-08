import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub out mitmproxy so tests run without it installed.
# http.Response.make returns a MagicMock with status_code set from the first arg.
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

from firewall_addon import WhitelistAddon


class TestWhitelistAddon(unittest.TestCase):
    def setUp(self):
        self.addon = WhitelistAddon.__new__(WhitelistAddon)
        self.addon._whitelist = {"github.com", "pypi.org", "api.anthropic.com"}

    def test_allowed_domain_passes(self):
        flow = MagicMock()
        flow.request.pretty_host = "github.com"
        flow.request.url = "https://github.com/user/repo"
        flow.response = None
        self.addon.request(flow)
        self.assertIsNone(flow.response)

    def test_blocked_domain_gets_403(self):
        flow = MagicMock()
        flow.request.pretty_host = "evil.com"
        flow.request.url = "https://evil.com/exfil"
        flow.response = None
        self.addon.request(flow)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)

    def test_subdomain_not_matched(self):
        """Whitelist contains github.com, but sub.github.com should be blocked."""
        flow = MagicMock()
        flow.request.pretty_host = "sub.github.com"
        flow.request.url = "https://sub.github.com/path"
        flow.response = None
        self.addon.request(flow)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)

    def test_parent_domain_whitelisted_with_dot_prefix(self):
        """Whitelist entry .github.com should match sub.github.com."""
        self.addon._whitelist = {".github.com", "pypi.org"}
        flow = MagicMock()
        flow.request.pretty_host = "sub.github.com"
        flow.request.url = "https://sub.github.com/path"
        flow.response = None
        self.addon.request(flow)
        self.assertIsNone(flow.response)


if __name__ == "__main__":
    unittest.main()
