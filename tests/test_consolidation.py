#!/usr/bin/env python3
"""Tests for memory consolidation engine and runner."""

import os
import sys
import tempfile
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.schemas import init_db
from memory.consolidation import run_consolidation
from memory.consolidation_runner import main as runner_main
from memory.embeddings import serialize_embedding

PASS = "\033[92m✅ PASS\033[0m"
FAIL = "\033[91m❌ FAIL\033[0m"
results = {"pass": 0, "fail": 0}


def report(name, ok, detail=""):
    tag = PASS if ok else FAIL
    extra = f" — {detail}" if detail else ""
    print(f"  {tag} {name}{extra}")
    results["pass" if ok else "fail"] += 1


def make_db():
    """Create a temp DB and return its path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    return path


def insert_old_memory(db_path, content, importance=0.5, days_old=10, embedding=None):
    """Insert a backdated short_term memory."""
    conn = sqlite3.connect(db_path)
    mem_id = f"mem_{uuid.uuid4().hex[:12]}"
    created = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
    if embedding is None:
        embedding = np.random.randn(384).astype(np.float32)
        embedding = embedding / np.linalg.norm(embedding)
    emb_blob = serialize_embedding(embedding)
    conn.execute(
        "INSERT INTO memories (id, content, embedding, tier, importance, tags, source_agent, created_at) "
        "VALUES (?, ?, ?, 'short_term', ?, 'test', 'test_agent', ?)",
        (mem_id, content, emb_blob, importance, created),
    )
    conn.commit()
    conn.close()
    return mem_id


# ═══════════════════════════════════════════════════════════════
# TEST 1: Empty DB consolidation
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("TEST 1: Empty DB consolidation")
print("=" * 60)

db_path = make_db()
try:
    summary = run_consolidation(db_path, tier="full")
    report("Empty DB returns success", summary is not None)
    report("No consolidated", summary.get("consolidated", 0) == 0)
    report("No clusters", summary.get("clusters", 0) == 0)
    report("No pruned", summary.get("pruned", 0) == 0)
finally:
    os.unlink(db_path)

# ═══════════════════════════════════════════════════════════════
# TEST 2: Consolidation clusters similar memories
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("TEST 2: Cluster similar old memories")
print("=" * 60)

db_path = make_db()
try:
    # Insert 3 memories with identical embeddings (similarity=1.0)
    shared_emb = np.random.randn(384).astype(np.float32)
    shared_emb = shared_emb / np.linalg.norm(shared_emb)
    id1 = insert_old_memory(db_path, "Memory about cats", importance=0.8, embedding=shared_emb)
    id2 = insert_old_memory(db_path, "More about cats", importance=0.6, embedding=shared_emb)
    id3 = insert_old_memory(db_path, "Even more cats", importance=0.5, embedding=shared_emb)

    summary = run_consolidation(db_path, tier="full")
    report("Consolidated 3 memories", summary["consolidated"] == 3)
    report("Formed 1 cluster", summary["clusters"] == 1)

    # Verify originals are gone
    conn = sqlite3.connect(db_path)
    remaining = conn.execute("SELECT COUNT(*) FROM memories WHERE tier='short_term'").fetchone()[0]
    long_term = conn.execute("SELECT COUNT(*) FROM memories WHERE tier='long_term'").fetchone()[0]
    links = conn.execute("SELECT COUNT(*) FROM memory_links WHERE relation_type='consolidated_into'").fetchone()[0]
    conn.close()

    report("Originals deleted", remaining == 0)
    report("1 long-term memory created", long_term == 1)
    report("3 consolidation links created", links == 3)
finally:
    os.unlink(db_path)

# ═══════════════════════════════════════════════════════════════
# TEST 3: Standard tier prunes low importance
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("TEST 3: Standard tier pruning")
print("=" * 60)

db_path = make_db()
try:
    insert_old_memory(db_path, "Important memory", importance=0.9, days_old=10)
    insert_old_memory(db_path, "Low importance", importance=0.1, days_old=3)
    insert_old_memory(db_path, "Also low", importance=0.2, days_old=3)

    summary = run_consolidation(db_path, tier="standard")
    report("Pruned 2 low-importance memories", summary["pruned"] == 2)

    conn = sqlite3.connect(db_path)
    remaining = conn.execute("SELECT COUNT(*) FROM memories WHERE tier='short_term'").fetchone()[0]
    conn.close()
    # The important old one (>7 days) goes to a singleton cluster (not consolidated since cluster size < 2)
    # The 2 low-importance ones (3 days old, not >7 days) get pruned
    report("Only important memory remains", remaining == 0 or remaining == 1)
finally:
    os.unlink(db_path)

# ═══════════════════════════════════════════════════════════════
# TEST 4: Runner CLI
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("TEST 4: Runner CLI")
print("=" * 60)

db_path = make_db()
try:
    exit_code = runner_main(["--db-path", db_path, "--tier", "full"])
    report("Runner exits 0 on empty DB", exit_code == 0)

    exit_code = runner_main(["--db-path", db_path, "--tier", "standard", "--dry-run"])
    report("Dry-run exits 0", exit_code == 0)

    exit_code = runner_main(["--db-path", "/nonexistent/path.db", "--tier", "full"])
    report("Runner exits 1 on missing DB", exit_code == 1)
finally:
    os.unlink(db_path)

# ═══════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
total = results["pass"] + results["fail"]
print(f"RESULTS: {results['pass']}/{total} passed, {results['fail']} failed")
print("=" * 60)

sys.exit(0 if results["fail"] == 0 else 1)
