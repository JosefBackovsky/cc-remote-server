import asyncio
import os
import tempfile
import unittest
from pathlib import Path

# Create temp DB file for tests (avoids :memory: isolation issues across async calls)
_test_db_dir = tempfile.mkdtemp()
_test_db_path = Path(_test_db_dir) / "test.db"
os.environ["DB_PATH"] = str(_test_db_path)

# Import after setting env var so DB_PATH reads it at module level
import database
database.DB_PATH = _test_db_path


def fresh_db():
    """Delete the test DB file and re-initialise schema."""
    if _test_db_path.exists():
        _test_db_path.unlink()
    asyncio.run(database.init_db())


# ---------------------------------------------------------------------------
# Rules CRUD
# ---------------------------------------------------------------------------

class TestRulesCRUD(unittest.TestCase):
    def setUp(self):
        fresh_db()

    def test_create_rule(self):
        result = asyncio.run(database.create_rule(domain="example.com", action="allow"))
        self.assertEqual(result["domain"], "example.com")
        self.assertEqual(result["action"], "allow")
        self.assertIn("id", result)
        self.assertIn("created_at", result)
        self.assertIn("updated_at", result)

    def test_list_rules(self):
        asyncio.run(database.create_rule(domain="a.com", action="allow"))
        asyncio.run(database.create_rule(domain="b.com", action="deny"))
        asyncio.run(database.create_rule(domain="c.com", action="allow"))
        rules = asyncio.run(database.list_rules())
        self.assertEqual(len(rules), 3)
        domains = [r["domain"] for r in rules]
        self.assertIn("a.com", domains)
        self.assertIn("b.com", domains)
        self.assertIn("c.com", domains)

    def test_get_rule(self):
        created = asyncio.run(database.create_rule(domain="get.com", action="allow"))
        fetched = asyncio.run(database.get_rule(created["id"]))
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["id"], created["id"])
        self.assertEqual(fetched["domain"], "get.com")

    def test_get_rule_not_found(self):
        result = asyncio.run(database.get_rule("nonexistent000"))
        self.assertIsNone(result)

    def test_update_rule(self):
        created = asyncio.run(database.create_rule(domain="old.com", action="allow"))
        updated = asyncio.run(database.update_rule(created["id"], domain="new.com"))
        self.assertIsNotNone(updated)
        self.assertEqual(updated["domain"], "new.com")
        self.assertEqual(updated["action"], "allow")

    def test_update_rule_partial(self):
        created = asyncio.run(database.create_rule(
            domain="partial.com", action="allow", description="original"
        ))
        updated = asyncio.run(database.update_rule(created["id"], description="changed"))
        self.assertIsNotNone(updated)
        self.assertEqual(updated["domain"], "partial.com")
        self.assertEqual(updated["action"], "allow")
        self.assertEqual(updated["description"], "changed")

    def test_update_rule_not_found(self):
        result = asyncio.run(database.update_rule("nonexistent000", domain="x.com"))
        self.assertIsNone(result)

    def test_delete_rule(self):
        created = asyncio.run(database.create_rule(domain="del.com", action="deny"))
        deleted = asyncio.run(database.delete_rule(created["id"]))
        self.assertTrue(deleted)
        gone = asyncio.run(database.get_rule(created["id"]))
        self.assertIsNone(gone)

    def test_delete_rule_not_found(self):
        result = asyncio.run(database.delete_rule("nonexistent000"))
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# import_whitelist
# ---------------------------------------------------------------------------

class TestImportWhitelist(unittest.TestCase):
    def setUp(self):
        fresh_db()

    def test_import_whitelist(self):
        count = asyncio.run(database.import_whitelist(["alpha.com", "beta.com", "gamma.com"]))
        self.assertEqual(count, 3)
        rules = asyncio.run(database.list_rules())
        domains = {r["domain"] for r in rules}
        self.assertEqual(domains, {"alpha.com", "beta.com", "gamma.com"})
        for rule in rules:
            self.assertEqual(rule["action"], "allow")

    def test_import_whitelist_idempotent(self):
        asyncio.run(database.import_whitelist(["x.com", "y.com"]))
        count2 = asyncio.run(database.import_whitelist(["x.com", "y.com"]))
        self.assertEqual(count2, 0)
        rules = asyncio.run(database.list_rules())
        self.assertEqual(len(rules), 2)

    def test_import_whitelist_skips_existing(self):
        asyncio.run(database.create_rule(domain="existing.com", action="deny"))
        count = asyncio.run(database.import_whitelist(["existing.com", "fresh.com"]))
        self.assertEqual(count, 1)
        rules = asyncio.run(database.list_rules())
        self.assertEqual(len(rules), 2)
        domains = {r["domain"] for r in rules}
        self.assertIn("fresh.com", domains)
        self.assertIn("existing.com", domains)
        # Original action preserved
        existing = next(r for r in rules if r["domain"] == "existing.com")
        self.assertEqual(existing["action"], "deny")


# ---------------------------------------------------------------------------
# Decisions CRUD
# ---------------------------------------------------------------------------

def _make_decision(**kwargs):
    defaults = dict(
        domain="test.com",
        url="https://test.com/api",
        method="GET",
        decision="approve",
        reasoning="looks fine",
        source="llm",
        cached=False,
        review_status=None,
    )
    defaults.update(kwargs)
    return asyncio.run(database.create_decision(**defaults))


class TestDecisionsCRUD(unittest.TestCase):
    def setUp(self):
        fresh_db()

    def test_create_decision(self):
        result = _make_decision(domain="create.com", decision="approve", review_status="pending")
        self.assertIn("id", result)
        self.assertEqual(result["domain"], "create.com")
        self.assertEqual(result["decision"], "approve")
        self.assertEqual(result["review_status"], "pending")
        self.assertIn("timestamp", result)
        self.assertIsNone(result["reviewed_at"])

    def test_list_decisions_pagination(self):
        for i in range(5):
            _make_decision(domain=f"d{i}.com")
        page = asyncio.run(database.list_decisions(limit=2, offset=0))
        self.assertEqual(len(page), 2)

    def test_list_decisions_newest_first(self):
        for i in range(3):
            _make_decision(domain=f"order{i}.com")
        decisions = asyncio.run(database.list_decisions())
        timestamps = [d["timestamp"] for d in decisions]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_list_pending_review(self):
        _make_decision(decision="approve", review_status="pending", domain="pending.com")
        _make_decision(decision="approve", review_status=None, domain="notstatus.com")
        pending = asyncio.run(database.list_pending_review())
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["domain"], "pending.com")

    def test_list_pending_review_excludes_deny(self):
        _make_decision(decision="deny", review_status="pending", domain="denied.com")
        pending = asyncio.run(database.list_pending_review())
        self.assertEqual(len(pending), 0)

    def test_list_escalated(self):
        _make_decision(decision="escalate", review_status=None, domain="esc.com")
        _make_decision(decision="escalate", review_status="approved", domain="handled.com")
        escalated = asyncio.run(database.list_escalated())
        self.assertEqual(len(escalated), 1)
        self.assertEqual(escalated[0]["domain"], "esc.com")

    def test_list_escalated_excludes_handled(self):
        _make_decision(decision="escalate", review_status="approved", domain="handled.com")
        escalated = asyncio.run(database.list_escalated())
        self.assertEqual(len(escalated), 0)

    def test_update_review_status(self):
        created = _make_decision(decision="approve", review_status="pending")
        updated = asyncio.run(database.update_review_status(created["id"], "reviewed"))
        self.assertIsNotNone(updated)
        self.assertEqual(updated["review_status"], "reviewed")
        self.assertIsNotNone(updated["reviewed_at"])

    def test_update_review_status_not_found(self):
        result = asyncio.run(database.update_review_status("nonexistent000", "reviewed"))
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

class TestCleanup(unittest.TestCase):
    def setUp(self):
        fresh_db()

    def test_cleanup_old_decisions(self):
        # Just verify it runs without error and returns an integer
        _make_decision(domain="old.com")
        result = asyncio.run(database.cleanup_old_decisions(days=30))
        self.assertIsInstance(result, int)


# ---------------------------------------------------------------------------
# WAL mode
# ---------------------------------------------------------------------------

class TestWALMode(unittest.TestCase):
    def setUp(self):
        fresh_db()

    def test_wal_mode_enabled(self):
        async def check_wal():
            async with database.get_db() as db:
                cursor = await db.execute("PRAGMA journal_mode")
                row = await cursor.fetchone()
                return row[0]

        mode = asyncio.run(check_wal())
        self.assertEqual(mode, "wal")


if __name__ == "__main__":
    unittest.main()
