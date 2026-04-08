import json
import tempfile
import unittest
from pathlib import Path
from audit_logger import AuditLogger


class TestAuditLogger(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = Path(self.tmpdir) / "test.jsonl"
        self.logger = AuditLogger(path=self.log_path)

    def test_log_creates_valid_jsonl(self):
        self.logger.log(
            domain="example.com", url="https://example.com/path", method="GET",
            headers={"Accept": "text/html"}, body=None, decision="approve",
            reasoning="Safe", source="llm", latency_ms=100,
        )
        lines = self.log_path.read_text().strip().split("\n")
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["domain"], "example.com")
        self.assertEqual(entry["decision"], "approve")

    def test_log_contains_all_fields(self):
        self.logger.log(
            domain="x.com", url="https://x.com/", method="POST",
            headers={"Content-Type": "application/json"}, body=b'{"key": "value"}',
            decision="deny", reasoning="Suspicious", source="llm",
            review_status="pending", latency_ms=1500,
        )
        entry = json.loads(self.log_path.read_text().strip())
        required = ["ts", "domain", "url", "method", "headers", "body_sha256",
                     "body_preview", "decision", "reasoning", "source",
                     "review_status", "latency_ms"]
        for field in required:
            self.assertIn(field, entry, f"Missing field: {field}")

    def test_body_sha256_is_hash_of_full_body(self):
        import hashlib
        body = b"test body content"
        expected_hash = hashlib.sha256(body).hexdigest()
        self.logger.log(
            domain="x.com", url="https://x.com/", method="POST",
            headers={}, body=body, decision="approve", reasoning="OK", source="rule",
        )
        entry = json.loads(self.log_path.read_text().strip())
        self.assertEqual(entry["body_sha256"], expected_hash)

    def test_body_preview_truncated(self):
        body = b"x" * 8000
        self.logger.log(
            domain="x.com", url="https://x.com/", method="POST",
            headers={}, body=body, decision="approve", reasoning="OK", source="llm",
        )
        entry = json.loads(self.log_path.read_text().strip())
        self.assertLessEqual(len(entry["body_preview"]), 4096)

    def test_append_mode(self):
        self.logger.log(domain="a.com", url="https://a.com/", method="GET",
                        headers={}, body=None, decision="approve", reasoning="OK", source="rule")
        self.logger.log(domain="b.com", url="https://b.com/", method="GET",
                        headers={}, body=None, decision="deny", reasoning="Bad", source="llm")
        lines = self.log_path.read_text().strip().split("\n")
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["domain"], "a.com")
        self.assertEqual(json.loads(lines[1])["domain"], "b.com")

    def test_null_body_empty_preview_and_hash(self):
        import hashlib
        empty_hash = hashlib.sha256(b"").hexdigest()
        self.logger.log(domain="x.com", url="https://x.com/", method="GET",
                        headers={}, body=None, decision="approve", reasoning="OK", source="rule")
        entry = json.loads(self.log_path.read_text().strip())
        self.assertEqual(entry["body_sha256"], empty_hash)
        self.assertEqual(entry["body_preview"], "")


if __name__ == "__main__":
    unittest.main()
