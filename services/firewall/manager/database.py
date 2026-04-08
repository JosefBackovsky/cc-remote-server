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
