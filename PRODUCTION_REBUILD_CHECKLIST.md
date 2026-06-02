# FahMai Production Rebuild Checklist

Use this checklist to prove that a fresh environment can rebuild the FahMai data
and retrieval stack from source-controlled inputs. The GPU VM is compute for
embeddings; Postgres remains the retrieval and evaluation source of truth.

## 0. Required Inputs

- A clean checkout of this repository.
- PostgreSQL with `pgvector`, `pgcrypto`, and `pg_trgm` available.
- Python 3.11+ with `psycopg[binary]`.
- Docker with NVIDIA GPU runtime on the B200 VM.
- `DATABASE_URL` for the target Postgres database.

```powershell
$env:DATABASE_URL = "postgresql://user:pass@host:5432/fahmai"
python -m pip install -r requirements.txt
```

## 1. Start Qwen Embedding Service On B200

```powershell
docker run --gpus all `
  -p 8080:80 `
  -v hf_cache:/data `
  --pull always `
  ghcr.io/huggingface/text-embeddings-inference:1.7.2 `
  --model-id Qwen/Qwen3-Embedding-8B `
  --dtype float16
```

Smoke check from the machine that will run the scripts:

```powershell
Invoke-RestMethod `
  -Uri http://localhost:8080/embed `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"inputs":["FahMai retrieval smoke test"]}' |
  ConvertTo-Json -Depth 4
```

The returned embedding length must be `4096`.

## 2. Apply Database Migrations

For a fresh database:

```powershell
psql $env:DATABASE_URL -f db/001_init_fahmai_model_schema.sql
psql $env:DATABASE_URL -f db/002_eval_retrieval_workflow.sql
```

Load data before creating heavier indexes/materialized views:

```powershell
python scripts/ingest_fahmai_to_postgres.py --truncate
```

Then apply performance and materialized-view layers:

```powershell
psql $env:DATABASE_URL -f db/003_performance_indexes.sql
psql $env:DATABASE_URL -f db/004_materialized_marts.sql
```

If this database already had 1536-dimensional OpenAI embeddings, run the Qwen
migration before re-embedding:

```powershell
psql $env:DATABASE_URL -f db/006_switch_to_qwen3_embedding_8b.sql
```

For a brand-new database, `001` already creates `vector(4096)`, so `006` is only
needed when upgrading an older loaded database.

## 3. Generate Embeddings

Dry-run the missing chunk count:

```powershell
python scripts/embed_chunks_openai.py `
  --provider tei `
  --endpoint http://localhost:8080/embed `
  --batch-size 64 `
  --dry-run
```

Generate embeddings:

```powershell
python scripts/embed_chunks_openai.py `
  --provider tei `
  --endpoint http://localhost:8080/embed `
  --batch-size 64
```

Build the RAG retrieval materialized view and HNSW indexes:

```powershell
psql $env:DATABASE_URL -f db/005_rag_hnsw_and_public_chunks_mv.sql
psql $env:DATABASE_URL -c "SELECT mart.refresh_all_materialized_views(false);"
psql $env:DATABASE_URL -c "SELECT audit.analyze_fahmai_model_tables();"
```

Use concurrent refresh only after all materialized views have been populated at
least once:

```powershell
psql $env:DATABASE_URL -c "SELECT mart.refresh_all_materialized_views(true);"
```

## 4. Data Health Gates

Run these checks after ingest and embedding:

```sql
SELECT count(*) AS eval_questions FROM eval.questions;
SELECT count(*) AS sales_rows FROM core.fact_sales;
SELECT count(*) AS sales_line_rows FROM core.fact_sales_line_item;
SELECT count(*) AS bank_rows FROM core.fact_bank_transaction;
SELECT count(*) AS source_documents FROM rag.source_documents;
SELECT count(*) AS document_chunks FROM rag.document_chunks;
SELECT count(*) AS embeddings FROM rag.chunk_embeddings;
SELECT count(*) AS public_chunks FROM rag.v_public_retrievable_chunks;
SELECT count(*) AS embedded_public_chunks FROM rag.mv_public_retrievable_chunks;
SELECT count(*) AS bad_embedding_dims
FROM rag.chunk_embeddings
WHERE vector_dims(embedding) <> 4096;
```

Expected gates:

- `eval_questions = 100`
- all 31 official CSV-backed core tables are loaded
- `embeddings > 0`
- `bad_embedding_dims = 0`
- `embedded_public_chunks <= public_chunks`
- `mart.v_sales_order` count equals `core.fact_sales`
- `mart.v_sales_line` count equals `core.fact_sales_line_item`
- `mart.v_bank_reconciliation` count equals `core.fact_bank_transaction`

## 5. Retrieval Smoke Test

Run one known eval question and persist the evidence:

```powershell
python scripts/run_question.py `
  --question-id FAHMAI-Q-L1-001 `
  --run-label production-smoke `
  --match-count 8
```

Run a small eval sample:

```powershell
python scripts/run_question.py `
  --all `
  --limit 10 `
  --run-label production-smoke-10 `
  --match-count 8
```

Inspect persisted runs:

```sql
SELECT
    question_id,
    run_label,
    status,
    cardinality(source_paths) AS source_count,
    runtime_ms,
    created_at
FROM eval.answer_runs
WHERE run_label LIKE 'production-smoke%'
ORDER BY created_at DESC;
```

`scripts/run_question.py` stores retrieval-only evidence as `needs_review`.
Downstream answer generation or human review should convert those runs into
final answers after checking sources.

## 6. Rollback And Recovery Notes

Before running `db/006_switch_to_qwen3_embedding_8b.sql` on a database that has
valuable embeddings, take a database snapshot. The migration intentionally:

- drops the public retrievable materialized view
- drops the old vector retrieval function/index
- truncates `rag.chunk_embeddings`
- switches `embedding` to `vector(4096)`

Recovery path:

1. Restore the DB snapshot, or
2. rerun `scripts/embed_chunks_openai.py`, then
3. rerun `db/005_rag_hnsw_and_public_chunks_mv.sql`, then
4. refresh materialized views.

## 7. Production Readiness Gate

Treat the system as ready for a real demo only when:

- A fresh rebuild completes using this checklist.
- TEI returns 4096-dimensional embeddings.
- `scripts/run_question.py --all --limit 100` completes and writes `eval.answer_runs`.
- L1/L2 questions meet the accepted correctness threshold after review.
- L3/injection questions do not override source-authority rules.
- The exact commit hash, DB snapshot time, and embedding model version are recorded.
