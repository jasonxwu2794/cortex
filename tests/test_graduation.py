"""Tests for knowledge graduation system."""

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from memory.schemas import init_db
from memory.graduation import run_graduation
from memory.knowledge_refresh import run_refresh


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database with schema."""
    path = tmp_path / "test_memory.db"
    conn = init_db(str(path))
    conn.close()
    return str(path)


def _insert_fact(db_path, fact_id, confidence=0.8, access_count=0,
                 age_days=0, last_accessed_days_ago=None, contradicted=False):
    """Helper to insert a fact with specific attributes."""
    conn = sqlite3.connect(db_path)
    now = datetime.utcnow()
    verified_at = (now - timedelta(days=age_days)).isoformat()
    last_accessed = None
    if last_accessed_days_ago is not None:
        last_accessed = (now - timedelta(days=last_accessed_days_ago)).isoformat()
    metadata = json.dumps({"contradicted": contradicted})
    conn.execute(
        "INSERT INTO knowledge_cache (id, fact, confidence, access_count, "
        "verified_at, last_accessed_at, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (fact_id, f"Fact {fact_id}", confidence, access_count,
         verified_at, last_accessed, metadata),
    )
    conn.commit()
    conn.close()


def _get_fact(db_path, fact_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM knowledge_cache WHERE id = ?", (fact_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


class TestGraduation:
    def test_promote_to_established(self, db_path):
        """Facts with access >= 3, age > 30d, no contradictions → 0.95."""
        _insert_fact(db_path, "f1", confidence=0.8, access_count=5, age_days=45)
        summary = run_graduation(db_path)
        assert summary["promoted"] == 1
        assert _get_fact(db_path, "f1")["confidence"] == 0.95

    def test_promote_to_permanent(self, db_path):
        """Facts with access >= 10, age > 90d, no contradictions → 1.0."""
        _insert_fact(db_path, "f1", confidence=0.8, access_count=15, age_days=100)
        summary = run_graduation(db_path)
        assert summary["promoted"] == 1
        assert _get_fact(db_path, "f1")["confidence"] == 1.0

    def test_no_promote_with_contradictions(self, db_path):
        """Contradicted facts don't get promoted."""
        _insert_fact(db_path, "f1", confidence=0.8, access_count=15,
                     age_days=100, last_accessed_days_ago=1, contradicted=True)
        summary = run_graduation(db_path)
        assert summary["promoted"] == 0
        assert _get_fact(db_path, "f1")["confidence"] == 0.8

    def test_decay_stale_facts(self, db_path):
        """Facts not accessed in 180+ days decay."""
        _insert_fact(db_path, "f1", confidence=0.8, access_count=1,
                     age_days=200, last_accessed_days_ago=200)
        summary = run_graduation(db_path)
        assert summary["decayed"] == 1
        assert _get_fact(db_path, "f1")["confidence"] == 0.7

    def test_flag_for_reverify(self, db_path):
        """Facts decaying below 0.5 get flagged."""
        _insert_fact(db_path, "f1", confidence=0.5, access_count=0,
                     age_days=300, last_accessed_days_ago=200)
        summary = run_graduation(db_path)
        assert summary["flagged_for_reverify"] == 1
        meta = json.loads(_get_fact(db_path, "f1")["metadata"])
        assert meta["needs_reverify"] is True

    def test_permanent_facts_exempt(self, db_path):
        """Permanent facts (1.0) are not touched."""
        _insert_fact(db_path, "f1", confidence=1.0, access_count=0,
                     age_days=300, last_accessed_days_ago=200)
        summary = run_graduation(db_path)
        assert summary["promoted"] == 0
        assert summary["decayed"] == 0
        assert _get_fact(db_path, "f1")["confidence"] == 1.0

    def test_mixed_facts(self, db_path):
        """Multiple facts with different outcomes."""
        _insert_fact(db_path, "promote", confidence=0.8, access_count=5, age_days=45)
        _insert_fact(db_path, "decay", confidence=0.7, access_count=0,
                     age_days=200, last_accessed_days_ago=200)
        _insert_fact(db_path, "permanent", confidence=1.0, access_count=20, age_days=365)
        summary = run_graduation(db_path)
        assert summary["promoted"] == 1
        assert summary["decayed"] == 1


class TestKnowledgeRefresh:
    def test_flag_old_recently_accessed(self, db_path):
        """Old facts accessed recently get flagged."""
        _insert_fact(db_path, "f1", confidence=0.8, access_count=5,
                     age_days=120, last_accessed_days_ago=5)
        summary = run_refresh(db_path)
        assert summary["flagged"] == 1

    def test_permanent_exempt(self, db_path):
        """Permanent facts are not flagged."""
        _insert_fact(db_path, "f1", confidence=1.0, access_count=20,
                     age_days=120, last_accessed_days_ago=5)
        summary = run_refresh(db_path)
        assert summary["already_permanent"] == 1
        assert summary["flagged"] == 0

    def test_skip_not_recently_accessed(self, db_path):
        """Old facts NOT recently accessed are skipped."""
        _insert_fact(db_path, "f1", confidence=0.8, access_count=1,
                     age_days=120, last_accessed_days_ago=60)
        summary = run_refresh(db_path)
        assert summary["skipped"] == 1
        assert summary["flagged"] == 0
