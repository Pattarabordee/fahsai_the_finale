# FahMai Optimization — Round 3

## What is still missing (verified by reading current source files)

Round 2 recommendations were **not yet applied** — the Python scripts and SQL files below are unchanged.
Do NOT redo anything from `003`, `004`, `005`. Start from here.

| Gap | Where | Severity |
|-----|--------|----------|
| `db/006_hybrid_retrieval.sql` not created | Missing file | 🔴 Critical |
| `db/007_session_tuning.sql` not created | Missing file | 🔴 Critical |
| `embed_chunks_openai.py` — per-row `execute` in upsert loop | line 67–81 | 🔴 Critical |
| `embed_chunks_openai.py` — `fetch_missing_chunks` degrades each batch | line 41–58 | 🟠 High |
| `embed_chunks_openai.py` — no retry on 429/timeout | line 132–136 | 🟠 High |
| `ingest_fahmai_to_postgres.py` — per-row `execute` for chunks | line 300–308 | 🟠 High |
| `ingest_fahmai_to_postgres.py` — `copy_csv` reads file twice | line 161–172 | 🟡 Medium |
| `ingest_fahmai_to_postgres.py` — re-processes unchanged docs | line 268–311 | 🟡 Medium |
| `ingest_fahmai_to_postgres.py` — `load_entity_links` fetches all source_documents into Python dict | line 323–324 | 🟡 Medium |
| `fahmai_question_cookbook.sql` query 8 — points to old `v_public_retrievable_chunks` | line 148 | 🟡 Medium |
| No answer-pipeline script | Missing file | 🟠 High |

---

## Task 1 — Create `db/006_hybrid_retrieval.sql`

Unified retrieval function combining HNSW vector search and BM25/trigram full-text via
Reciprocal Rank Fusion. Callers currently must run two queries and merge manually.

```sql
-- Hybrid retrieval using Reciprocal Rank Fusion (RRF).
-- query_embedding: pass NULL to do text-only search.
-- query_text:      pass NULL to do vector-only search.
-- candidate_count: candidates pulled per signal before merging.
-- rrf_k:           smoothing constant (60 is the standard default).

CREATE OR REPLACE FUNCTION rag.hybrid_search_public_chunks(
    query_embedding vector(1536) DEFAULT NULL,
    query_text      text        DEFAULT NULL,
    match_count     integer     DEFAULT 8,
    rrf_k           integer     DEFAULT 60,
    candidate_count integer     DEFAULT 80
)
RETURNS TABLE (
    chunk_id         text,
    source_path      text,
    source_kind      text,
    artifact_id      text,
    doc_id           text,
    chunk_index      integer,
    chunk_text       text,
    token_count      integer,
    rrf_score        double precision,
    vector_rank      integer,
    text_rank        integer,
    cosine_distance  double precision,
    text_score       real,
    embedding_model  text,
    chunk_metadata   jsonb,
    source_metadata  jsonb
)
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
WITH
vector_ranked AS (
    SELECT
        m.chunk_id,
        ROW_NUMBER() OVER (ORDER BY m.embedding <=> query_embedding) AS rank,
        (m.embedding <=> query_embedding)::double precision            AS cosine_distance,
        m.embedding_model
    FROM rag.mv_public_retrievable_chunks m
    WHERE query_embedding IS NOT NULL
      AND m.embedding IS NOT NULL
    ORDER BY m.embedding <=> query_embedding
    LIMIT GREATEST(candidate_count, match_count)
),
text_ranked AS (
    SELECT
        c.chunk_id,
        ROW_NUMBER() OVER (
            ORDER BY GREATEST(
                ts_rank(c.search_tsv, plainto_tsquery('simple', query_text)),
                similarity(c.chunk_text, query_text)::real
            ) DESC
        ) AS rank,
        GREATEST(
            ts_rank(c.search_tsv, plainto_tsquery('simple', query_text)),
            similarity(c.chunk_text, query_text)::real
        )::real AS text_score
    FROM rag.mv_public_retrievable_chunks c
    WHERE query_text IS NOT NULL
      AND (
          c.search_tsv @@ plainto_tsquery('simple', query_text)
          OR c.chunk_text % query_text
      )
    ORDER BY text_score DESC
    LIMIT GREATEST(candidate_count, match_count)
),
merged AS (
    SELECT
        COALESCE(v.chunk_id, t.chunk_id)                   AS chunk_id,
        COALESCE(1.0 / (rrf_k + v.rank), 0.0)
            + COALESCE(1.0 / (rrf_k + t.rank), 0.0)       AS rrf_score,
        v.rank::integer                                     AS vector_rank,
        t.rank::integer                                     AS text_rank,
        v.cosine_distance,
        t.text_score,
        v.embedding_model
    FROM vector_ranked v
    FULL OUTER JOIN text_ranked t ON t.chunk_id = v.chunk_id
    ORDER BY rrf_score DESC
    LIMIT match_count
)
SELECT
    m.chunk_id,
    c.source_path,
    c.source_kind,
    c.artifact_id,
    c.doc_id,
    c.chunk_index,
    c.chunk_text,
    c.token_count,
    m.rrf_score,
    m.vector_rank,
    m.text_rank,
    m.cosine_distance,
    m.text_score,
    COALESCE(m.embedding_model, c.embedding_model) AS embedding_model,
    c.chunk_metadata,
    c.source_metadata
FROM merged m
JOIN rag.mv_public_retrievable_chunks c ON c.chunk_id = m.chunk_id
ORDER BY m.rrf_score DESC, m.chunk_id;
$$;

COMMENT ON FUNCTION rag.hybrid_search_public_chunks(vector, text, integer, integer, integer) IS
    'Hybrid retrieval: HNSW vector + BM25/trigram merged with RRF. Pass both signals for full hybrid; omit one for single-signal search.';

-- High-quality variant that raises ef_search before searching
CREATE OR REPLACE FUNCTION rag.hybrid_search_hq(
    query_embedding vector(1536) DEFAULT NULL,
    query_text      text        DEFAULT NULL,
    match_count     integer     DEFAULT 8,
    ef_search_val   integer     DEFAULT 100
)
RETURNS TABLE (
    chunk_id text, source_path text, source_kind text,
    chunk_text text, rrf_score double precision,
    cosine_distance double precision, text_score real
)
LANGUAGE plpgsql STABLE AS $$
BEGIN
    EXECUTE format('SET LOCAL hnsw.ef_search = %s', ef_search_val);
    RETURN QUERY
    SELECT h.chunk_id, h.source_path, h.source_kind, h.chunk_text,
           h.rrf_score, h.cosine_distance, h.text_score
    FROM rag.hybrid_search_public_chunks(query_embedding, query_text, match_count) h;
END;
$$;
```

---

## Task 2 — Create `db/007_session_tuning.sql`

Adds `pg_stat_statements` for monitoring slow queries and sets database-level performance defaults.

```sql
-- Slow query monitoring
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Replace 'fahmai' with the actual database name.
-- On managed Postgres (Supabase/RDS) these may require ALTER ROLE instead; skip if restricted.
ALTER DATABASE fahmai SET work_mem                       = '64MB';
ALTER DATABASE fahmai SET max_parallel_workers_per_gather = 4;
ALTER DATABASE fahmai SET max_parallel_workers            = 8;
ALTER DATABASE fahmai SET max_parallel_maintenance_workers = 4;
ALTER DATABASE fahmai SET jit                             = on;
ALTER DATABASE fahmai SET hnsw.ef_search                 = 40;

-- Useful diagnostic queries (run ad-hoc, not as part of schema):
-- SELECT query, calls, total_exec_time/calls AS avg_ms, rows
-- FROM pg_stat_statements
-- ORDER BY avg_ms DESC LIMIT 20;
```

---

## Task 3 — Fix `db/sql_templates/fahmai_question_cookbook.sql` query 8

Query 8 (line 148) still points to `rag.v_public_retrievable_chunks` (the old regular view).
Replace it with the materialized view so it benefits from the HNSW and GIN indexes.

Find this block:
```sql
-- 8) Public-safe entity-linked document retrieval.
SELECT
    c.chunk_id,
    c.source_path,
    c.source_kind,
    c.chunk_text,
    el.linked_table,
    el.linked_column,
    el.entity_id
FROM rag.v_public_retrievable_chunks c
JOIN rag.entity_links el ON el.chunk_id = c.chunk_id
WHERE el.is_public_safe = true
  AND el.linked_table = :linked_table
  AND el.entity_id = :entity_id
ORDER BY c.source_path, c.chunk_index
LIMIT :limit_rows;
```

Replace `rag.v_public_retrievable_chunks` with `rag.mv_public_retrievable_chunks`.

Also add two new templates at the end of the file:

```sql
-- 11) Hybrid retrieval (vector + full-text, RRF-merged).
-- Pass :query_embedding as a pre-computed vector literal,
-- and :query_text as the raw question string.
SELECT *
FROM rag.hybrid_search_public_chunks(
    :query_embedding::vector(1536),
    :query_text,
    :match_count
);

-- 12) Customer loyalty history — latest balance and tier per customer.
SELECT DISTINCT ON (customer_id)
    customer_id,
    business_event_date,
    resulting_balance_points,
    resulting_tier
FROM core.fact_loyalty_ledger
WHERE customer_id = :customer_id
ORDER BY customer_id, business_event_date DESC, ledger_id DESC;

-- 13) Inventory turnover: movement quantity vs snapshot stock for a period.
WITH moved AS (
    SELECT sku_id, branch_code, SUM(quantity) AS units_moved
    FROM core.fact_inventory_movement
    WHERE movement_type IN ('sale_out', 'transfer_out')
      AND business_event_date >= :start_date::date
      AND business_event_date <  :end_date_exclusive::date
    GROUP BY sku_id, branch_code
),
snap AS (
    SELECT sku_id, branch_code, closing_units
    FROM core.fact_inventory_monthly_snapshot
    WHERE month_end_date = :snapshot_month_end::date
)
SELECT
    s.sku_id,
    s.branch_code,
    s.closing_units,
    m.units_moved,
    ROUND(m.units_moved::numeric / NULLIF(s.closing_units, 0), 4) AS turnover_ratio
FROM snap s
LEFT JOIN moved m USING (sku_id, branch_code)
ORDER BY turnover_ratio DESC NULLS LAST;
```

---

## Task 4 — Fix `scripts/embed_chunks_openai.py` (modify existing file)

### 4.1 Replace per-row `execute` loop with `executemany`

Current `upsert_embeddings` (lines 61–82) calls `cur.execute()` once per chunk in a Python for-loop.
Replace the entire function body with:

```python
def upsert_embeddings(
    conn,
    rows: list[tuple[str, str]],
    model: str,
    embeddings: Sequence[Sequence[float]],
) -> int:
    if len(rows) != len(embeddings):
        raise ValueError("Embedding response count does not match chunk count")

    records = []
    for (chunk_id, _), embedding in zip(rows, embeddings):
        if len(embedding) != DEFAULT_DIMENSION:
            raise ValueError(
                f"{chunk_id} embedding dimension {len(embedding)} != {DEFAULT_DIMENSION}"
            )
        records.append((chunk_id, model, vector_literal(embedding)))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO rag.chunk_embeddings (chunk_id, embedding_model, embedding)
            VALUES (%s, %s, %s::vector)
            ON CONFLICT (chunk_id) DO UPDATE SET
                embedding_model = EXCLUDED.embedding_model,
                embedding       = EXCLUDED.embedding,
                embedding_created_at = now()
            """,
            records,
        )
    return len(records)
```

### 4.2 Fix `fetch_missing_chunks` degradation

`fetch_missing_chunks` scans from the beginning every time (no cursor). After N batches the query
must skip over N×batch_size already-processed rows. Fix with an `after_chunk_id` offset:

```python
def fetch_missing_chunks(
    conn, batch_size: int, after_chunk_id: str = ""
) -> list[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.chunk_id, c.chunk_text
            FROM rag.document_chunks c
            JOIN rag.source_documents d
              ON d.source_document_id = c.source_document_id
            LEFT JOIN rag.chunk_embeddings e ON e.chunk_id = c.chunk_id
            WHERE c.is_public_safe = true
              AND d.is_public_safe = true
              AND e.chunk_id IS NULL
              AND c.chunk_id > %s
            ORDER BY c.chunk_id
            LIMIT %s
            """,
            (after_chunk_id, batch_size),
        )
        return [(row[0], row[1]) for row in cur.fetchall()]
```

Update `main()` to pass and advance `after_chunk_id`:
```python
last_chunk_id = ""
while True:
    rows = fetch_missing_chunks(conn, batch_size, after_chunk_id=last_chunk_id)
    if not rows:
        break
    # ... embed and upsert ...
    last_chunk_id = rows[-1][0]
```

### 4.3 Add retry with exponential backoff for rate-limit errors

Add these imports at the top of the file:
```python
import time
import openai
```

Wrap the `client.embeddings.create(...)` call:

```python
def embed_with_retry(
    client: "openai.OpenAI",
    model: str,
    texts: list[str],
    dimensions: int,
    max_retries: int = 5,
    base_sleep: float = 10.0,
) -> list[list[float]]:
    for attempt in range(max_retries + 1):
        try:
            response = client.embeddings.create(
                model=model, input=texts, dimensions=dimensions
            )
            return [item.embedding for item in response.data]
        except (openai.RateLimitError, openai.APITimeoutError) as exc:
            if attempt == max_retries:
                raise
            sleep_secs = min(base_sleep * (2 ** attempt), 120.0)
            print(
                f"OpenAI rate-limit/timeout (attempt {attempt+1}); "
                f"sleeping {sleep_secs:.0f}s — {exc}"
            )
            time.sleep(sleep_secs)
```

Replace the `client.embeddings.create(...)` line in `main()` with:
```python
embeddings = embed_with_retry(client, args.model, [text for _, text in rows], DEFAULT_DIMENSION)
```

Add `--max-retries` and `--retry-base-sleep` arguments to the parser:
```python
parser.add_argument("--max-retries", type=int, default=5)
parser.add_argument("--retry-base-sleep", type=float, default=10.0)
```

---

## Task 5 — Fix `scripts/ingest_fahmai_to_postgres.py` (modify existing file)

### 5.1 Fix `copy_csv` reading the file twice

Current code opens the file in binary mode for `COPY` and then re-opens in text mode just to count rows (lines 161–172). Use `cur.rowcount` instead:

```python
def copy_csv(cur, schema: str, table: str, path: Path) -> int:
    sql = (
        f"COPY {qident(schema)}.{qident(table)} "
        f"FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')"
    )
    with cur.copy(sql) as copy:
        with path.open("rb") as fh:
            while chunk := fh.read(1 << 20):   # 1 MiB
                copy.write(chunk)
    return cur.rowcount   # rowcount is set after COPY completes
```

### 5.2 Batch chunk inserts with `executemany`

In `load_markdown_documents`, the inner loop (lines 297–309) calls `cur.execute()` once per chunk.
Accumulate chunks in a list and flush every 500 rows:

```python
CHUNK_BATCH = 500

def load_markdown_documents(conn, chunk_chars: int, overlap_chars: int) -> None:
    document_count = 0
    chunk_count = 0
    pending_chunks: list[tuple] = []

    def flush_chunks(cur):
        if not pending_chunks:
            return
        cur.executemany(
            """
            INSERT INTO rag.document_chunks
                (chunk_id, source_document_id, chunk_index, chunk_text,
                 token_count, char_start, char_end, language_hint, is_public_safe)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'th-en', true)
            """,
            pending_chunks,
        )
        pending_chunks.clear()

    with conn.cursor() as cur:
        for path in markdown_paths():
            rel_path = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            content_sha = sha256_text(text)
            source_kind = source_kind_for(path)
            source_document_id = stable_id("doc", rel_path)

            cur.execute(
                """
                INSERT INTO rag.source_documents
                    (source_document_id, source_path, source_kind,
                     is_public_safe, safety_tier, content_sha256)
                VALUES (%s, %s, %s, true, 'official', %s)
                ON CONFLICT (source_path) DO UPDATE SET
                    source_kind      = EXCLUDED.source_kind,
                    is_public_safe   = true,
                    safety_tier      = 'official',
                    content_sha256   = EXCLUDED.content_sha256,
                    updated_at       = now()
                RETURNING source_document_id, content_sha256
                """,
                (source_document_id, rel_path, source_kind, content_sha),
            )
            row = cur.fetchone()
            actual_id, stored_sha = row
            # Skip if file content unchanged
            if stored_sha == content_sha:
                # Check whether chunks already exist for this document
                cur.execute(
                    "SELECT 1 FROM rag.document_chunks WHERE source_document_id = %s LIMIT 1",
                    (actual_id,),
                )
                if cur.fetchone():
                    document_count += 1
                    continue

            cur.execute(
                "DELETE FROM rag.document_chunks WHERE source_document_id = %s",
                (actual_id,),
            )
            for idx, (start, end, piece) in enumerate(chunk_text(text, chunk_chars, overlap_chars)):
                chunk_id = stable_id("chunk", f"{rel_path}:{idx}:{sha256_text(piece)}")
                token_estimate = max(1, len(piece) // 4)
                pending_chunks.append(
                    (chunk_id, actual_id, idx, piece, token_estimate, start, end)
                )
                chunk_count += 1
                if len(pending_chunks) >= CHUNK_BATCH:
                    flush_chunks(cur)
            document_count += 1
        flush_chunks(cur)

    print(f"loaded markdown documents: {document_count}, chunks: {chunk_count}")
```

> **Note**: The `ON CONFLICT` clause above must return both `source_document_id` and `content_sha256`. Adjust the `RETURNING` clause if the `ON CONFLICT` branch currently returns a stale sha. Use `RETURNING source_document_id, EXCLUDED.content_sha256` if needed, or run a follow-up `SELECT` after the upsert.

### 5.3 Fix `load_entity_links` in-memory dict

Current code (lines 323–324) fetches **all** rows from `rag.source_documents` into a Python dict.
For large document sets this can hold tens of thousands of rows in memory unnecessarily.
Do the lookup inside SQL instead:

```python
def load_entity_links(conn) -> None:
    link_files = [
        DERIVED_DIR / "DOC_ENTITY_LINKS.csv",
        DERIVED_DIR / "ARTIFACT_ENTITY_LINKS.csv",
    ]
    public_rows: list[tuple] = []
    unsafe_rows: list[tuple] = []

    for path in link_files:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                source_path = (row.get("source_path") or "").strip()
                artifact_id = (row.get("artifact_id") or row.get("source_doc_id") or "").strip() or None
                is_public_safe = parse_bool(row.get("is_public_safe"))
                if is_public_safe:
                    public_rows.append((
                        source_path, artifact_id,
                        row.get("source_type"), row.get("entity_type"),
                        row.get("entity_id"), row.get("linked_table"),
                        row.get("linked_column"), row.get("link_method"),
                        row.get("confidence") or "1.0", row.get("notes"),
                    ))
                else:
                    unsafe_rows.append((
                        artifact_id, source_path,
                        row.get("source_type"), row.get("entity_type"),
                        row.get("entity_id"), row.get("linked_table"),
                        row.get("linked_column"), row.get("link_method"),
                        row.get("confidence") or None, row.get("notes"),
                    ))

    with conn.cursor() as cur:
        if public_rows:
            cur.executemany(
                """
                INSERT INTO rag.entity_links
                    (source_document_id, artifact_id, source_path, source_type,
                     entity_type, entity_id, linked_table, linked_column,
                     link_method, confidence, is_public_safe, notes)
                SELECT
                    sd.source_document_id, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, true, %s
                FROM rag.source_documents sd
                WHERE sd.source_path = %s
                """,
                [(a, sp, st, et, ei, lt, lc, lm, cf, no, sp)
                 for (sp, a, st, et, ei, lt, lc, lm, cf, no) in public_rows],
            )
        if unsafe_rows:
            cur.executemany(
                """
                INSERT INTO audit.provenance_entity_links
                    (artifact_id, source_path, source_type, entity_type, entity_id,
                     linked_table, linked_column, link_method, confidence,
                     is_public_safe, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, false, %s)
                """,
                unsafe_rows,
            )

    print(f"loaded entity links: public_safe={len(public_rows)}, unsafe_audit={len(unsafe_rows)}")
```

### 5.4 Batch-insert questions and tags with `executemany`

In `load_questions` (lines 184–223), individual `cur.execute()` is called per question and per tag.
Collect all rows first, then insert in two `executemany` calls:

```python
def load_questions(conn) -> None:
    question_rows: list[tuple] = []
    tag_rows: list[tuple] = []

    with QUESTIONS_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            question_id   = row["id"].strip()
            question_text = row["question"].strip()
            parts      = question_id.split("-")
            difficulty = parts[2] if len(parts) >= 3 else None
            family     = difficulty.lower() if difficulty else "unknown"
            question_rows.append(
                (question_id, question_text, difficulty, family, sha256_text(question_text))
            )
            for tag in classify_question(question_id, question_text):
                tag_rows.append((question_id, tag))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO eval.questions
                (question_id, question_text, difficulty, question_family, question_hash)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (question_id) DO UPDATE SET
                question_text  = EXCLUDED.question_text,
                difficulty     = EXCLUDED.difficulty,
                question_family= EXCLUDED.question_family,
                question_hash  = EXCLUDED.question_hash,
                updated_at     = now()
            """,
            question_rows,
        )
        cur.executemany(
            """
            INSERT INTO eval.question_tags (question_id, tag, tag_source, confidence)
            VALUES (%s, %s, 'rule', 1.0)
            ON CONFLICT (question_id, tag) DO UPDATE SET
                tag_source = EXCLUDED.tag_source,
                confidence = EXCLUDED.confidence
            """,
            tag_rows,
        )
    print(f"loaded questions: {len(question_rows)}, tags: {len(tag_rows)}")
```

---

## Task 6 — Create `scripts/run_question.py` (new file)

This is the missing answer-pipeline script. It ties together: embed query → hybrid search →
SQL template lookup → write result to `eval.answer_runs`.

```python
#!/usr/bin/env python
"""Run a single question through the FahMai RAG + SQL answer pipeline.

Prerequisites:
  pip install psycopg[binary] openai

Usage:
  python scripts/run_question.py --question-id "FAHMAI-Q-L1-001" --run-label "v1"
  python scripts/run_question.py --question-text "ยอดขายสาขา A เดือนมกราคม 2025 เท่าไร" --run-label "v1"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

try:
    import psycopg
except ImportError as exc:
    raise SystemExit("Missing dependency: pip install psycopg[binary]") from exc

try:
    from openai import OpenAI
    import openai as openai_mod
except ImportError as exc:
    raise SystemExit("Missing dependency: pip install openai") from exc


DEFAULT_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_DIMENSION   = 1536
DEFAULT_MATCH_COUNT = 8


def embed_query(client: OpenAI, text: str, model: str = DEFAULT_EMBED_MODEL) -> list[float]:
    for attempt in range(5):
        try:
            response = client.embeddings.create(
                model=model, input=[text], dimensions=DEFAULT_DIMENSION
            )
            return response.data[0].embedding
        except (openai_mod.RateLimitError, openai_mod.APITimeoutError) as exc:
            if attempt == 4:
                raise
            sleep = min(10.0 * (2 ** attempt), 120.0)
            print(f"rate-limit; sleeping {sleep:.0f}s — {exc}")
            time.sleep(sleep)


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.9g}" for v in values) + "]"


def retrieve_chunks(
    conn, embedding: list[float], query_text: str, match_count: int
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT chunk_id, source_path, source_kind, chunk_text,
                   rrf_score, cosine_distance, text_score
            FROM rag.hybrid_search_public_chunks(
                %s::vector, %s, %s
            )
            """,
            (vector_literal(embedding), query_text, match_count),
        )
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def save_answer_run(
    conn,
    question_id: str,
    run_label: str,
    answer_text: str,
    chunks: list[dict],
    runtime_ms: int,
    model_name: str,
) -> str:
    source_paths = list({c["source_path"] for c in chunks})
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO eval.answer_runs
                (question_id, run_label, status, answer_text,
                 source_paths, runtime_ms, model_name)
            VALUES (%s, %s, 'answered', %s, %s, %s, %s)
            RETURNING answer_run_id
            """,
            (
                question_id, run_label, answer_text,
                source_paths, runtime_ms, model_name,
            ),
        )
        return str(cur.fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--question-id",   help="Load question text from eval.questions")
    parser.add_argument("--question-text", help="Raw question string (skips DB lookup)")
    parser.add_argument("--run-label",  default="manual")
    parser.add_argument("--match-count", type=int, default=DEFAULT_MATCH_COUNT)
    parser.add_argument("--embed-model", default=os.getenv("EMBEDDING_MODEL", DEFAULT_EMBED_MODEL))
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("Set DATABASE_URL or pass --database-url")
    if not args.question_id and not args.question_text:
        raise SystemExit("Provide --question-id or --question-text")

    client = OpenAI()
    t0 = time.monotonic()

    with psycopg.connect(args.database_url) as conn:
        question_text = args.question_text
        question_id   = args.question_id or "adhoc"

        if args.question_id and not question_text:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT question_text FROM eval.questions WHERE question_id = %s",
                    (args.question_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise SystemExit(f"Question {args.question_id!r} not found in eval.questions")
                question_text = row[0]

        print(f"Question: {question_text}")

        embedding = embed_query(client, question_text, args.embed_model)
        chunks    = retrieve_chunks(conn, embedding, question_text, args.match_count)

        print(f"\nRetrieved {len(chunks)} chunks:")
        for i, c in enumerate(chunks, 1):
            print(f"  [{i}] {c['source_path']} | rrf={c['rrf_score']:.4f}")
            print(f"       {c['chunk_text'][:120].replace(chr(10), ' ')}…")

        # Simple answer assembly — replace with LLM call if needed
        context = "\n\n---\n\n".join(
            f"[{c['source_path']}]\n{c['chunk_text']}" for c in chunks
        )
        answer_text = f"[Context assembled from {len(chunks)} chunks]\n\n{context}"

        runtime_ms = int((time.monotonic() - t0) * 1000)

        with conn.transaction():
            run_id = save_answer_run(
                conn, question_id, args.run_label, answer_text,
                chunks, runtime_ms, args.embed_model,
            )
        print(f"\nSaved answer_run_id={run_id}  runtime={runtime_ms}ms")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## Execution order (full pipeline after applying all rounds)

```bash
# DB migrations (run once)
psql $DATABASE_URL -f db/001_init_fahmai_model_schema.sql
psql $DATABASE_URL -f db/002_eval_retrieval_workflow.sql
psql $DATABASE_URL -f db/003_performance_indexes.sql
psql $DATABASE_URL -f db/004_materialized_marts.sql
psql $DATABASE_URL -f db/005_rag_hnsw_and_public_chunks_mv.sql
psql $DATABASE_URL -f db/006_hybrid_retrieval.sql
psql $DATABASE_URL -f db/007_session_tuning.sql

# Load data
python scripts/ingest_fahmai_to_postgres.py \
    --truncate --refresh-materialized

# Generate embeddings
python scripts/embed_chunks_openai.py \
    --batch-size 128 --max-retries 5 --refresh-materialized

# Run a question
python scripts/run_question.py \
    --question-id "FAHMAI-Q-L1-001" \
    --match-count 8 \
    --run-label "round3"
```

---

## Expected gains from Round 3

| Change | Current behaviour | After fix |
|--------|------------------|-----------|
| `upsert_embeddings` executemany | N DB round-trips per batch | 1 round-trip per batch |
| `fetch_missing_chunks` cursor | Full scan grows with each batch | O(log n) keyset pagination |
| Retry on 429 | Script crashes, loses progress | Auto-recovers up to 5× |
| Chunk insert executemany | 1 round-trip per chunk | 1 round-trip per 500 chunks |
| Skip unchanged docs | Re-processes all docs on re-run | Skips docs with same SHA |
| `load_entity_links` SQL join | Dict of all source_documents in RAM | No Python dict, join in DB |
| `load_questions` executemany | N+M round-trips | 2 round-trips total |
| Hybrid search (006) | Two separate queries + manual merge | Single RPC, RRF in DB |
| `run_question.py` | No pipeline script | End-to-end in one command |
