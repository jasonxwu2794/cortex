#!/usr/bin/env python3
"""Integration tests for MemoryEnhancedMultiAgent — validates all layers work together."""

import sys
import os
import tempfile
import sqlite3
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = "\033[92m✅ PASS\033[0m"
FAIL = "\033[91m❌ FAIL\033[0m"

results = {"pass": 0, "fail": 0}


def report(name, ok, detail=""):
    tag = PASS if ok else FAIL
    extra = f" — {detail}" if detail else ""
    print(f"  {tag} {name}{extra}")
    results["pass" if ok else "fail"] += 1


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1: Import Check
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("TEST 1: Import Check")
print("=" * 60)

modules_to_import = [
    ("memory.schemas", "init_db"),
    ("memory.engine", "MemoryEngine"),
    ("memory.embeddings", "get_embedder"),
    ("memory.scoring", "compute_composite_score"),
    ("memory.dedup", "check_duplicate"),
    ("memory.knowledge_cache", "store_fact"),
    ("memory.retrieval", "retrieve_memories"),
    ("memory.chunker", "split_turn"),
    ("memory.consolidation", None),
    ("agents.common.protocol", "MessageBus"),
    ("agents.common.base_agent", "BaseAgent"),
    ("agents.common.llm_client", "LLMClient"),
    ("agents.common.sub_agent", "SubAgentPool"),
    ("agents.common.web_search", "WebSearchClient"),
    ("agents.brain.brain", "BrainAgent"),
    ("agents.builder.builder", "BuilderAgent"),
    ("agents.researcher.researcher", "ResearcherAgent"),
    ("agents.verifier.verifier", "VerifierAgent"),
    ("agents.guardian.guardian", "GuardianAgent"),
]

for mod_name, attr in modules_to_import:
    try:
        mod = __import__(mod_name, fromlist=[attr] if attr else ["__name__"])
        if attr:
            getattr(mod, attr)
        report(f"import {mod_name}" + (f".{attr}" if attr else ""), True)
    except Exception as e:
        report(f"import {mod_name}" + (f".{attr}" if attr else ""), False, str(e))

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2: Memory Schema
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("TEST 2: Memory Schema")
print("=" * 60)

from memory.schemas import init_db

with tempfile.TemporaryDirectory() as tmpdir:
    db = init_db(os.path.join(tmpdir, "test.db"))

    # Check tables exist
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for tbl in ("memories", "knowledge_cache", "memory_links"):
        report(f"Table '{tbl}' exists", tbl in tables)

    # Check columns
    expected_cols = {
        "memories": {"id", "content", "embedding", "tier", "importance", "tags",
                     "created_at", "updated_at", "access_count", "source_agent", "metadata"},
        "knowledge_cache": {"id", "fact", "embedding", "source", "verified_by",
                            "verified_at", "confidence", "metadata"},
        "memory_links": {"memory_id_a", "memory_id_b", "relation_type", "strength", "created_at"},
    }
    for tbl, expected in expected_cols.items():
        actual = {r[1] for r in db.execute(f"PRAGMA table_info({tbl})").fetchall()}
        ok = expected.issubset(actual)
        report(f"Columns for '{tbl}'", ok, f"missing: {expected - actual}" if not ok else "all present")

    db.close()

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3: Memory Engine — Ingest & Retrieve
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("TEST 3: Memory Engine — Ingest & Retrieve")
print("=" * 60)

import numpy as np
from memory.engine import MemoryEngine, Turn
from memory.embeddings import Embedder

# Try to use real embedder, fall back to random
try:
    from sentence_transformers import SentenceTransformer
    USE_REAL_EMBEDDER = True
    print("  (Using real sentence-transformers embedder)")
except ImportError:
    USE_REAL_EMBEDDER = False
    print("  (Using random vector fallback embedder)")


class FakeEmbedder:
    """Deterministic fake embedder using hash-based vectors."""
    def embed(self, text: str) -> np.ndarray:
        import hashlib
        h = hashlib.sha384(text.encode()).digest()
        vec = np.frombuffer(h, dtype=np.uint8).astype(np.float32)
        # Pad to 384 dims
        vec = np.resize(vec, 384)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    def embed_batch(self, texts: list) -> list:
        return [self.embed(t) for t in texts]

# If no real embedder, patch globally so all MemoryEngine instances use FakeEmbedder
if not USE_REAL_EMBEDDER:
    import memory.embeddings as _emb_mod
    import memory.engine as _eng_mod
    _fake_get = lambda config=None: FakeEmbedder()
    _emb_mod.get_embedder = _fake_get
    _eng_mod.get_embedder = _fake_get


with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "test.db")

    engine = MemoryEngine(db_path=db_path)

    turn = Turn(
        user_message="I prefer Python for ML projects",
        agent_response="Got it, I'll use Python for your ML work",
        agent="brain",
        tags=["preference", "language"],
        signals=["user_preference"],
    )
    ingest_result = engine.ingest(turn)
    stored_ids = ingest_result.get("stored_ids", []) if isinstance(ingest_result, dict) else ingest_result
    report("Ingest returns stored IDs", len(stored_ids) > 0, f"{len(stored_ids)} chunks stored")

    # Check DB has rows
    count = engine.db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    report("Memories exist in DB", count > 0, f"{count} rows")

    # Retrieve
    retrieved = engine.retrieve("What programming language does the user prefer?", limit=5)
    report("Retrieve returns results", len(retrieved) > 0, f"{len(retrieved)} results")

    if retrieved:
        has_python = any("python" in str(r.get("content", "")).lower() for r in retrieved)
        report("Retrieved content mentions Python", has_python)

    # ═══════════════════════════════════════════════════════════════════════════
    # TEST 4: Deduplication
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("TEST 4: Deduplication")
    print("=" * 60)

    count_before = engine.db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    # Ingest same thing again
    turn_dup = Turn(
        user_message="I prefer Python for ML",
        agent_response="Noted, Python for ML",
        agent="brain",
        tags=["preference"],
        signals=["user_preference"],
    )
    dup_result = engine.ingest(turn_dup)
    stored_dup = dup_result.get("stored_ids", []) if isinstance(dup_result, dict) else dup_result

    count_after = engine.db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    if USE_REAL_EMBEDDER:
        # Real embedder should detect near-duplicates
        dedup_worked = count_after <= count_before + 1  # at most 1 new (the slightly different response)
        report("Dedup detection (real embedder)", dedup_worked,
               f"before={count_before}, after={count_after}")
    else:
        # Fake embedder: hash-based, different text = different vector, so dedup won't trigger
        # Instead verify the dedup machinery itself works
        from memory.dedup import check_duplicate, MatchType
        vec = engine.embedder.embed("test")
        existing = [("id1", vec.copy())]
        result = check_duplicate(vec, existing)
        report("Dedup detects exact match", result.match_type == MatchType.EXACT_DUP)

        # Check importance boost mechanism
        from memory.dedup import handle_duplicate
        # Insert a test memory
        from memory.embeddings import serialize_embedding
        engine.db.execute(
            "INSERT OR IGNORE INTO memories (id, content, embedding, importance) VALUES (?, ?, ?, ?)",
            ("test_dedup_id", "test content", serialize_embedding(vec), 0.5),
        )
        engine.db.commit()
        should_store = handle_duplicate("new_id", MatchType.EXACT_DUP, "test_dedup_id", engine.db)
        report("Exact dup: should NOT store new", not should_store)

        imp = engine.db.execute("SELECT importance FROM memories WHERE id='test_dedup_id'").fetchone()[0]
        report("Exact dup: importance boosted", imp > 0.5, f"importance={imp}")

    # ═══════════════════════════════════════════════════════════════════════════
    # TEST 5: Knowledge Cache
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("TEST 5: Knowledge Cache")
    print("=" * 60)

    from memory.knowledge_cache import store_fact, lookup_facts

    fact_embedding = engine.embedder.embed("Python was created by Guido van Rossum")
    fact_id = store_fact(
        fact="Python was created by Guido van Rossum in 1991",
        embedding=fact_embedding,
        source_agent="verifier",
        confidence=0.95,
        db=engine.db,
    )
    report("Store fact returns ID", fact_id is not None and fact_id.startswith("fact_"))

    query_emb = engine.embedder.embed("Who created Python?")
    facts = lookup_facts(query_emb, engine.db, limit=3)
    report("Lookup returns facts", len(facts) > 0, f"{len(facts)} facts")

    if facts:
        report("Fact content correct", "guido" in facts[0]["fact"].lower())
        report("Fact confidence present", facts[0]["confidence"] >= 0.9)

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 6: Scoring
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("TEST 6: Scoring")
print("=" * 60)

from memory.scoring import compute_recency_score, compute_importance_score, compute_composite_score

# Recency
now = datetime.now(timezone.utc)
score_now = compute_recency_score(now)
score_week_ago = compute_recency_score(now - timedelta(days=7))
score_month_ago = compute_recency_score(now - timedelta(days=30))

report("Recency: recent > old", score_now > score_week_ago > score_month_ago,
       f"now={score_now:.3f}, 7d={score_week_ago:.3f}, 30d={score_month_ago:.3f}")
report("Recency: now ≈ 1.0", abs(score_now - 1.0) < 0.01)

# Importance
imp_correction = compute_importance_score(["user_correction"])
imp_general = compute_importance_score(["general"])
imp_empty = compute_importance_score([])

report("Importance: correction > general", imp_correction > imp_general,
       f"correction={imp_correction}, general={imp_general}")
report("Importance: empty = general default", imp_empty == 0.2)

# Composite
score_balanced = compute_composite_score(0.8, 0.9, 0.7, "balanced")
score_recency = compute_composite_score(0.8, 0.9, 0.7, "recency")
score_importance = compute_composite_score(0.8, 0.9, 0.7, "importance")

report("Composite: balanced strategy", 0.0 < score_balanced < 1.0, f"{score_balanced:.3f}")
report("Composite: recency favors recency", score_recency > score_importance,
       f"recency={score_recency:.3f}, importance={score_importance:.3f}")

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 7: Protocol & Message Bus
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("TEST 7: Protocol & Message Bus")
print("=" * 60)

from agents.common.protocol import MessageBus, AgentMessage, AgentRole, TaskStatus

with tempfile.TemporaryDirectory() as tmpdir:
    bus = MessageBus(db_path=os.path.join(tmpdir, "bus.db"))

    # Send message from Brain to Builder
    msg = AgentMessage(
        from_agent=AgentRole.BRAIN,
        to_agent=AgentRole.BUILDER,
        action="build",
        payload={"message": "Create a hello world script"},
    )
    bus.send(msg)
    report("Send message", True)

    # Receive on Builder's end
    received = bus.receive(AgentRole.BUILDER, limit=5)
    report("Receive message", len(received) == 1, f"got {len(received)}")

    if received:
        rmsg = received[0]
        report("Message from Brain", rmsg.from_agent == AgentRole.BRAIN)
        report("Message to Builder", rmsg.to_agent == AgentRole.BUILDER)
        report("Action is 'build'", rmsg.action == "build")
        report("Payload intact", rmsg.payload.get("message") == "Create a hello world script")

    # Update status
    bus.update_status(msg.task_id, TaskStatus.COMPLETED, result={"code": "print('hello')"})
    updated = bus.get_task(msg.task_id)
    report("Status updated to completed", updated.status == TaskStatus.COMPLETED.value)
    report("Result attached", updated.result == {"code": "print('hello')"})

    # Verify no more pending for builder
    pending = bus.receive(AgentRole.BUILDER, limit=5)
    report("No more pending messages", len(pending) == 0)

    bus.close()

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 8: Sub-Agent Pool
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("TEST 8: Sub-Agent Pool")
print("=" * 60)

from agents.common.sub_agent import SubAgentPool, SubTask
from agents.common.llm_client import LLMClient


async def test_sub_agent_pool():
    mock_llm = LLMClient()

    # Mock the generate method
    async def mock_generate(**kwargs):
        return {
            "content": f"Response to: {kwargs.get('prompt', '')[:30]}",
            "usage": {"total_tokens": 100},
        }

    mock_llm.generate = mock_generate

    pool = SubAgentPool(llm=mock_llm, system_prompt="You are a helper.", max_concurrency=3)

    tasks = [
        SubTask(id="t1", description="Task one"),
        SubTask(id="t2", description="Task two"),
        SubTask(id="t3", description="Task three"),
    ]

    results = await pool.execute_parallel(tasks)
    report("All tasks return results", len(results) == 3)

    all_success = all(r.success for r in results)
    report("All tasks succeeded", all_success)

    all_have_output = all(r.output is not None for r in results)
    report("All tasks have output", all_have_output)

    metrics = pool.get_metrics()
    report("Metrics track tasks", metrics["total_tasks"] == 3, f"total={metrics['total_tasks']}")
    report("Metrics track successes", metrics["successes"] == 3)

asyncio.run(test_sub_agent_pool())

# ═══════════════════════════════════════════════════════════════════════════════
# TEST 9: Agent Instantiation
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("TEST 9: Agent Instantiation")
print("=" * 60)

from agents.brain.brain import BrainAgent
from agents.builder.builder import BuilderAgent
from agents.researcher.researcher import ResearcherAgent
from agents.verifier.verifier import VerifierAgent
from agents.guardian.guardian import GuardianAgent

with tempfile.TemporaryDirectory() as tmpdir:
    bus = MessageBus(db_path=os.path.join(tmpdir, "bus.db"))

    agents_to_test = [
        ("BrainAgent", BrainAgent, AgentRole.BRAIN, "brain",
         {"memory_db_path": os.path.join(tmpdir, "mem.db"), "message_bus": bus}),
        ("BuilderAgent", BuilderAgent, AgentRole.BUILDER, "builder",
         {"message_bus": bus}),
        ("ResearcherAgent", ResearcherAgent, AgentRole.RESEARCHER, "researcher",
         {"message_bus": bus}),
        ("VerifierAgent", VerifierAgent, AgentRole.VERIFIER, "verifier",
         {"message_bus": bus}),
        ("GuardianAgent", GuardianAgent, AgentRole.GUARDIAN, "guardian",
         {"message_bus": bus}),
    ]

    for label, cls, expected_role, expected_name, kwargs in agents_to_test:
        try:
            agent = cls(**kwargs)
            report(f"{label} instantiates", True)
            report(f"{label} role={expected_role.value}", agent.role == expected_role)
            report(f"{label} name={expected_name}", agent.name == expected_name)
        except Exception as e:
            report(f"{label} instantiates", False, str(e))

    # Permission matrix
    print("\n  --- Permission Matrix ---")
    brain = BrainAgent(memory_db_path=os.path.join(tmpdir, "mem2.db"), message_bus=bus)
    builder = BuilderAgent(message_bus=bus)
    researcher = ResearcherAgent(message_bus=bus)
    verifier = VerifierAgent(message_bus=bus)
    guardian = GuardianAgent(message_bus=bus)

    report("Brain CAN write memory", brain.can_write_memory)
    report("Builder CANNOT write memory", not builder.can_write_memory)
    report("Researcher CANNOT write memory", not researcher.can_write_memory)
    report("Verifier CANNOT write memory", not verifier.can_write_memory)
    report("Guardian CANNOT write memory", not guardian.can_write_memory)

    report("Builder CAN execute code", builder.can_execute_code)
    report("Brain CANNOT execute code", not brain.can_execute_code)

    report("Researcher CAN access web", researcher.can_access_web)
    report("Verifier CAN access web", verifier.can_access_web)
    report("Builder CANNOT access web", not builder.can_access_web)
    report("Brain CANNOT access web", not brain.can_access_web)
    report("Guardian CANNOT access web", not guardian.can_access_web)

    bus.close()

# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
total = results["pass"] + results["fail"]
print(f"RESULTS: {results['pass']}/{total} passed, {results['fail']} failed")
print("=" * 60)

if results["fail"] > 0:
    print("\n⚠️  Some tests failed!")
    sys.exit(1)
else:
    print("\n🎉 All tests passed!")
    sys.exit(0)
