import unittest
from rule_engine import RuleEngine


class TestRuleEngine(unittest.TestCase):

    def test_exact_domain_allow(self):
        engine = RuleEngine()
        engine.load([{"id": "1", "domain": "docs.python.org", "action": "allow"}])
        self.assertEqual(engine.check("docs.python.org", "/3/library/asyncio.html"), "allow")

    def test_exact_domain_deny(self):
        engine = RuleEngine()
        engine.load([{"id": "1", "domain": "evil.com", "action": "deny"}])
        self.assertEqual(engine.check("evil.com", "/anything"), "deny")

    def test_no_match_returns_none(self):
        engine = RuleEngine()
        engine.load([{"id": "1", "domain": "docs.python.org", "action": "allow"}])
        self.assertIsNone(engine.check("unknown.com", "/"))

    def test_case_insensitive_domain(self):
        engine = RuleEngine()
        engine.load([{"id": "1", "domain": "GitHub.com", "action": "allow"}])
        self.assertEqual(engine.check("github.com", "/"), "allow")
        self.assertEqual(engine.check("GITHUB.COM", "/"), "allow")

    def test_path_prefix_match(self):
        engine = RuleEngine()
        engine.load([{"id": "1", "domain": "vault.azure.net", "path_prefix": "/secrets/kv-dovera-local/", "action": "allow"}])
        self.assertEqual(engine.check("vault.azure.net", "/secrets/kv-dovera-local/key1"), "allow")
        self.assertIsNone(engine.check("vault.azure.net", "/secrets/other/key1"))

    def test_path_pattern_match(self):
        engine = RuleEngine()
        engine.load([{"id": "1", "domain": "github.com", "path_pattern": ".*/git-receive-pack$", "action": "deny"}])
        self.assertEqual(engine.check("github.com", "/user/repo.git/git-receive-pack"), "deny")
        self.assertIsNone(engine.check("github.com", "/user/repo.git/git-upload-pack"))

    def test_deny_beats_allow(self):
        """When both deny and allow match, deny wins."""
        engine = RuleEngine()
        engine.load([
            {"id": "1", "domain": "github.com", "action": "allow"},
            {"id": "2", "domain": "github.com", "path_pattern": ".*/git-receive-pack$", "action": "deny"},
        ])
        # git push blocked even though github.com is allowed
        self.assertEqual(engine.check("github.com", "/user/repo.git/git-receive-pack"), "deny")
        # normal github access allowed
        self.assertEqual(engine.check("github.com", "/user/repo"), "allow")

    def test_git_push_blocked(self):
        """The primary use case — git push blocked on any host."""
        engine = RuleEngine()
        engine.load([
            {"id": "1", "domain": "github.com", "action": "allow"},
            {"id": "2", "domain": "gitlab.com", "action": "allow"},
            {"id": "block-push", "domain": "*", "path_pattern": ".*/git-receive-pack$", "action": "deny"},
        ])
        self.assertEqual(engine.check("github.com", "/user/repo.git/git-receive-pack"), "deny")
        self.assertEqual(engine.check("gitlab.com", "/user/repo.git/git-receive-pack"), "deny")
        self.assertEqual(engine.check("github.com", "/user/repo"), "allow")

    def test_wildcard_domain(self):
        """domain='*' matches any domain."""
        engine = RuleEngine()
        engine.load([{"id": "1", "domain": "*", "path_pattern": ".*/git-receive-pack$", "action": "deny"}])
        self.assertEqual(engine.check("anything.com", "/repo.git/git-receive-pack"), "deny")
        self.assertIsNone(engine.check("anything.com", "/other"))

    def test_regex_too_long_skipped(self):
        """Regex patterns > 200 chars are skipped."""
        engine = RuleEngine()
        long_pattern = "a" * 201
        engine.load([{"id": "1", "domain": "x.com", "path_pattern": long_pattern, "action": "deny"}])
        # Rule should be skipped — no match
        self.assertIsNone(engine.check("x.com", "a" * 201))

    def test_empty_rules(self):
        engine = RuleEngine()
        engine.load([])
        self.assertIsNone(engine.check("anything.com", "/"))

    def test_reload_replaces_rules(self):
        engine = RuleEngine()
        engine.load([{"id": "1", "domain": "old.com", "action": "allow"}])
        self.assertEqual(engine.check("old.com", "/"), "allow")
        engine.load([{"id": "2", "domain": "new.com", "action": "allow"}])
        self.assertIsNone(engine.check("old.com", "/"))
        self.assertEqual(engine.check("new.com", "/"), "allow")


if __name__ == "__main__":
    unittest.main()
