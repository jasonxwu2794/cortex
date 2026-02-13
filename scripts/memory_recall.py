#!/usr/bin/env python3
"""Recall memories from the SQLite database using semantic search."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    parser = argparse.ArgumentParser(description="Recall memories via semantic search")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--db", default="data/memory.db", help="Path to SQLite DB")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results")
    parser.add_argument("--threshold", type=float, default=0.3, help="Min similarity")
    args = parser.parse_args()

    try:
        from memory.schemas import init_db
        from memory.embeddings import get_embedder, cosine_similarity, deserialize_embedding

        conn = init_db(args.db)
        embedder = get_embedder()
        query_emb = embedder.embed(args.query)

        rows = conn.execute(
            "SELECT content, embedding, importance, created_at FROM memories WHERE embedding IS NOT NULL"
        ).fetchall()
        conn.close()

        if not rows:
            print("No relevant memories found.")
            return

        # Score and rank
        results = []
        for row in rows:
            emb = deserialize_embedding(row["embedding"])
            sim = cosine_similarity(query_emb, emb)
            if sim >= args.threshold:
                importance_display = round((row["importance"] or 0.5) * 10)
                results.append((sim, row["created_at"], importance_display, row["content"]))

        results.sort(key=lambda x: x[0], reverse=True)
        results = results[:args.top_k]

        if not results:
            print("No relevant memories found.")
            return

        for sim, ts, imp, content in results:
            # Format timestamp
            ts_short = ts[:16] if ts else "unknown"
            print(f"[{ts_short}] (importance: {imp}) {content}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
