"""SQLite schema definitions and database initialization."""

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    embedding BLOB,
    tier TEXT CHECK(tier IN ('short_term', 'long_term')) DEFAULT 'short_term',
    importance REAL DEFAULT 0.5,
    tags TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    source_agent TEXT,
    metadata JSON
);

CREATE TABLE IF NOT EXISTS knowledge_cache (
    id TEXT PRIMARY KEY,
    fact TEXT NOT NULL,
    embedding BLOB,
    source TEXT,
    verified_by TEXT,
    verified_at TIMESTAMP,
    confidence REAL DEFAULT 1.0,
    metadata JSON,
    last_accessed_at TIMESTAMP,
    access_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS memory_links (
    memory_id_a TEXT NOT NULL,
    memory_id_b TEXT NOT NULL,
    relation_type TEXT,
    strength REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (memory_id_a, memory_id_b, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_memories_tier ON memories(tier);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);
CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories(tags);
CREATE INDEX IF NOT EXISTS idx_links_a ON memory_links(memory_id_a);
CREATE INDEX IF NOT EXISTS idx_links_b ON memory_links(memory_id_b);
"""


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Initialize the database with schema and return a connection."""
    db_path = str(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    # Migrate: add graduation columns if missing (for existing DBs)
    cursor = conn.execute("PRAGMA table_info(knowledge_cache)")
    columns = {row[1] for row in cursor.fetchall()}
    if "last_accessed_at" not in columns:
        conn.execute("ALTER TABLE knowledge_cache ADD COLUMN last_accessed_at TIMESTAMP")
    if "access_count" not in columns:
        conn.execute("ALTER TABLE knowledge_cache ADD COLUMN access_count INTEGER DEFAULT 0")
    conn.commit()
    return conn
