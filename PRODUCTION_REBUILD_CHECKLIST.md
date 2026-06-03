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
- `FAHMAI_DB_PASSWORD` for the local VM database user.

## B200 VM Quickstart

For a fresh Linux B200 VM, use the bootstrap script instead of running each
command manually:

```bash
export FAHMAI_DB_PASSWORD="replace-me"
bash scripts/setup_b200_fahmai.sh
```

The default run starts PostgreSQL with `pgvector`, starts the Qwen embedding
service, applies `db/001`, `db/002`, `db/007`, and `db/008`, and runs schema
smoke checks.

To load data and chunk public documents:

```bash
LOAD_DATA=1 bash scripts/setup_b200_fahmai.sh
```

To also generate embeddings and build retrieval caches:

```bash
LOAD_DATA=1 GENERATE_EMBEDDINGS=1 bash scripts/setup_b200_fahmai.sh
```

Set `TRUNCATE_BEFORE_LOAD=1` only for a disposable/fresh database that should be
cleared before reloading data.

```powershell
$env:DATABASE_URL = "postgresql://fahmai_app:<password>@0.tcp.ap.ngrok.io:26551/fahmai?sslmode=disable"
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
python scripts/apply_db_migrations.py --migrations schema --verify
```

This creates the source-of-truth schemas plus the compact
`fah_sai_lpk_model` LLM-facing views.

To expose the same allowlisted migration flow as an internal API, run:

```powershell
$env:DB_MIGRATION_ADMIN_TOKEN = "replace-me"
uvicorn scripts.db_migration_api:app --host 127.0.0.1 --port 8081
```

Load data before creating heavier indexes/materialized views:

```powershell
python scripts/ingest_fahmai_to_postgres.py --truncate --skip-rag
python scripts/ingest_rag_batches.py --commit-docs 500 --load-entity-links
```

Then apply performance and materialized-view layers:

```powershell
python scripts/apply_db_migrations.py --migrations "003,004" --verify
```

If this database already had 1536-dimensional OpenAI embeddings, run the Qwen
migration before re-embedding:

```powershell
python scripts/apply_db_migrations.py --migrations 006 --verify
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

Build the RAG retrieval materialized view and optional HNSW indexes:

```powershell
python scripts/apply_db_migrations.py --migrations 005 --verify
psql $env:DATABASE_URL -c "SELECT fah_sai_lpk_mart.refresh_all_materialized_views(false);"
psql $env:DATABASE_URL -c "SELECT fah_sai_lpk_audit.analyze_fahmai_model_tables();"
```

`Qwen/Qwen3-Embedding-8B` uses 4096-dimensional vectors. Some pgvector builds
cannot create HNSW indexes above 2000 dimensions; the current migrations skip
those HNSW indexes with a NOTICE and still create the schema/materialized views.

Use concurrent refresh only after all materialized views have been populated at
least once:

```powershell
psql $env:DATABASE_URL -c "SELECT fah_sai_lpk_mart.refresh_all_materialized_views(true);"
```

## 4. Data Health Gates

Run these checks after ingest and embedding:

```sql
SELECT count(*) AS eval_questions FROM fah_sai_lpk_eval.questions;
SELECT count(*) AS sales_rows FROM fah_sai_lpk_core.fact_sales;
SELECT count(*) AS sales_line_rows FROM fah_sai_lpk_core.fact_sales_line_item;
SELECT count(*) AS bank_rows FROM fah_sai_lpk_core.fact_bank_transaction;
SELECT count(*) AS source_documents FROM fah_sai_lpk_rag.source_documents;
SELECT count(*) AS document_chunks FROM fah_sai_lpk_rag.document_chunks;
SELECT count(*) AS embeddings FROM fah_sai_lpk_rag.chunk_embeddings;
SELECT count(*) AS public_chunks FROM fah_sai_lpk_rag.v_public_retrievable_chunks;
SELECT count(*) AS embedded_public_chunks FROM fah_sai_lpk_rag.mv_public_retrievable_chunks;
SELECT count(*) AS model_surface_count
FROM information_schema.views
WHERE table_schema = 'fah_sai_lpk_model';
SELECT count(*) AS bad_embedding_dims
FROM fah_sai_lpk_rag.chunk_embeddings
WHERE vector_dims(embedding) <> 4096;
```

Expected gates:

- `eval_questions = 100`
- all 31 official CSV-backed core tables are loaded
- `embeddings > 0`
- `bad_embedding_dims = 0`
- `embedded_public_chunks <= public_chunks`
- `model_surface_count = 8`
- `fah_sai_lpk_mart.v_sales_order` count equals `fah_sai_lpk_core.fact_sales`
- `fah_sai_lpk_mart.v_sales_line` count equals `fah_sai_lpk_core.fact_sales_line_item`
- `fah_sai_lpk_mart.v_bank_reconciliation` count equals `fah_sai_lpk_core.fact_bank_transaction`

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
FROM fah_sai_lpk_eval.answer_runs
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
- truncates `fah_sai_lpk_rag.chunk_embeddings`
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
- `scripts/run_question.py --all --limit 100` completes and writes `fah_sai_lpk_eval.answer_runs`.
- L1/L2 questions meet the accepted correctness threshold after review.
- L3/injection questions do not override source-authority rules.
- The exact commit hash, DB snapshot time, and embedding model version are recorded.
