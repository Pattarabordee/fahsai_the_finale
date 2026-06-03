#!/usr/bin/env python
"""Batch/resumable RAG ingest for remote FahMai PostgreSQL databases.

This reuses the canonical chunking/id helpers from ingest_fahmai_to_postgres.py
but commits document chunks in small batches so remote runs can be resumed.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

try:
    import psycopg
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit("Missing dependency: pip install psycopg[binary]") from exc

import ingest_fahmai_to_postgres as ingest


def iter_batches(items, size: int):
    for start in range(0, len(items), size):
        yield start, items[start : start + size]


def load_markdown_range(
    conn,
    paths: list[Path],
    chunk_chars: int,
    overlap_chars: int,
    commit_docs: int,
    insert_batch_size: int,
) -> tuple[int, int]:
    total_docs = 0
    total_chunks = 0
    start_time = time.monotonic()

    with conn.cursor() as cur:
        for _, batch_paths in iter_batches(paths, commit_docs):
            source_rows = []
            chunk_rows_by_path = {}
            with conn.transaction():
                for path in batch_paths:
                    rel_path = path.relative_to(ingest.ROOT).as_posix()
                    text = path.read_text(encoding="utf-8")
                    source_document_id = ingest.stable_id("doc", rel_path)
                    content_sha = ingest.sha256_text(text)
                    source_kind = ingest.source_kind_for(path)
                    source_rows.append((source_document_id, rel_path, source_kind, content_sha))

                    path_chunk_rows = []
                    for chunk_index, chunk in enumerate(
                        ingest.chunk_text_with_metadata(
                            text,
                            chunk_chars,
                            overlap_chars,
                            source_path=rel_path,
                            source_kind=source_kind,
                        )
                    ):
                        chunk_id = ingest.stable_id(
                            "chunk",
                            f"{rel_path}:{chunk_index}:{ingest.sha256_text(chunk.chunk_text)}",
                        )
                        token_estimate = max(1, len(chunk.chunk_text) // 4)
                        path_chunk_rows.append(
                            (
                                chunk_id,
                                chunk_index,
                                chunk.chunk_text,
                                token_estimate,
                                chunk.char_start,
                                chunk.char_end,
                                ingest.Jsonb(chunk.metadata),
                            )
                        )
                    chunk_rows_by_path[rel_path] = path_chunk_rows

                cur.executemany(
                    """
                    INSERT INTO fah_sai_lpk_rag.source_documents
                        (source_document_id, source_path, source_kind, is_public_safe, safety_tier, content_sha256)
                    VALUES (%s, %s, %s, true, 'official', %s)
                    ON CONFLICT (source_path) DO UPDATE SET
                        source_kind = EXCLUDED.source_kind,
                        is_public_safe = true,
                        safety_tier = 'official',
                        content_sha256 = EXCLUDED.content_sha256,
                        updated_at = now()
                    """,
                    source_rows,
                )

                rel_paths = [row[1] for row in source_rows]
                cur.execute(
                    """
                    SELECT source_path, source_document_id
                    FROM fah_sai_lpk_rag.source_documents
                    WHERE source_path = ANY(%s)
                    """,
                    (rel_paths,),
                )
                source_ids_by_path = dict(cur.fetchall())
                source_ids = list(source_ids_by_path.values())
                cur.execute(
                    "DELETE FROM fah_sai_lpk_rag.document_chunks WHERE source_document_id = ANY(%s)",
                    (source_ids,),
                )

                batch_insert_rows = []
                for rel_path, path_chunk_rows in chunk_rows_by_path.items():
                    actual_source_document_id = source_ids_by_path[rel_path]
                    batch_insert_rows.extend(
                        (
                            chunk_id,
                            actual_source_document_id,
                            chunk_index,
                            chunk_text,
                            token_estimate,
                            char_start,
                            char_end,
                            metadata,
                        )
                        for (
                            chunk_id,
                            chunk_index,
                            chunk_text,
                            token_estimate,
                            char_start,
                            char_end,
                            metadata,
                        ) in path_chunk_rows
                    )

                for _, insert_rows in iter_batches(batch_insert_rows, insert_batch_size):
                    cur.executemany(
                        """
                        INSERT INTO fah_sai_lpk_rag.document_chunks
                            (chunk_id, source_document_id, chunk_index, chunk_text, token_count,
                             char_start, char_end, language_hint, is_public_safe, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'th-en', true, %s)
                        """,
                        insert_rows,
                    )

            total_docs += len(batch_paths)
            total_chunks += len(batch_insert_rows)
            elapsed = time.monotonic() - start_time
            print(
                f"committed markdown batch docs={total_docs}/{len(paths)} chunks={total_chunks} elapsed_sec={elapsed:.1f}",
                flush=True,
            )

    return total_docs, total_chunks


def load_entity_links(conn, insert_batch_size: int, force_reload: bool) -> tuple[int, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM fah_sai_lpk_rag.entity_links")
        existing_public_links = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM fah_sai_lpk_audit.provenance_entity_links")
        existing_unsafe_links = cur.fetchone()[0]

    if existing_public_links or existing_unsafe_links:
        if not force_reload:
            print(
                f"skipped entity links: existing public={existing_public_links}, unsafe={existing_unsafe_links}",
                flush=True,
            )
            return existing_public_links, existing_unsafe_links
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("DELETE FROM fah_sai_lpk_rag.entity_links")
                cur.execute("DELETE FROM fah_sai_lpk_audit.provenance_entity_links")

    with conn.cursor() as cur:
        cur.execute("SELECT source_path, source_document_id FROM fah_sai_lpk_rag.source_documents")
        source_id_by_path = {row[0]: row[1] for row in cur.fetchall()}

    public_sql = """
        INSERT INTO fah_sai_lpk_rag.entity_links
            (source_document_id, chunk_id, artifact_id, source_path, source_type, entity_type,
             entity_id, linked_table, linked_column, link_method, confidence,
             is_public_safe, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s)
    """
    unsafe_sql = """
        INSERT INTO fah_sai_lpk_audit.provenance_entity_links
            (artifact_id, source_path, source_type, entity_type, entity_id,
             linked_table, linked_column, link_method, confidence,
             is_public_safe, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, false, %s)
    """
    public_count = 0
    unsafe_count = 0
    link_files = [
        ingest.DERIVED_DIR / "DOC_ENTITY_LINKS.csv",
        ingest.DERIVED_DIR / "ARTIFACT_ENTITY_LINKS.csv",
    ]
    chunk_id_cache: dict[tuple[str, str], str | None] = {}

    with conn.cursor() as cur:
        for link_path in link_files:
            if not link_path.exists():
                continue
            file_public = 0
            file_unsafe = 0
            with link_path.open("r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.DictReader(fh)
                public_rows = []
                unsafe_rows = []
                for row in reader:
                    source_path = (row.get("source_path") or "").strip()
                    source_document_id = source_id_by_path.get(source_path)
                    artifact_id = (row.get("artifact_id") or row.get("source_doc_id") or "").strip() or None
                    if ingest.parse_bool(row.get("is_public_safe")):
                        entity_id = row.get("entity_id")
                        chunk_id = ingest.resolve_entity_chunk_id(cur, source_document_id, entity_id, chunk_id_cache)
                        public_rows.append(
                            (
                                source_document_id,
                                chunk_id,
                                artifact_id,
                                source_path,
                                row.get("source_type"),
                                row.get("entity_type"),
                                entity_id,
                                row.get("linked_table"),
                                row.get("linked_column"),
                                row.get("link_method"),
                                row.get("confidence") or "1.0",
                                row.get("notes"),
                            )
                        )
                        if len(public_rows) >= insert_batch_size:
                            with conn.transaction():
                                cur.executemany(public_sql, public_rows)
                            file_public += len(public_rows)
                            public_count += len(public_rows)
                            public_rows.clear()
                    else:
                        unsafe_rows.append(
                            (
                                artifact_id,
                                source_path,
                                row.get("source_type"),
                                row.get("entity_type"),
                                row.get("entity_id"),
                                row.get("linked_table"),
                                row.get("linked_column"),
                                row.get("link_method"),
                                row.get("confidence") or None,
                                row.get("notes"),
                            )
                        )
                        if len(unsafe_rows) >= insert_batch_size:
                            with conn.transaction():
                                cur.executemany(unsafe_sql, unsafe_rows)
                            file_unsafe += len(unsafe_rows)
                            unsafe_count += len(unsafe_rows)
                            unsafe_rows.clear()

                if public_rows:
                    with conn.transaction():
                        cur.executemany(public_sql, public_rows)
                    file_public += len(public_rows)
                    public_count += len(public_rows)
                if unsafe_rows:
                    with conn.transaction():
                        cur.executemany(unsafe_sql, unsafe_rows)
                    file_unsafe += len(unsafe_rows)
                    unsafe_count += len(unsafe_rows)
                    unsafe_rows.clear()

            print(
                f"loaded link file {link_path.name}: public_safe={file_public}, unsafe_audit={file_unsafe}",
                flush=True,
            )

    return public_count, unsafe_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--chunk-chars", type=int, default=ingest.DEFAULT_CHUNK_CHARS)
    parser.add_argument("--chunk-overlap-chars", type=int, default=ingest.DEFAULT_CHUNK_OVERLAP_CHARS)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0, help="0 means all documents from offset")
    parser.add_argument("--commit-docs", type=int, default=1000)
    parser.add_argument("--insert-batch-size", type=int, default=5000)
    parser.add_argument("--load-entity-links", action="store_true")
    parser.add_argument("--force-reload-links", action="store_true")
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("Set DATABASE_URL or pass --database-url")
    if args.chunk_overlap_chars >= args.chunk_chars:
        raise SystemExit("--chunk-overlap-chars must be smaller than --chunk-chars")
    if args.offset < 0:
        raise SystemExit("--offset must be >= 0")
    if args.limit < 0:
        raise SystemExit("--limit must be >= 0")
    if args.commit_docs < 1:
        raise SystemExit("--commit-docs must be >= 1")
    if args.insert_batch_size < 1:
        raise SystemExit("--insert-batch-size must be >= 1")

    all_paths = list(ingest.markdown_paths())
    end = None if args.limit == 0 else args.offset + args.limit
    selected_paths = all_paths[args.offset:end]
    print(
        f"selected markdown docs={len(selected_paths)} offset={args.offset} total={len(all_paths)}",
        flush=True,
    )

    with psycopg.connect(args.database_url, autocommit=True) as conn:
        ingest.configure_bulk_load_session(conn)
        if selected_paths:
            docs, chunks = load_markdown_range(
                conn,
                selected_paths,
                args.chunk_chars,
                args.chunk_overlap_chars,
                args.commit_docs,
                args.insert_batch_size,
            )
            print(f"loaded markdown documents: {docs}, chunks: {chunks}", flush=True)
        if args.load_entity_links:
            public_count, unsafe_count = load_entity_links(
                conn,
                args.insert_batch_size,
                args.force_reload_links,
            )
            print(
                f"loaded entity links: public_safe={public_count}, unsafe_audit={unsafe_count}",
                flush=True,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
