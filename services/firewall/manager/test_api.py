import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Set up temp DB BEFORE importing app — DB_PATH is read at module level
_test_db_dir = tempfile.mkdtemp()
_test_db_path = Path(_test_db_dir) / "test_api.db"
os.environ["DB_PATH"] = str(_test_db_path)
os.environ["MANAGER_AUTH_TOKEN"] = "test-secret-token"

import database
database.DB_PATH = _test_db_path

from starlette.testclient import TestClient
from main import app

AUTH_HEADER = {"Authorization": "Bearer test-secret-token"}


class TestAPI(unittest.TestCase):
    def setUp(self):
        if _test_db_path.exists():
            _test_db_path.unlink()
        asyncio.run(database.init_db())
        self.client = TestClient(app)

    # --- Auth tests ---

    def test_rules_requires_auth(self):
        """GET /api/rules without token should return 401."""
        resp = self.client.get("/api/rules")
        self.assertEqual(resp.status_code, 401)

    def test_rules_with_auth(self):
        """GET /api/rules with valid token should return 200."""
        resp = self.client.get("/api/rules", headers=AUTH_HEADER)
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    def test_dashboard_no_auth(self):
        """GET / should return 200 without any auth."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)

    def test_dev_mode_no_token(self):
        """When MANAGER_AUTH_TOKEN is empty, all endpoints work without auth."""
        import main as main_module
        original_token = main_module.MANAGER_AUTH_TOKEN
        try:
            main_module.MANAGER_AUTH_TOKEN = ""
            resp = self.client.get("/api/rules")
            self.assertEqual(resp.status_code, 200)
        finally:
            main_module.MANAGER_AUTH_TOKEN = original_token

    # --- Rules CRUD tests ---

    def test_create_rule(self):
        """POST /api/rules with valid body should return 201."""
        resp = self.client.post(
            "/api/rules",
            json={"domain": "example.com", "action": "allow", "description": "test rule"},
            headers=AUTH_HEADER,
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["domain"], "example.com")
        self.assertEqual(data["action"], "allow")
        self.assertIn("id", data)

    def test_list_rules(self):
        """Creating 2 rules then listing should return exactly 2 (plus the git-receive-pack rule from migration)."""
        # The lifespan migration creates a git-receive-pack deny rule on fresh DB
        # Count existing rules first
        resp = self.client.get("/api/rules", headers=AUTH_HEADER)
        existing_count = len(resp.json())

        self.client.post(
            "/api/rules",
            json={"domain": "alpha.com", "action": "allow"},
            headers=AUTH_HEADER,
        )
        self.client.post(
            "/api/rules",
            json={"domain": "beta.com", "action": "deny"},
            headers=AUTH_HEADER,
        )

        resp = self.client.get("/api/rules", headers=AUTH_HEADER)
        self.assertEqual(resp.status_code, 200)
        rules = resp.json()
        self.assertEqual(len(rules), existing_count + 2)

    def test_delete_rule(self):
        """Create a rule then DELETE it — should return 200 with deleted: true."""
        create_resp = self.client.post(
            "/api/rules",
            json={"domain": "todelete.com", "action": "allow"},
            headers=AUTH_HEADER,
        )
        rule_id = create_resp.json()["id"]

        resp = self.client.delete(f"/api/rules/{rule_id}", headers=AUTH_HEADER)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["deleted"])

    def test_delete_rule_not_found(self):
        """DELETE on a nonexistent rule ID should return 404."""
        resp = self.client.delete("/api/rules/nonexistent-id", headers=AUTH_HEADER)
        self.assertEqual(resp.status_code, 404)

    def test_create_rule_long_pattern(self):
        """path_pattern longer than 200 chars should return 400."""
        long_pattern = "a" * 201
        resp = self.client.post(
            "/api/rules",
            json={"domain": "example.com", "action": "allow", "path_pattern": long_pattern},
            headers=AUTH_HEADER,
        )
        self.assertEqual(resp.status_code, 400)

    # --- Escalation tests ---

    def test_approve_escalated_creates_rule(self):
        """Approving an escalated decision should create an allow rule for its domain."""
        decision = asyncio.run(database.create_decision(
            domain="escalated.com",
            url="https://escalated.com/api",
            method="GET",
            decision="escalate",
            reasoning="needs review",
            source="llm",
        ))
        decision_id = decision["id"]

        resp = self.client.post(f"/api/escalated/{decision_id}/approve", headers=AUTH_HEADER)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "approved")
        self.assertEqual(data["domain"], "escalated.com")

        # Verify the allow rule was created
        rules_resp = self.client.get("/api/rules", headers=AUTH_HEADER)
        rules = rules_resp.json()
        allow_rules = [r for r in rules if r["domain"] == "escalated.com" and r["action"] == "allow"]
        self.assertEqual(len(allow_rules), 1)

    # --- Decisions tests ---

    def test_list_decisions(self):
        """Creating decisions in DB then GET /api/decisions should return them."""
        asyncio.run(database.create_decision(
            domain="site1.com",
            url="https://site1.com/",
            method="GET",
            decision="approve",
            reasoning="allowed",
            source="llm",
        ))
        asyncio.run(database.create_decision(
            domain="site2.com",
            url="https://site2.com/",
            method="POST",
            decision="deny",
            reasoning="blocked",
            source="llm",
        ))

        resp = self.client.get("/api/decisions", headers=AUTH_HEADER)
        self.assertEqual(resp.status_code, 200)
        decisions = resp.json()
        domains = [d["domain"] for d in decisions]
        self.assertIn("site1.com", domains)
        self.assertIn("site2.com", domains)

    def test_review_decision(self):
        """POST /api/decisions/{id}/review should update review_status to 'reviewed'."""
        decision = asyncio.run(database.create_decision(
            domain="reviewme.com",
            url="https://reviewme.com/",
            method="GET",
            decision="approve",
            reasoning="auto-approved",
            source="llm",
            review_status="pending",
        ))
        decision_id = decision["id"]

        resp = self.client.post(f"/api/decisions/{decision_id}/review", headers=AUTH_HEADER)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "reviewed")
        self.assertEqual(data["id"], decision_id)

        # Verify status updated in DB
        updated = asyncio.run(database.get_decision(decision_id))
        self.assertEqual(updated["review_status"], "reviewed")

    def test_block_decision_creates_deny_rule(self):
        """POST /api/decisions/{id}/block should create a deny rule for the domain."""
        decision = asyncio.run(database.create_decision(
            domain="blockme.com",
            url="https://blockme.com/bad",
            method="GET",
            decision="approve",
            reasoning="mistakenly approved",
            source="llm",
            review_status="pending",
        ))
        decision_id = decision["id"]

        resp = self.client.post(f"/api/decisions/{decision_id}/block", headers=AUTH_HEADER)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "blocked")
        self.assertEqual(data["domain"], "blockme.com")

        # Verify deny rule was created
        rules_resp = self.client.get("/api/rules", headers=AUTH_HEADER)
        rules = rules_resp.json()
        deny_rules = [r for r in rules if r["domain"] == "blockme.com" and r["action"] == "deny"]
        self.assertEqual(len(deny_rules), 1)


if __name__ == "__main__":
    unittest.main()
