#!/usr/bin/env python
"""Embed public-safe FahMai chunks into rag.chunk_embeddings.

Prerequisites:
  pip install psycopg[binary]

For local Qwen3-Embedding-8B via Hugging Face Text Embeddings Inference:
  docker run --gpus all -p 8080:80 -v hf_cache:/data --pull always ghcr.io/huggingface/text-embeddings-inference:1.7.2 --model-id Qwen/Qwen3-Embedding-8B --dtype float16

Usage:
  $env:DATABASE_URL = "postgresql://user:pass@localhost:5432/fahmai"
  python scripts/embed_chunks_openai.py --provider tei --endpoint http://localhost:8080/embed --batch-size 64
  python scripts/embed_chunks_openai.py --provider tei --batch-size 64 --refresh-materialized

OpenAI-compatible gateways are also supported:
  pip install openai
  $env:EMBEDDING_BASE_URL = "https://..."
  $env:EMBEDDING_API_KEY = "..."
  python scripts/embed_chunks_openai.py --provider openai-compatible --batch-size 64
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Sequence
from urllib import error, request

try:
    import psycopg
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit("Missing dependency: pip install psycopg[binary]") from exc


DEFAULT_MODEL = "Qwen/Qwen3-Embedding-8B"
DEFAULT_DIMENSION = 4096
DEFAULT_TEI_ENDPOINT = "http://localhost:8080/embed"


def vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(value):.9g}" for value in values) + "]"


def normalize_embedding_response(payload) -> list[list[float]]:
    if isinstance(payload, list):
        if not payload:
            return []
        if isinstance(payload[0], dict) and "embedding" in payload[0]:
            return [item["embedding"] for item in payload]
        return payload
    if isinstance(payload, dict) and "data" in payload:
        return [item["embedding"] for item in payload["data"]]
    raise ValueError("Embedding endpoint returned an unsupported response shape")


def embed_with_tei(endpoint: str, inputs: list[str], timeout_seconds: int, max_retries: int) -> list[list[float]]:
    body = json.dumps({"inputs": inputs}).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    for attempt in range(max_retries + 1):
        try:
            req = request.Request(endpoint, data=body, headers=headers, method="POST")
            with request.urlopen(req, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return normalize_embedding_response(payload)
        except (TimeoutError, error.URLError, error.HTTPError) as exc:
            if attempt >= max_retries:
                raise RuntimeError(f"TEI embedding request failed after {attempt + 1} attempts: {exc}") from exc
            time.sleep(min(2**attempt, 8))

    raise RuntimeError("TEI embedding request failed")


def embed_with_openai_compatible(
    model: str,
    inputs: list[str],
    base_url: str | None,
    api_key: str | None,
    max_retries: int,
) -> list[list[float]]:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise SystemExit("Missing dependency for --provider openai-compatible: pip install openai") from exc

    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=max_retries)
    response = client.embeddings.create(model=model, input=inputs)
    return [item.embedding for item in response.data]


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
    parser.add_argument(
        "--provider",
        choices=["tei", "openai-compatible"],
        default=os.getenv("EMBEDDING_PROVIDER", "tei"),
        help="Embedding backend. Use tei for local Hugging Face Text Embeddings Inference.",
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("EMBEDDING_ENDPOINT", DEFAULT_TEI_ENDPOINT),
        help="TEI /embed endpoint used when --provider tei.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("EMBEDDING_BASE_URL"),
        help="OpenAI-compatible base URL used when --provider openai-compatible.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY"),
        help="API key used when --provider openai-compatible.",
    )
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--max-chunks", type=int, default=0, help="0 means embed all missing chunks")
    parser.add_argument("--dry-run", action="store_true", help="Count missing chunks without calling the embedding backend")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--max-retries", type=int, default=3)
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
    if args.timeout_seconds < 1:
        raise SystemExit("--timeout-seconds must be >= 1")
    if args.max_retries < 0:
        raise SystemExit("--max-retries must be >= 0")

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

            inputs = [text for _, text in rows]
            if args.provider == "tei":
                embeddings = embed_with_tei(args.endpoint, inputs, args.timeout_seconds, args.max_retries)
            else:
                embeddings = embed_with_openai_compatible(
                    args.model,
                    inputs,
                    args.base_url,
                    args.api_key,
                    args.max_retries,
                )
            with conn.transaction():
                inserted = upsert_embeddings(conn, rows, args.model, embeddings)
            total += inserted
            print(f"embedded {inserted} chunks; total={total}")

        if args.refresh_materialized and not args.dry_run:
            refresh_materialized_views(conn)

    return 0


if __name__ == "__main__":
    sys.exit(main())
