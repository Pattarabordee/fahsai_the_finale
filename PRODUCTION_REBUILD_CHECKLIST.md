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

The default run starts PostgreSQL with `pgvector`, starts the BGE-M3 embedding
service, applies the `schema` migration preset (`001,002,007,008,009,010,012,013,014`),
generates/uploads the current model M-Schema artifacts, and runs schema smoke
checks.

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

## 1. Start BGE-M3 Embedding Service On B200

```powershell
docker run --gpus all `
  -p 8080:80 `
  -v hf_cache:/data `
  --pull always `
  ghcr.io/huggingface/text-embeddings-inference:1.7.2 `
  --model-id BAAI/bge-m3 `
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

The returned embedding length must be `1024`.

## 2. Apply Database Migrations

For a fresh database:

```powershell
python scripts/apply_db_migrations.py --migrations schema --verify
```

This creates the source-of-truth schemas plus the compact
`fah_sai_lpk_model` LLM-facing views, OCR artifact schema, BGE-M3
parent-child retrieval schema, prompt-hygiene comments, and M-Schema metadata
handoff table.

When passing explicit comma-separated migration lists in PowerShell, quote the
list so it is sent as one argument:

```powershell
python scripts/apply_db_migrations.py --migrations "010,012,013,014" --dry-run
```

To expose the same allowlisted migration flow as an internal API, run:

```powershell
$env:DB_MIGRATION_ADMIN_TOKEN = "replace-me"
uvicorn scripts.db_migration_api:app --host 127.0.0.1 --port 8081
```

Load data before creating heavier indexes/materialized views:

```powershell
python scripts/ingest_fahmai_to_postgres.py --truncate --skip-rag
python scripts/ingest_rag_batches.py --commit-docs 500 --load-entity-links
python scripts/build_bge_parent_child_chunks.py --profile bge_m3_v1 --replace-profile --json
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
needed when upgrading an older loaded database for the legacy Qwen path. The
production BGE-M3 path writes to `fah_sai_lpk_rag.child_chunk_embeddings`
with `vector(1024)`.

## 3. Generate BGE-M3 Embeddings And M-Schema Handoff

Dry-run the missing chunk count:

```powershell
python scripts/embed_chunks_openai.py `
  --retrieval-profile bge_m3_v1 `
  --provider tei `
  --endpoint http://localhost:8080/embed `
  --batch-size 64 `
  --dry-run
```

Generate embeddings:

```powershell
python scripts/embed_chunks_openai.py `
  --retrieval-profile bge_m3_v1 `
  --provider tei `
  --endpoint http://localhost:8080/embed `
  --batch-size 64 `
  --refresh-materialized
```

Build the BGE-M3 HNSW index:

```powershell
python scripts/apply_db_migrations.py --migrations "011" --verify
psql $env:DATABASE_URL -c "SELECT fah_sai_lpk_mart.refresh_all_materialized_views(false);"
psql $env:DATABASE_URL -c "SELECT fah_sai_lpk_audit.analyze_fahmai_model_tables();"
```

Generate the current model-facing M-Schema artifacts from the live database and
upload them for model-team/API handoff:

```powershell
python scripts/generate_fahmai_mschema.py --schema-mode model --strict-live
python scripts/upload_mschema_artifacts.py --retrieval-profile bge_m3_v1 --json
```

`BAAI/bge-m3` uses 1024-dimensional vectors, so the BGE HNSW index in `011`
can be created directly on `fah_sai_lpk_rag.child_chunk_embeddings`.

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
SELECT count(*) AS bge_child_chunks
FROM fah_sai_lpk_rag.child_chunks
WHERE retrieval_profile = 'bge_m3_v1';
SELECT count(*) AS bge_child_embeddings
FROM fah_sai_lpk_rag.child_chunk_embeddings
WHERE retrieval_profile = 'bge_m3_v1';
SELECT count(*) AS model_surface_count
FROM information_schema.views
WHERE table_schema = 'fah_sai_lpk_model';
SELECT count(*) AS bad_bge_embedding_dims
FROM fah_sai_lpk_rag.child_chunk_embeddings
WHERE retrieval_profile = 'bge_m3_v1'
  AND vector_dims(embedding) <> 1024;
SELECT artifact_format, relation_count, retrieval_profile
FROM fah_sai_lpk_meta.mschema_artifacts
WHERE artifact_name = 'fahmai_model_mschema'
ORDER BY artifact_format;
```

Expected gates:

- `eval_questions = 100`
- all 31 official CSV-backed core tables are loaded
- `bge_child_chunks > 0`
- `bge_child_embeddings > 0`
- `bad_bge_embedding_dims = 0`
- `model_surface_count = 8`
- exactly two uploaded M-Schema artifact rows (`json`, `text`) with `relation_count = 8`
- `fah_sai_lpk_mart.v_sales_order` count equals `fah_sai_lpk_core.fact_sales`
- `fah_sai_lpk_mart.v_sales_line` count equals `fah_sai_lpk_core.fact_sales_line_item`
- `fah_sai_lpk_mart.v_bank_reconciliation` count equals `fah_sai_lpk_core.fact_bank_transaction`

## 5. Retrieval Smoke Test

Run one known eval question and persist the evidence:

```powershell
python scripts/run_question.py `
  --retrieval-profile bge_m3_v1 `
  --question-id FAHMAI-Q-L1-001 `
  --run-label production-smoke-bge `
  --match-count 8
```

Run a small eval sample:

```powershell
python scripts/run_question.py `
  --retrieval-profile bge_m3_v1 `
  --all `
  --limit 10 `
  --run-label production-smoke-bge-10 `
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

Skip `db/006_switch_to_qwen3_embedding_8b.sql` for the production BGE-M3 path.
It is only for upgrading an older legacy Qwen embedding database. Before
running it on a database that has valuable legacy embeddings, take a database
snapshot. The migration intentionally:

- drops the public retrievable materialized view
- drops the old vector retrieval function/index
- truncates `fah_sai_lpk_rag.chunk_embeddings`
- switches `embedding` to `vector(4096)`

Legacy Qwen recovery path:

1. Restore the DB snapshot, or
2. rerun `scripts/embed_chunks_openai.py --retrieval-profile legacy_qwen3`, then
3. rerun `db/005_rag_hnsw_and_public_chunks_mv.sql`, then
4. refresh materialized views.

Production BGE-M3 recovery path, if child chunks or child embeddings are
affected, is to rerun `build_bge_parent_child_chunks.py`, rerun
`embed_chunks_openai.py --retrieval-profile bge_m3_v1`, then rerun
`db/011_rag_bge_m3_hnsw.sql`.

## 7. Production Readiness Gate

Treat the system as ready for a real demo only when:

- A fresh rebuild completes using this checklist.
- TEI returns 1024-dimensional BGE-M3 embeddings.
- `scripts/run_question.py --retrieval-profile bge_m3_v1 --all --limit 100` completes and writes `fah_sai_lpk_eval.answer_runs`.
- `fah_sai_lpk_meta.mschema_artifacts` has current `text` and `json` rows for `fahmai_model_mschema`.
- L1/L2 questions meet the accepted correctness threshold after review.
- L3/injection questions do not override source-authority rules.
- The exact commit hash, DB snapshot time, and embedding model version are recorded.
