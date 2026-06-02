#!/usr/bin/env python
"""Embed public-safe FahMai chunks into rag.chunk_embeddings.

Prerequisites:
  pip install psycopg[binary] openai

Usage:
  $env:DATABASE_URL = "postgresql://user:pass@localhost:5432/fahmai"
  $env:OPENAI_API_KEY = "..."
  python scripts/embed_chunks_openai.py --batch-size 64
  python scripts/embed_chunks_openai.py --batch-size 64 --refresh-materialized
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Sequence

try:
    import psycopg
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit("Missing dependency: pip install psycopg[binary]") from exc

try:
    from openai import OpenAI
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit("Missing dependency: pip install openai") from exc


DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_DIMENSION = 1536


def vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(value):.9g}" for value in values) + "]"


def fetch_missing_chunks(conn, batch_size: int) -> list[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.chunk_id, c.chunk_text
            FROM rag.document_chunks c
            JOIN rag.source_documents d
              ON d.source_document_id = c.source_document_id
            LEFT JOIN rag.chunk_embeddings e
              ON e.chunk_id = c.chunk_id
            WHERE c.is_public_safe = true
              AND d.is_public_safe = true
              AND e.chunk_id IS NULL
            ORDER BY c.source_document_id, c.chunk_index
            LIMIT %s
            """,
            (batch_size,),
        )
        return [(row[0], row[1]) for row in cur.fetchall()]


def upsert_embeddings(conn, rows: list[tuple[str, str]], model: str, embeddings: Sequence[Sequence[float]]) -> int:
    if len(rows) != len(embeddings):
        raise ValueError("Embedding response count does not match chunk count")

    inserted = 0
    with conn.cursor() as cur:
        for (chunk_id, _), embedding in zip(rows, embeddings):
            if len(embedding) != DEFAULT_DIMENSION:
                raise ValueError(f"{chunk_id} embedding dimension {len(embedding)} != {DEFAULT_DIMENSION}")
            cur.execute(
                """
                INSERT INTO rag.chunk_embeddings (chunk_id, embedding_model, embedding)
                VALUES (%s, %s, %s::vector)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    embedding_model = EXCLUDED.embedding_model,
                    embedding = EXCLUDED.embedding,
                    embedding_created_at = now()
                """,
                (chunk_id, model, vector_literal(embedding)),
            )
            inserted += 1
    return inserted


def refresh_materialized_views(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regprocedure('mart.refresh_all_materialized_views(boolean)')")
        if cur.fetchone()[0]:
            cur.execute("SELECT mart.refresh_all_materialized_views(false)")
            print("refreshed materialized views: non-concurrent first-load mode")
        else:
            print("skipped materialized refresh; run db/004_materialized_marts.sql first")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="Postgres connection URL")
    parser.add_argument("--model", default=os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL))
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--max-chunks", type=int, default=0, help="0 means embed all missing chunks")
    parser.add_argument("--dry-run", action="store_true", help="Count missing chunks without calling OpenAI")
    parser.add_argument(
        "--refresh-materialized",
        action="store_true",
        help="Refresh mart/RAG materialized views after embedding, if the refresh function exists",
    )
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("Set DATABASE_URL or pass --database-url")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")

    client = None if args.dry_run else OpenAI()
    total = 0
    with psycopg.connect(args.database_url) as conn:
        while True:
            remaining = args.max_chunks - total if args.max_chunks else args.batch_size
            if args.max_chunks and remaining <= 0:
                break
            batch_size = min(args.batch_size, remaining) if args.max_chunks else args.batch_size
            rows = fetch_missing_chunks(conn, batch_size)
            if not rows:
                break
            if args.dry_run:
                total += len(rows)
                print(f"would embed {len(rows)} chunks; total seen={total}")
                if args.max_chunks:
                    continue
                break

            response = client.embeddings.create(
                model=args.model,
                input=[text for _, text in rows],
                dimensions=DEFAULT_DIMENSION,
            )
            embeddings = [item.embedding for item in response.data]
            with conn.transaction():
                inserted = upsert_embeddings(conn, rows, args.model, embeddings)
            total += inserted
            print(f"embedded {inserted} chunks; total={total}")

        if args.refresh_materialized and not args.dry_run:
            refresh_materialized_views(conn)

    return 0


if __name__ == "__main__":
    sys.exit(main())
