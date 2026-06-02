# FahMai Optimization — Round 2

## Context: What Codex already completed

| File | Status |
|------|--------|
| `db/002_eval_retrieval_workflow.sql` | Done — eval schema, question tags, SQL templates, match_public_chunks, search_public_chunks_text |
| `db/003_performance_indexes.sql` | Done — all missing indexes on every core/rag table + analyze function |
| `db/004_materialized_marts.sql` | Done — all mart views materialized + compatibility views + refresh function |
| `db/005_rag_hnsw_and_public_chunks_mv.sql` | Done — HNSW ef_construction=128 + mv_public_retrievable_chunks + updated refresh function |
| `scripts/ingest_fahmai_to_postgres.py` | Done — COPY-based bulk loader, SET CONSTRAINTS ALL DEFERRED |
| `scripts/embed_chunks_openai.py` | Done — batched OpenAI embedding, upsert to chunk_embeddings |

The tasks below are the remaining gaps. Do NOT redo anything from the files above.

---

## Task 1 — Create `db/006_hybrid_retrieval.sql`

Add a unified hybrid retrieval function that combines vector similarity and full-text search using Reciprocal Rank Fusion (RRF). This removes the need for callers to run two separate queries and merge results manually.

### 1.1 `rag.hybrid_search_public_chunks`

```sql
-- Hybrid retrieval: vector + BM25/trigram, merged with Reciprocal Rank Fusion.
-- query_embedding: pre-computed query vector (pass NULL to do text-only search)
-- query_text:      raw query string (pass NULL to do vector-only search)
-- match_count:     number of results to return
-- rrf_k:           RRF smoothing constant (default 60 is standard)
-- candidate_count: how many candidates to pull from each signal before merging

CREATE OR REPLACE FUNCTION rag.hybrid_search_public_chunks(
    query_embedding vector(1536) DEFAULT NULL,
    query_text text DEFAULT NULL,
    match_count integer DEFAULT 8,
    rrf_k integer DEFAULT 60,
    candidate_count integer DEFAULT 80
)
RETURNS TABLE (
    chunk_id text,
    source_document_id text,
    source_path text,
    source_kind text,
    artifact_id text,
    doc_id text,
    chunk_index integer,
    chunk_text text,
    token_count integer,
    rrf_score double precision,
    vector_rank integer,
    text_rank integer,
    cosine_distance double precision,
    text_score real,
    embedding_model text,
    chunk_metadata jsonb,
    source_metadata jsonb
)
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
WITH

-- Vector signal: ranked nearest neighbours from the materialized view
vector_results AS (
    SELECT
        m.chunk_id,
        ROW_NUMBER() OVER (ORDER BY m.embedding <=> query_embedding) AS rank,
        (m.embedding <=> query_embedding)::double precision AS cosine_distance,
        m.embedding_model
    FROM rag.mv_public_retrievable_chunks m
    WHERE query_embedding IS NOT NULL
      AND m.embedding IS NOT NULL
    ORDER BY m.embedding <=> query_embedding
    LIMIT GREATEST(candidate_count, match_count)
),

-- Full-text + trigram signal: ranked by combined ts_rank + similarity score
text_results AS (
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

-- RRF merge: score = 1/(k + rank_v) + 1/(k + rank_t) for each signal present
merged AS (
    SELECT
        COALESCE(v.chunk_id, t.chunk_id) AS chunk_id,
        COALESCE(
            1.0 / (rrf_k + v.rank), 0.0
        ) + COALESCE(
            1.0 / (rrf_k + t.rank), 0.0
        ) AS rrf_score,
        v.rank::integer AS vector_rank,
        t.rank::integer AS text_rank,
        v.cosine_distance,
        t.text_score,
        v.embedding_model
    FROM vector_results v
    FULL OUTER JOIN text_results t ON t.chunk_id = v.chunk_id
    ORDER BY rrf_score DESC
    LIMIT match_count
)

SELECT
    m.chunk_id,
    c.source_document_id,
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
    'Hybrid RAG retrieval combining HNSW vector similarity and BM25/trigram full-text search via Reciprocal Rank Fusion. Pass both query_embedding and query_text for full hybrid; omit one for single-signal search.';
```

### 1.2 Add `hnsw.ef_search` session setter

```sql
-- Convenience wrapper that sets ef_search before calling hybrid search
-- Use for queries that need higher recall at cost of slight latency
CREATE OR REPLACE FUNCTION rag.hybrid_search_public_chunks_hq(
    query_embedding vector(1536) DEFAULT NULL,
    query_text text DEFAULT NULL,
    match_count integer DEFAULT 8,
    rrf_k integer DEFAULT 60,
    candidate_count integer DEFAULT 120,
    ef_search integer DEFAULT 100
)
RETURNS TABLE (
    chunk_id text,
    source_path text,
    source_kind text,
    chunk_text text,
    rrf_score double precision,
    cosine_distance double precision,
    text_score real
)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    EXECUTE format('SET LOCAL hnsw.ef_search = %s', ef_search);
    RETURN QUERY
    SELECT
        h.chunk_id, h.source_path, h.source_kind, h.chunk_text,
        h.rrf_score, h.cosine_distance, h.text_score
    FROM rag.hybrid_search_public_chunks(
        query_embedding, query_text, match_count, rrf_k, candidate_count
    ) h;
END;
$$;
```

### 1.3 Fix the `entity_linked_retrieval` SQL template (still points to old view)

Update the existing `entity_linked_retrieval` template in `eval.sql_templates` to use the materialized view:

```sql
UPDATE eval.sql_templates
SET sql_template = $template$
SELECT
    c.chunk_id,
    c.source_path,
    c.source_kind,
    c.chunk_text,
    el.linked_table,
    el.linked_column,
    el.entity_id
FROM rag.mv_public_retrievable_chunks c
JOIN rag.entity_links el ON el.chunk_id = c.chunk_id
WHERE el.is_public_safe = true
  AND el.linked_table = :linked_table
  AND el.entity_id = :entity_id
ORDER BY c.source_path, c.chunk_index
LIMIT :limit_rows;
$template$,
updated_at = now()
WHERE template_name = 'entity_linked_retrieval';
```

---

## Task 2 — Create `db/007_session_tuning.sql`

Performance tuning settings and monitoring extension. Apply to the database (not just session) for persistent effect.

```sql
-- Enable slow query logging and statistics tracking.
-- These require superuser on managed Postgres (Supabase/RDS) - skip if unavailable.

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Database-level defaults (ALTER DATABASE requires the DB name - replace 'fahmai' with actual name)
-- These improve query performance for analytics workloads:

-- work_mem: per-sort/hash operation; 64MB helps large GROUP BY / ORDER BY on fact tables
ALTER DATABASE fahmai SET work_mem = '64MB';

-- Increase parallel workers for large sequential scans
ALTER DATABASE fahmai SET max_parallel_workers_per_gather = 4;
ALTER DATABASE fahmai SET max_parallel_workers = 8;

-- Allow parallel queries on safe functions (already set on match_public_chunks)
ALTER DATABASE fahmai SET max_parallel_maintenance_workers = 4;

-- JIT: beneficial for aggregation queries on large fact tables
ALTER DATABASE fahmai SET jit = on;

-- For HNSW vector search quality (can also set per-session before querying)
ALTER DATABASE fahmai SET hnsw.ef_search = 40;
```

> **Note**: Replace `fahmai` with the actual database name. If using a managed DB (Supabase/RDS/Cloud SQL) that restricts `ALTER DATABASE`, skip those lines and apply settings per-session instead.

---

## Task 3 — Improve `scripts/embed_chunks_openai.py`

The current script is single-threaded: it fetches one batch, waits for the API response, inserts, then repeats. For a large chunk corpus this is slow. Apply these improvements:

### 3.1 Use `asyncio` + `openai.AsyncOpenAI` for concurrent batches

Replace the current `main()` with an async implementation that runs `concurrency` batches in parallel.

Key changes:
- Import `asyncio` and `openai.AsyncOpenAI`
- Add `--concurrency` CLI argument (default: 3)
- Fetch `concurrency × batch_size` chunks at once, split into sub-batches, embed concurrently
- Each sub-batch runs in its own `asyncio.Task`
- Respect OpenAI rate limits by catching `openai.RateLimitError` and sleeping with exponential backoff (start at 10s, max 120s)
- Write embeddings with a single `executemany` call per batch instead of one `execute` per row

### 3.2 Batch the `INSERT` into `rag.chunk_embeddings` using `executemany`

Current code inserts one row per `cur.execute()` call inside a Python loop.

Replace the `upsert_embeddings` function with:

```python
def upsert_embeddings(conn, rows: list[tuple[str, str]], model: str, embeddings) -> int:
    records = []
    for (chunk_id, _), embedding in zip(rows, embeddings):
        if len(embedding) != DEFAULT_DIMENSION:
            raise ValueError(f"{chunk_id} embedding dimension {len(embedding)} != {DEFAULT_DIMENSION}")
        records.append((chunk_id, model, vector_literal(embedding)))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO rag.chunk_embeddings (chunk_id, embedding_model, embedding)
            VALUES (%s, %s, %s::vector)
            ON CONFLICT (chunk_id) DO UPDATE SET
                embedding_model = EXCLUDED.embedding_model,
                embedding = EXCLUDED.embedding,
                embedding_created_at = now()
            """,
            records,
        )
    return len(records)
```

### 3.3 Add `--retry-on-rate-limit` and `--max-retries` flags

Current code has no retry logic. If the OpenAI API returns 429, the script crashes and loses progress on the current batch (though already-committed batches are safe).

Add:
```python
parser.add_argument("--max-retries", type=int, default=5)
parser.add_argument("--retry-base-sleep", type=float, default=10.0)
```

Wrap the `client.embeddings.create(...)` call in a retry loop:
- Catch `openai.RateLimitError` and `openai.APITimeoutError`
- Sleep `retry_base_sleep * 2**attempt` seconds (capped at 120s)
- Re-raise after `max_retries` attempts

---

## Task 4 — Improve `scripts/ingest_fahmai_to_postgres.py`

### 4.1 Load dimension tables in parallel

The current `load_official_csvs` loads all 31 tables sequentially in one giant `SET CONSTRAINTS ALL DEFERRED` transaction. Independent dimension tables can be loaded concurrently.

Split loading into three phases. Each phase runs tables in parallel using `concurrent.futures.ThreadPoolExecutor`. Use a separate connection per thread (psycopg connections are not thread-safe).

```python
# Phase 1: no FK dependencies - load all in parallel
PHASE_1_DIMS = [
    "DIM_BRANCH", "DIM_DEPARTMENT", "DIM_POSITION_LEVEL", "DIM_DATE",
    "DIM_VENDOR", "DIM_PROMO_CAMPAIGN",
]

# Phase 2: depend only on Phase 1 tables
PHASE_2_DIMS = [
    "DIM_BANK_ACCOUNT", "DIM_EMPLOYEE", "DIM_PRODUCT",
    "DIM_VENDOR_CONTRACT_VERSION", "DIM_POLICY_VERSION", "DIM_CUSTOMER",
]

# Phase 3: depend on Phase 2 tables
PHASE_3_DIMS = [
    "dim_care_plus_sku_tier", "dim_product_recall_history",
    "dim_promo_mechanic", "dim_signing_authority_ladder",
    "DIM_PROMO_CAMPAIGN",  # if not in phase 1
]

# All fact tables (load after all dims)
FACT_TABLES = [
    "FACT_BANK_TRANSACTION", "FACT_SALES",
    "FACT_SALES_LINE_ITEM", "FACT_LOYALTY_LEDGER",
    "FACT_INVENTORY_MOVEMENT", "FACT_INVENTORY_MONTHLY_SNAPSHOT",
    "FACT_PAYROLL", "FACT_PROMO_REDEMPTION", "FACT_REFUND_PAID",
    "FACT_RETURN", "FACT_SHIPPING", "FACT_VENDOR_PAYMENT",
    "FACT_WARRANTY_CLAIM", "FACT_CS_INTERACTION",
    "T2_DOC_INVENTORY",
]
```

Each parallel task:
1. Opens its own connection with `psycopg.connect(database_url)`
2. Runs `SET CONSTRAINTS ALL DEFERRED` in that connection
3. Calls `copy_csv` for raw and core
4. Commits

After all three phases complete, run the existing `ANALYZE` and `refresh_materialized_views` steps.

### 4.2 Batch-insert chunks with `executemany`

The `load_markdown_documents` function currently calls `cur.execute(INSERT ...)` once per chunk inside a loop. Replace with batch accumulation and `executemany`:

```python
CHUNK_BATCH_SIZE = 500

# Collect tuples in a list, flush every CHUNK_BATCH_SIZE rows
chunk_batch = []

# ... inside the per-document loop, instead of cur.execute per chunk:
chunk_batch.append((chunk_id, actual_source_document_id, idx, piece,
                    token_estimate, start, end))

if len(chunk_batch) >= CHUNK_BATCH_SIZE:
    cur.executemany(
        """
        INSERT INTO rag.document_chunks
            (chunk_id, source_document_id, chunk_index, chunk_text, token_count,
             char_start, char_end, language_hint, is_public_safe)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'th-en', true)
        """,
        chunk_batch,
    )
    chunk_batch.clear()

# After the document loop, flush remaining rows
if chunk_batch:
    cur.executemany(...)
    chunk_batch.clear()
```

Apply the same `executemany` pattern to `load_questions` (question rows + tag rows) and `load_entity_links`.

### 4.3 Add `--workers` CLI argument

```python
parser.add_argument("--workers", type=int, default=4,
                    help="Number of parallel threads for phase-based CSV loading")
```

Pass this to the `ThreadPoolExecutor(max_workers=args.workers)` call in the parallel loader.

---

## Task 5 — Improve chunking strategy in `scripts/ingest_fahmai_to_postgres.py`

The current `chunk_text` function splits at fixed `chunk_chars=4500` with a fallback to the nearest newline. This works but creates uneven chunks and can split mid-sentence.

### 5.1 Add sentence-boundary aware splitting

Replace the `chunk_text` function with a version that:
1. Tries to split at paragraph boundaries (`\n\n`) first
2. Falls back to sentence boundaries (`.`, `!`, `?`, `\n`) within the chunk window
3. Only falls back to hard character split if no boundary is found

```python
import re

_SENTENCE_END = re.compile(r'(?<=[.!?])\s+|(?<=\n)\s*')

def chunk_text(text: str, chunk_chars: int, overlap_chars: int) -> list[tuple[int, int, str]]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    chunks = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_chars, len(normalized))
        if end < len(normalized):
            # Prefer paragraph boundary
            para = normalized.rfind("\n\n", start, end)
            if para > start + chunk_chars // 2:
                end = para
            else:
                # Fall back to sentence boundary (newline or sentence-end punctuation)
                newline = normalized.rfind("\n", start + chunk_chars // 2, end)
                if newline > start:
                    end = newline
        piece = normalized[start:end].strip()
        if piece:
            chunks.append((start, end, piece))
        if end >= len(normalized):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks
```

---

## Summary — Files to create

| File | Task |
|------|------|
| `db/006_hybrid_retrieval.sql` | Task 1: hybrid_search_public_chunks + ef_search wrapper + fix entity template |
| `db/007_session_tuning.sql` | Task 2: pg_stat_statements + ALTER DATABASE performance settings |
| `scripts/embed_chunks_openai.py` | Task 3: async concurrent batches + executemany + retry logic (modify existing file) |
| `scripts/ingest_fahmai_to_postgres.py` | Task 4+5: parallel dim loading + executemany chunks + sentence-boundary chunking (modify existing file) |

## Migration execution order (full sequence)

```bash
psql $DATABASE_URL -f db/001_init_fahmai_model_schema.sql
psql $DATABASE_URL -f db/002_eval_retrieval_workflow.sql
psql $DATABASE_URL -f db/003_performance_indexes.sql
psql $DATABASE_URL -f db/004_materialized_marts.sql
psql $DATABASE_URL -f db/005_rag_hnsw_and_public_chunks_mv.sql
psql $DATABASE_URL -f db/006_hybrid_retrieval.sql      # NEW
psql $DATABASE_URL -f db/007_session_tuning.sql        # NEW

python scripts/ingest_fahmai_to_postgres.py --truncate --workers 4 --refresh-materialized
python scripts/embed_chunks_openai.py --batch-size 64 --concurrency 3 --refresh-materialized
```
