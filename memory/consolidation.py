"""Background consolidation job for memory maintenance."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone, timedelta

import numpy as np

from memory.embeddings import cosine_similarity, deserialize_embedding, serialize_embedding


def run_consolidation(db_path: str, tier: str = "full", dry_run: bool = False) -> dict:
    """Main entry point for consolidation.

    Returns a summary dict: {consolidated, clusters, pruned}.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        summary = {"consolidated": 0, "clusters": 0, "pruned": 0}

        old = find_old_memories(conn)
        if old:
            clusters = cluster_memories(old)
            summary["clusters"] = len([c for c in clusters if len(c) >= 2])

            if not dry_run:
                for cluster in clusters:
                    if len(cluster) < 2:
                        continue
                    merged = summarize_cluster(cluster)
                    summary_id = f"mem_{uuid.uuid4().hex[:12]}"
                    best = max(cluster, key=lambda m: m["importance"])
                    conn.execute(
                        "INSERT INTO memories (id, content, embedding, tier, importance, tags, source_agent, metadata) "
                        "VALUES (?, ?, ?, 'long_term', ?, ?, ?, ?)",
                        (
                            summary_id,
                            merged,
                            best["embedding"],
                            best["importance"],
                            best["tags"],
                            best["source_agent"],
                            str({"consolidated_from": [m["id"] for m in cluster]}),
                        ),
                    )
                    for mem in cluster:
                        conn.execute(
                            "INSERT OR IGNORE INTO memory_links (memory_id_a, memory_id_b, relation_type, strength) "
                            "VALUES (?, ?, 'consolidated_into', 1.0)",
                            (mem["id"], summary_id),
                        )
                        conn.execute("DELETE FROM memories WHERE id = ?", (mem["id"],))
                    summary["consolidated"] += len(cluster)
            else:
                # dry-run: just count
                for cluster in clusters:
                    if len(cluster) >= 2:
                        summary["consolidated"] += len(cluster)

        # Standard tier: also prune low-importance memories
        if tier != "full":
            if dry_run:
                count = conn.execute(
                    "SELECT COUNT(*) FROM memories WHERE tier = 'short_term' AND importance < 0.3"
                ).fetchone()[0]
                summary["pruned"] = count
            else:
                summary["pruned"] = prune_low_importance(conn)

        if not dry_run:
            conn.commit()

        return summary
    finally:
        conn.close()


def find_old_memories(db: sqlite3.Connection, days: int = 7) -> list[dict]:
    """Find short-term memories older than `days`."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = db.execute(
        "SELECT id, content, embedding, importance, tags, source_agent FROM memories "
        "WHERE tier = 'short_term' AND created_at < ?",
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def cluster_memories(memories: list[dict], threshold: float = 0.7) -> list[list[dict]]:
    """Group memories by embedding similarity (simple greedy clustering)."""
    if not memories:
        return []

    used = set()
    clusters: list[list[dict]] = []

    for i, mem in enumerate(memories):
        if i in used or mem["embedding"] is None:
            continue
        cluster = [mem]
        used.add(i)
        emb_i = deserialize_embedding(mem["embedding"])
        for j in range(i + 1, len(memories)):
            if j in used or memories[j]["embedding"] is None:
                continue
            emb_j = deserialize_embedding(memories[j]["embedding"])
            if cosine_similarity(emb_i, emb_j) >= threshold:
                cluster.append(memories[j])
                used.add(j)
        clusters.append(cluster)

    return clusters


def summarize_cluster(cluster: list[dict]) -> str:
    """Summarize a cluster of related memories into one consolidated memory.

    Uses extractive summarization: pulls unique sentences from the cluster
    and deduplicates near-identical ones. No LLM call needed.

    # TODO: Upgrade to LLM-based abstractive summarization as a future enhancement
    # for higher-quality consolidated memories (pro tier feature).
    """
    if len(cluster) == 1:
        return cluster[0]["content"]

    contents = [m["content"] for m in cluster]

    # Simple extractive summary: take unique sentences, deduplicate near-identical ones
    sentences = []
    seen: set[str] = set()
    for content in contents:
        for sentence in content.split(". "):
            sentence = sentence.strip()
            if sentence and sentence.lower() not in seen:
                seen.add(sentence.lower())
                sentences.append(sentence)

    # Cap at reasonable length
    summary = ". ".join(sentences[:20])
    if not summary.endswith("."):
        summary += "."

    return summary


def prune_low_importance(db: sqlite3.Connection, threshold: float = 0.3) -> int:
    """Remove low-importance short-term memories (Standard tier)."""
    cursor = db.execute(
        "DELETE FROM memories WHERE tier = 'short_term' AND importance < ?",
        (threshold,),
    )
    return cursor.rowcount
