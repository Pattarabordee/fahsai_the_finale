#!/usr/bin/env python
"""Build compact BGE-M3 child chunks from existing FahMai document_chunks.

Usage:
  python scripts/build_bge_parent_child_chunks.py --profile bge_m3_v1 --replace-profile --json

The script reuses fah_sai_lpk_rag.document_chunks as parent context and writes
only child_chunks for BGE-M3 embedding. It does not rewrite legacy chunks and
does not duplicate parent text.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit("Missing dependency: pip install psycopg[binary]") from exc

from ingest_fahmai_to_postgres import ChunkPiece, sha256_text, split_section_body, stable_id


DEFAULT_PROFILE = "bge_m3_v1"
DEFAULT_CHILD_CHARS = 1600
DEFAULT_CHILD_OVERLAP_CHARS = 40
SPLITTER_VERSION = "parent-child-bge-m3-v1"


@dataclass(frozen=True)
class ParentChunk:
    chunk_id: str
    source_document_id: str
    chunk_index: int
    chunk_text: str
    char_start: int | None
    char_end: int | None
    is_public_safe: bool
    metadata: dict[str, Any]
    source_path: str
    source_kind: str


def token_estimate(text: str) -> int:
    return max(1, len(text) // 4)


def split_parent_chunk(
    parent: ParentChunk,
    *,
    profile: str,
    child_chars: int,
    child_overlap_chars: int,
) -> list[ChunkPiece]:
    base_metadata = dict(parent.metadata or {})
    base_metadata.update(
        {
            "chunk_strategy": "parent-child",
            "splitter_version": SPLITTER_VERSION,
            "retrieval_profile": profile,
            "parent_chunk_id": parent.chunk_id,
            "parent_chunk_index": parent.chunk_index,
            "parent_source_path": parent.source_path,
            "parent_source_kind": parent.source_kind,
            "child_chunk_chars": child_chars,
            "child_overlap_chars": child_overlap_chars,
        }
    )
    absolute_start = parent.char_start or 0
    parent_text = parent.chunk_text.strip()
    if not parent_text:
        return []
    if len(parent_text) <= child_chars:
        metadata = dict(base_metadata)
        metadata["chunk_kind"] = metadata.get("chunk_kind", "parent_child")
        metadata["boundary_type"] = "parent"
        return [
            ChunkPiece(
                absolute_start,
                absolute_start + len(parent_text),
                parent_text,
                metadata,
            )
        ]
    return split_section_body(
        parent_text,
        absolute_start,
        child_chars,
        child_overlap_chars,
        base_metadata,
    )


def fetch_parent_batch(conn, profile: str, batch_size: int, last_seen: tuple[str, int, str] | None) -> list[ParentChunk]:
    if last_seen:
        predicate = """
          AND (c.source_document_id, c.chunk_index, c.chunk_id) > (%s, %s, %s)
        """
        params: tuple[Any, ...] = (*last_seen, batch_size)
    else:
        predicate = ""
        params = (batch_size,)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT
                c.chunk_id,
                c.source_document_id,
                c.chunk_index,
                c.chunk_text,
                c.char_start,
                c.char_end,
                c.is_public_safe,
                c.metadata,
                d.source_path,
                d.source_kind
            FROM fah_sai_lpk_rag.document_chunks c
            JOIN fah_sai_lpk_rag.source_documents d
              ON d.source_document_id = c.source_document_id
            WHERE c.is_public_safe = true
              AND d.is_public_safe = true
              {predicate}
            ORDER BY c.source_document_id, c.chunk_index, c.chunk_id
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()
    return [
        ParentChunk(
            chunk_id=row["chunk_id"],
            source_document_id=row["source_document_id"],
            chunk_index=row["chunk_index"],
            chunk_text=row["chunk_text"],
            char_start=row["char_start"],
            char_end=row["char_end"],
            is_public_safe=row["is_public_safe"],
            metadata=row["metadata"] or {},
            source_path=row["source_path"],
            source_kind=row["source_kind"],
        )
        for row in rows
    ]


def count_public_parents(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)
            FROM fah_sai_lpk_rag.document_chunks c
            JOIN fah_sai_lpk_rag.source_documents d
              ON d.source_document_id = c.source_document_id
            WHERE c.is_public_safe = true
              AND d.is_public_safe = true
            """
        )
        return cur.fetchone()[0]


def count_profile_children(conn, profile: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM fah_sai_lpk_rag.child_chunks WHERE retrieval_profile = %s",
            (profile,),
        )
        return cur.fetchone()[0]


def replace_profile(conn, profile: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM fah_sai_lpk_rag.child_chunks WHERE retrieval_profile = %s",
            (profile,),
        )


def insert_child_rows(conn, child_rows: list[tuple[Any, ...]]) -> None:
    if not child_rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO fah_sai_lpk_rag.child_chunks
                (child_chunk_id, parent_chunk_id, retrieval_profile, source_document_id,
                 child_index, child_index_in_parent, child_text, child_start_in_parent,
                 child_end_in_parent, token_count, char_start, char_end, language_hint,
                 is_public_safe, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (child_chunk_id) DO UPDATE SET
                parent_chunk_id = EXCLUDED.parent_chunk_id,
                child_index = EXCLUDED.child_index,
                child_index_in_parent = EXCLUDED.child_index_in_parent,
                child_text = EXCLUDED.child_text,
                child_start_in_parent = EXCLUDED.child_start_in_parent,
                child_end_in_parent = EXCLUDED.child_end_in_parent,
                token_count = EXCLUDED.token_count,
                char_start = EXCLUDED.char_start,
                char_end = EXCLUDED.char_end,
                language_hint = EXCLUDED.language_hint,
                is_public_safe = EXCLUDED.is_public_safe,
                metadata = EXCLUDED.metadata
            """,
            child_rows,
        )


def child_rows_for_parent(
    parent: ParentChunk,
    *,
    profile: str,
    source_child_index: int,
    child_chars: int,
    child_overlap_chars: int,
) -> tuple[list[tuple[Any, ...]], int]:
    rows: list[tuple[Any, ...]] = []
    children = split_parent_chunk(
        parent,
        profile=profile,
        child_chars=child_chars,
        child_overlap_chars=child_overlap_chars,
    )
    for child_index_in_parent, child in enumerate(children):
        child_text = child.chunk_text.strip()
        if not child_text:
            continue
        parent_base = parent.char_start or 0
        child_start_in_parent = max(0, child.char_start - parent_base)
        child_end_in_parent = child_start_in_parent + len(child_text)
        metadata = dict(child.metadata)
        metadata.update(
            {
                "source_child_index": source_child_index,
                "child_index_in_parent": child_index_in_parent,
                "child_start_in_parent": child_start_in_parent,
                "child_end_in_parent": child_end_in_parent,
                "content_sha256": sha256_text(child_text),
            }
        )
        child_chunk_id = stable_id(
            "child",
            f"{profile}:{parent.chunk_id}:{child_index_in_parent}:{sha256_text(child_text)}",
        )
        rows.append(
            (
                child_chunk_id,
                parent.chunk_id,
                profile,
                parent.source_document_id,
                source_child_index,
                child_index_in_parent,
                None,
                child_start_in_parent,
                child_end_in_parent,
                token_estimate(child_text),
                child.char_start,
                child.char_end,
                "th-en",
                True,
                Jsonb(metadata),
            )
        )
        source_child_index += 1
    return rows, source_child_index


def build_profile_chunks(args: argparse.Namespace) -> dict[str, Any]:
    source_child_counters: dict[str, int] = defaultdict(int)
    total_parents = 0
    total_children = 0
    last_seen: tuple[str, int, str] | None = None
    start_time = time.monotonic()

    with psycopg.connect(args.database_url, autocommit=True) as conn:
        parent_total = count_public_parents(conn)
        existing_children = count_profile_children(conn, args.profile)
        if args.replace_profile and not args.dry_run:
            with conn.transaction():
                replace_profile(conn, args.profile)
            existing_children = 0

        while True:
            parents = fetch_parent_batch(conn, args.profile, args.batch_size, last_seen)
            if not parents:
                break
            child_rows: list[tuple[Any, ...]] = []
            for parent in parents:
                source_index = source_child_counters[parent.source_document_id]
                rows, next_source_index = child_rows_for_parent(
                    parent,
                    profile=args.profile,
                    source_child_index=source_index,
                    child_chars=args.child_chars,
                    child_overlap_chars=args.child_overlap_chars,
                )
                source_child_counters[parent.source_document_id] = next_source_index
                child_rows.extend(rows)
                total_parents += 1
                total_children += len(rows)
            if not args.dry_run:
                with conn.transaction():
                    insert_child_rows(conn, child_rows)
            last = parents[-1]
            last_seen = (last.source_document_id, last.chunk_index, last.chunk_id)
            if not args.json:
                elapsed = int(time.monotonic() - start_time)
                print(
                    f"built {total_parents}/{parent_total} parents; "
                    f"children={total_children} elapsed={elapsed}s",
                    flush=True,
                )

    return {
        "profile": args.profile,
        "dry_run": args.dry_run,
        "replace_profile": args.replace_profile,
        "existing_children_before_run": existing_children,
        "parent_chunks_read": total_parents,
        "child_chunks": total_children,
        "child_chars": args.child_chars,
        "child_overlap_chars": args.child_overlap_chars,
        "splitter_version": SPLITTER_VERSION,
        "runtime_seconds": int(time.monotonic() - start_time),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--profile", default=os.getenv("RETRIEVAL_PROFILE", DEFAULT_PROFILE))
    parser.add_argument("--replace-profile", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--child-chars", type=int, default=DEFAULT_CHILD_CHARS)
    parser.add_argument("--child-overlap-chars", type=int, default=DEFAULT_CHILD_OVERLAP_CHARS)
    parser.add_argument("--batch-size", type=int, default=2000)
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("Set DATABASE_URL or pass --database-url")
    if args.profile != DEFAULT_PROFILE:
        raise SystemExit(f"Only {DEFAULT_PROFILE!r} is supported by this builder")
    if args.child_chars < 1:
        raise SystemExit("--child-chars must be >= 1")
    if args.child_overlap_chars < 0:
        raise SystemExit("--child-overlap-chars must be >= 0")
    if args.child_overlap_chars >= args.child_chars:
        raise SystemExit("--child-overlap-chars must be smaller than --child-chars")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")
    return args


def main() -> int:
    args = parse_args()
    result = build_profile_chunks(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"built compact bge child chunks: children={result['child_chunks']} "
            f"dry_run={result['dry_run']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
