#!/usr/bin/env python3
"""Store a memory in the SQLite database with embedding and dedup."""

import argparse
import sys
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add parent dir to path for memory module imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def score_importance(text: str) -> float:
    """Simple heuristic importance scoring (1-10 scale)."""
    text_lower = text.lower()
    score = 5.0  # baseline

    # High importance signals
    high = ["name is", "called", "prefer", "favorite", "birthday", "allergic",
            "decided", "important", "always", "never", "hate", "love", "must"]
    medium = ["project", "working on", "planning", "goal", "wants", "likes",
              "job", "lives in", "moved to", "started", "switched"]
    low = ["mentioned", "said", "talked about"]

    for kw in high:
        if kw in text_lower:
            score = max(score, 8.0)
    for kw in medium:
        if kw in text_lower:
            score = max(score, 6.5)
    for kw in low:
        if kw in text_lower:
            score = max(score, 4.0)

    # Longer = likely more substantive
    if len(text) > 200:
        score = min(score + 1, 10.0)

    return round(score, 1)


def main():
    parser = argparse.ArgumentParser(description="Store a memory with embedding and dedup")
    parser.add_argument("text", nargs="?", help="Memory text (or pass via stdin)")
    parser.add_argument("--db", default="data/memory.db", help="Path to SQLite DB")
    parser.add_argument("--importance", type=float, default=None, help="Override importance (1-10)")
    parser.add_argument("--source", default="conversation", help="Source label")
    args = parser.parse_args()

    # Get text from arg or stdin
    text = args.text
    if not text:
        if not sys.stdin.isatty():
            text = sys.stdin.read().strip()
    if not text:
        print("Error: No text provided", file=sys.stderr)
        sys.exit(1)

    try:
        from memory.schemas import init_db
        from memory.embeddings import get_embedder, cosine_similarity, serialize_embedding, deserialize_embedding

        # Ensure DB directory exists
        os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)
        conn = init_db(args.db)

        # Generate embedding
        embedder = get_embedder()
        embedding = embedder.embed(text)

        # Dedup: check against recent memories
        rows = conn.execute(
            "SELECT id, content, embedding FROM memories ORDER BY created_at DESC LIMIT 50"
        ).fetchall()

        for row in rows:
            if row["embedding"]:
                existing_emb = deserialize_embedding(row["embedding"])
                sim = cosine_similarity(embedding, existing_emb)
                if sim > 0.9:
                    print(f"Skipped (duplicate, {sim:.2f} similar to existing): {row['content'][:80]}")
                    conn.close()
                    return

        # Score importance
        importance = args.importance if args.importance is not None else score_importance(text)
        importance_normalized = importance / 10.0  # DB stores 0-1

        # Store
        memory_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO memories (id, content, embedding, importance, source_agent, tier)
               VALUES (?, ?, ?, ?, ?, 'long_term')""",
            (memory_id, text, serialize_embedding(embedding), importance_normalized, args.source)
        )
        conn.commit()
        conn.close()

        print(f"Stored: {text[:120]} (importance: {importance:.0f})")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
