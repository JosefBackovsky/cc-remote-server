import os
import aiosqlite
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", "/data/approval.db"))


def get_db():
    return aiosqlite.connect(DB_PATH)


async def init_db():
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        await db.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                path_pattern TEXT,
                path_prefix TEXT,
                action TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_rules_domain ON rules(domain)
        """)
        await db.commit()


async def create_request(domain: str, reason: str) -> dict:
    request_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "INSERT INTO requests (id, domain, reason, status, created_at, updated_at) VALUES (?, ?, ?, 'pending', ?, ?)",
            (request_id, domain, reason, now, now),
        )
        await db.commit()
    return {"id": request_id, "domain": domain, "reason": reason, "status": "pending", "created_at": now}


async def get_request(request_id: str) -> dict | None:
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM requests WHERE id = ?", (request_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)


async def list_requests() -> list[dict]:
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM requests ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_request_status(request_id: str, status: str) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "UPDATE requests SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, request_id),
        )
        await db.commit()
        if cursor.rowcount == 0:
            return None
        return await get_request(request_id)


# --- Rules CRUD ---


async def create_rule(domain: str, action: str, path_pattern: str | None = None,
                      path_prefix: str | None = None, description: str | None = None) -> dict:
    """Create a new rule. Returns the rule dict."""
    rule_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """INSERT INTO rules (id, domain, path_pattern, path_prefix, action, description, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (rule_id, domain, path_pattern, path_prefix, action, description, now, now),
        )
        await db.commit()
    return {
        "id": rule_id, "domain": domain, "path_pattern": path_pattern,
        "path_prefix": path_prefix, "action": action, "description": description,
        "created_at": now, "updated_at": now,
    }


async def get_rule(rule_id: str) -> dict | None:
    """Get a single rule by ID."""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM rules WHERE id = ?", (rule_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)


async def list_rules() -> list[dict]:
    """List all rules, ordered by created_at."""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM rules ORDER BY created_at")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_rule(rule_id: str, domain: str | None = None, action: str | None = None,
                      path_pattern: str | None = None, path_prefix: str | None = None,
                      description: str | None = None) -> dict | None:
    """Update a rule. Returns updated rule or None if not found."""
    existing = await get_rule(rule_id)
    if existing is None:
        return None
    now = datetime.now(timezone.utc).isoformat()
    new_domain = domain if domain is not None else existing["domain"]
    new_action = action if action is not None else existing["action"]
    new_path_pattern = path_pattern if path_pattern is not None else existing["path_pattern"]
    new_path_prefix = path_prefix if path_prefix is not None else existing["path_prefix"]
    new_description = description if description is not None else existing["description"]
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """UPDATE rules SET domain = ?, action = ?, path_pattern = ?, path_prefix = ?,
               description = ?, updated_at = ? WHERE id = ?""",
            (new_domain, new_action, new_path_pattern, new_path_prefix, new_description, now, rule_id),
        )
        await db.commit()
    return await get_rule(rule_id)


async def delete_rule(rule_id: str) -> bool:
    """Delete a rule. Returns True if deleted, False if not found."""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
        await db.commit()
        return cursor.rowcount > 0


async def import_whitelist(domains: list[str]) -> int:
    """Import domains as allow rules. Skips domains that already have a rule.
    Returns count of newly imported rules."""
    existing_rules = await list_rules()
    existing_domains = {r["domain"] for r in existing_rules}
    count = 0
    for domain in domains:
        if domain not in existing_domains:
            await create_rule(domain=domain, action="allow")
            existing_domains.add(domain)
            count += 1
    return count
