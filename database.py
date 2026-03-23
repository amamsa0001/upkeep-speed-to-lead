import aiosqlite

from config import settings

SCHEMA_SQL = """
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


def _connect():
    return aiosqlite.connect(settings.database_path)


async def init_db():
    async with _connect() as db:
        await db.executescript(SCHEMA_SQL)
        # Migrate: add slack_message_ts if missing (existing DBs)
        try:
            await db.execute("ALTER TABLE leads ADD COLUMN slack_message_ts TEXT")
        except Exception:
            pass  # Column already exists
        await db.commit()


async def insert_lead(lead_data: dict) -> int:
    cols = ", ".join(lead_data.keys())
    placeholders = ", ".join("?" for _ in lead_data)
    async with _connect() as db:
        cursor = await db.execute(
            f"INSERT INTO leads ({cols}) VALUES ({placeholders})",
            list(lead_data.values()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_lead_by_phone(phone: str) -> dict | None:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM leads WHERE phone = ?", (phone,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_lead_by_id(lead_id: int) -> dict | None:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_lead(lead_id: int, updates: dict):
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [lead_id]
    async with _connect() as db:
        await db.execute(
            f"UPDATE leads SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
            values,
        )
        await db.commit()


async def clear_messages(lead_id: int):
    async with _connect() as db:
        await db.execute("DELETE FROM messages WHERE lead_id = ?", (lead_id,))
        await db.commit()


async def insert_message(lead_id: int, direction: str, content: str):
    async with _connect() as db:
        await db.execute(
            "INSERT INTO messages (lead_id, direction, content) VALUES (?, ?, ?)",
            (lead_id, direction, content),
        )
        await db.commit()


async def get_transcript(lead_id: int) -> list[dict]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT direction, content, created_at FROM messages WHERE lead_id = ? ORDER BY created_at ASC",
            (lead_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def list_leads(classification: str | None = None) -> list[dict]:
    async with _connect() as db:
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
