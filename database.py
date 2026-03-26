import urllib.parse
from contextlib import asynccontextmanager

import aiomysql
import aiosqlite

from config import settings

# ---------------------------------------------------------------------------
# Detect backend
# ---------------------------------------------------------------------------
USE_MYSQL = bool(settings.mysql_url)


# ---------------------------------------------------------------------------
# MySQL helpers
# ---------------------------------------------------------------------------
_pool: aiomysql.Pool | None = None


def _parse_mysql_url(url: str) -> dict:
    """Parse mysql://user:pass@host:port/db into aiomysql connect kwargs."""
    parsed = urllib.parse.urlparse(url)
    return dict(
        host=parsed.hostname or "localhost",
        port=parsed.port or 3306,
        user=parsed.username or "root",
        password=parsed.password or "",
        db=parsed.path.lstrip("/") or "railway",
    )


async def _get_pool() -> aiomysql.Pool:
    global _pool
    if _pool is None:
        params = _parse_mysql_url(settings.mysql_url)
        _pool = await aiomysql.create_pool(**params, autocommit=True, minsize=1, maxsize=5)
    return _pool


@asynccontextmanager
async def _mysql_conn():
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            yield conn, cur


# ---------------------------------------------------------------------------
# SQLite helpers (local dev fallback)
# ---------------------------------------------------------------------------
def _sqlite_connect():
    return aiosqlite.connect(settings.database_path)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
MYSQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    first_name VARCHAR(255) NOT NULL,
    last_name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(50) NOT NULL UNIQUE,
    company VARCHAR(255),
    job_title VARCHAR(255),
    industry VARCHAR(255),
    reason_for_interest TEXT,
    urgency_score INTEGER DEFAULT 0,
    classification VARCHAR(50) DEFAULT 'unscored',
    rationale TEXT,
    recommended_action TEXT,
    conversation_stage VARCHAR(50) DEFAULT 'new',
    turn_count INTEGER DEFAULT 0,
    slack_message_ts VARCHAR(100),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
"""

MYSQL_MESSAGES_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    lead_id INTEGER NOT NULL,
    direction VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);
"""

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT,
    phone TEXT NOT NULL UNIQUE,
    company TEXT,
    job_title TEXT,
    industry TEXT,
    reason_for_interest TEXT,
    urgency_score INTEGER DEFAULT 0,
    classification TEXT DEFAULT 'unscored',
    rationale TEXT,
    recommended_action TEXT,
    conversation_stage TEXT DEFAULT 'new',
    turn_count INTEGER DEFAULT 0,
    slack_message_ts TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);
CREATE INDEX IF NOT EXISTS idx_messages_lead_id ON messages(lead_id);
"""


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------
async def init_db():
    if USE_MYSQL:
        async with _mysql_conn() as (conn, cur):
            await cur.execute(MYSQL_SCHEMA)
            await cur.execute(MYSQL_MESSAGES_SCHEMA)
            # Create indexes if they don't exist
            try:
                await cur.execute("CREATE INDEX idx_leads_phone ON leads(phone)")
            except Exception:
                pass
            try:
                await cur.execute("CREATE INDEX idx_messages_lead_id ON messages(lead_id)")
            except Exception:
                pass
    else:
        async with _sqlite_connect() as db:
            await db.executescript(SQLITE_SCHEMA)
            try:
                await db.execute("ALTER TABLE leads ADD COLUMN slack_message_ts TEXT")
            except Exception:
                pass
            await db.commit()


# ---------------------------------------------------------------------------
# insert_lead
# ---------------------------------------------------------------------------
async def insert_lead(lead_data: dict) -> int:
    cols = ", ".join(lead_data.keys())
    if USE_MYSQL:
        placeholders = ", ".join("%s" for _ in lead_data)
        async with _mysql_conn() as (conn, cur):
            await cur.execute(
                f"INSERT INTO leads ({cols}) VALUES ({placeholders})",
                list(lead_data.values()),
            )
            return cur.lastrowid
    else:
        placeholders = ", ".join("?" for _ in lead_data)
        async with _sqlite_connect() as db:
            cursor = await db.execute(
                f"INSERT INTO leads ({cols}) VALUES ({placeholders})",
                list(lead_data.values()),
            )
            await db.commit()
            return cursor.lastrowid


# ---------------------------------------------------------------------------
# get_lead_by_phone
# ---------------------------------------------------------------------------
async def get_lead_by_phone(phone: str) -> dict | None:
    if USE_MYSQL:
        async with _mysql_conn() as (conn, cur):
            await cur.execute("SELECT * FROM leads WHERE phone = %s", (phone,))
            row = await cur.fetchone()
            return dict(row) if row else None
    else:
        async with _sqlite_connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM leads WHERE phone = ?", (phone,))
            row = await cursor.fetchone()
            return dict(row) if row else None


# ---------------------------------------------------------------------------
# get_lead_by_id
# ---------------------------------------------------------------------------
async def get_lead_by_id(lead_id: int) -> dict | None:
    if USE_MYSQL:
        async with _mysql_conn() as (conn, cur):
            await cur.execute("SELECT * FROM leads WHERE id = %s", (lead_id,))
            row = await cur.fetchone()
            return dict(row) if row else None
    else:
        async with _sqlite_connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None


# ---------------------------------------------------------------------------
# update_lead
# ---------------------------------------------------------------------------
async def update_lead(lead_id: int, updates: dict):
    if USE_MYSQL:
        set_clause = ", ".join(f"{k} = %s" for k in updates)
        values = list(updates.values()) + [lead_id]
        async with _mysql_conn() as (conn, cur):
            await cur.execute(
                f"UPDATE leads SET {set_clause} WHERE id = %s",
                values,
            )
    else:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [lead_id]
        async with _sqlite_connect() as db:
            await db.execute(
                f"UPDATE leads SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
                values,
            )
            await db.commit()


# ---------------------------------------------------------------------------
# clear_messages
# ---------------------------------------------------------------------------
async def clear_messages(lead_id: int):
    if USE_MYSQL:
        async with _mysql_conn() as (conn, cur):
            await cur.execute("DELETE FROM messages WHERE lead_id = %s", (lead_id,))
    else:
        async with _sqlite_connect() as db:
            await db.execute("DELETE FROM messages WHERE lead_id = ?", (lead_id,))
            await db.commit()


# ---------------------------------------------------------------------------
# insert_message
# ---------------------------------------------------------------------------
async def insert_message(lead_id: int, direction: str, content: str):
    if USE_MYSQL:
        async with _mysql_conn() as (conn, cur):
            await cur.execute(
                "INSERT INTO messages (lead_id, direction, content) VALUES (%s, %s, %s)",
                (lead_id, direction, content),
            )
    else:
        async with _sqlite_connect() as db:
            await db.execute(
                "INSERT INTO messages (lead_id, direction, content) VALUES (?, ?, ?)",
                (lead_id, direction, content),
            )
            await db.commit()


# ---------------------------------------------------------------------------
# get_transcript
# ---------------------------------------------------------------------------
async def get_transcript(lead_id: int) -> list[dict]:
    if USE_MYSQL:
        async with _mysql_conn() as (conn, cur):
            await cur.execute(
                "SELECT direction, content, created_at FROM messages WHERE lead_id = %s ORDER BY created_at ASC",
                (lead_id,),
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
    else:
        async with _sqlite_connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT direction, content, created_at FROM messages WHERE lead_id = ? ORDER BY created_at ASC",
                (lead_id,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# list_leads
# ---------------------------------------------------------------------------
async def list_leads(classification: str | None = None) -> list[dict]:
    if USE_MYSQL:
        async with _mysql_conn() as (conn, cur):
            if classification:
                await cur.execute(
                    "SELECT * FROM leads WHERE classification = %s ORDER BY created_at DESC",
                    (classification,),
                )
            else:
                await cur.execute("SELECT * FROM leads ORDER BY created_at DESC")
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
    else:
        async with _sqlite_connect() as db:
            db.row_factory = aiosqlite.Row
            if classification:
                cursor = await db.execute(
                    "SELECT * FROM leads WHERE classification = ? ORDER BY created_at DESC",
                    (classification,),
                )
            else:
                cursor = await db.execute("SELECT * FROM leads ORDER BY created_at DESC")
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# claim_lead_for_processing (atomic dedup guard)
# ---------------------------------------------------------------------------
async def claim_lead_for_processing(lead_id: int) -> bool:
    """Atomically set conversation_stage='sending' only if currently 'new'.
    Returns True if claimed, False if already claimed by another request."""
    if USE_MYSQL:
        async with _mysql_conn() as (conn, cur):
            await cur.execute(
                "UPDATE leads SET conversation_stage = 'sending' WHERE id = %s AND conversation_stage = 'new'",
                (lead_id,),
            )
            return cur.rowcount > 0
    else:
        async with _sqlite_connect() as db:
            cursor = await db.execute(
                "UPDATE leads SET conversation_stage = 'sending' WHERE id = ? AND conversation_stage = 'new'",
                (lead_id,),
            )
            await db.commit()
            return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# delete_lead
# ---------------------------------------------------------------------------
async def delete_lead(lead_id: int):
    if USE_MYSQL:
        async with _mysql_conn() as (conn, cur):
            await cur.execute("DELETE FROM messages WHERE lead_id = %s", (lead_id,))
            await cur.execute("DELETE FROM leads WHERE id = %s", (lead_id,))
    else:
        async with _sqlite_connect() as db:
            await db.execute("DELETE FROM messages WHERE lead_id = ?", (lead_id,))
            await db.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
            await db.commit()


# ---------------------------------------------------------------------------
# reset_lead
# ---------------------------------------------------------------------------
async def reset_lead(lead_id: int):
    if USE_MYSQL:
        async with _mysql_conn() as (conn, cur):
            await cur.execute("DELETE FROM messages WHERE lead_id = %s", (lead_id,))
            await cur.execute(
                """UPDATE leads SET
                    conversation_stage = 'new', turn_count = 0,
                    urgency_score = 0, classification = 'unscored',
                    rationale = NULL, recommended_action = NULL,
                    slack_message_ts = NULL
                WHERE id = %s""",
                (lead_id,),
            )
    else:
        async with _sqlite_connect() as db:
            await db.execute("DELETE FROM messages WHERE lead_id = ?", (lead_id,))
            await db.execute(
                """UPDATE leads SET
                    conversation_stage = 'new', turn_count = 0,
                    urgency_score = 0, classification = 'unscored',
                    rationale = NULL, recommended_action = NULL,
                    slack_message_ts = NULL, updated_at = datetime('now')
                WHERE id = ?""",
                (lead_id,),
            )
            await db.commit()
