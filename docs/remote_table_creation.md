# Remote Table Creation

Use versioned migrations to create FahMai tables on a remote PostgreSQL
database. Do not send raw `CREATE TABLE` SQL through an ad hoc API request.

## PostgreSQL Protocol Runner

Set the remote connection string:

```powershell
$env:DATABASE_URL = "postgresql://fahmai_app:<password>@0.tcp.ap.ngrok.io:26551/fahmai?sslmode=disable"
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Create the base schemas, tables, fact-date comments, compact model-facing
views, OCR artifacts, BGE-M3 parent-child retrieval objects, prompt-hygiene
comments, and M-Schema metadata handoff table:

```powershell
python scripts/apply_db_migrations.py --migrations schema --verify
```

The `schema` preset expands to `001,002,007,008,009,010,012,013,014`.

Apply the full schema, index, mart, legacy retrieval, BGE-M3 retrieval, and
M-Schema handoff layers:

```powershell
python scripts/apply_db_migrations.py --migrations full --verify
```

The `full` preset applies `011` last so the BGE-M3 HNSW index is created after
the compact child-chunk schema is in place.

Preview without touching the database:

```powershell
python scripts/apply_db_migrations.py --migrations schema --dry-run
python scripts/apply_db_migrations.py --migrations full --dry-run
python scripts/apply_db_migrations.py --migrations "010,012,013,014" --dry-run
```

In PowerShell, quote explicit comma-separated migration lists. Without quotes,
PowerShell treats commas as an array expression before Python receives the
argument.

## BGE-M3 Rebuild And Handoff Flow

After `schema` migrations are applied, load source data, build BGE-M3 child
chunks, embed them, add the BGE HNSW index, then upload the current M-Schema
artifacts:

```powershell
python scripts/ingest_fahmai_to_postgres.py --truncate --skip-rag
python scripts/ingest_rag_batches.py --commit-docs 500 --load-entity-links
python scripts/build_bge_parent_child_chunks.py --profile bge_m3_v1 --replace-profile --json
python scripts/embed_chunks_openai.py --retrieval-profile bge_m3_v1 --provider tei --endpoint http://localhost:8080/embed --batch-size 64 --refresh-materialized
python scripts/apply_db_migrations.py --migrations "011" --verify
python scripts/generate_fahmai_mschema.py --schema-mode model --strict-live
python scripts/upload_mschema_artifacts.py --retrieval-profile bge_m3_v1 --json
python scripts/run_question.py --retrieval-profile bge_m3_v1 --question-id FAHMAI-Q-L1-001 --run-label production-smoke-bge
```

## Internal HTTP API Contract

Use the optional internal admin API when another service needs to trigger table
creation remotely. It still runs the same allowlisted migrations and does not
accept raw SQL.

Start the service on the VM or private network:

```powershell
$env:DATABASE_URL = "postgresql://fahmai_app:<password>@0.tcp.ap.ngrok.io:26551/fahmai?sslmode=disable"
$env:DB_MIGRATION_ADMIN_TOKEN = "<strong-admin-token>"

uvicorn scripts.db_migration_api:app --host 127.0.0.1 --port 8081
```

Apply migrations through the API:

```powershell
$headers = @{ Authorization = "Bearer $env:DB_MIGRATION_ADMIN_TOKEN" }
$body = @{
  migrations = "schema"
  verify = $true
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8081/internal/db/migrations/apply" `
  -Method Post `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

Preview without touching the database:

```powershell
$body = @{
  migrations = "full"
  dry_run = $true
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8081/internal/db/migrations/apply" `
  -Method Post `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

Contract:

```text
POST /internal/db/migrations/apply
Authorization: Bearer <admin-token>
Content-Type: application/json

{
  "migrations": "schema",
  "verify": true
}
```

Rules:

- Never accept raw SQL in the request body.
- Require admin authentication.
- Set `DB_MIGRATION_ADMIN_TOKEN`; missing tokens make protected endpoints return `503`.
- Keep the service internal-only; do not expose it on the public internet.
- Write an audit log for requester, migrations, time, and result at the platform/proxy layer.
- Apply one ordered migration batch at a time.
- Return verification output from `scripts/apply_db_migrations.py --json`.

## Verification

```sql
SELECT to_regclass('fah_sai_lpk_core.fact_sales');
SELECT to_regclass('fah_sai_lpk_rag.child_chunks');
SELECT to_regclass('fah_sai_lpk_rag.child_chunk_embeddings');
SELECT to_regclass('fah_sai_lpk_eval.questions');
SELECT to_regclass('fah_sai_lpk_model.sales_order_360');
SELECT to_regclass('fah_sai_lpk_model.document_evidence');
SELECT to_regclass('fah_sai_lpk_meta.mschema_artifacts');

SELECT count(*) AS model_surface_count
FROM information_schema.views
WHERE table_schema = 'fah_sai_lpk_model';

SELECT count(*) AS bge_child_chunks
FROM fah_sai_lpk_rag.child_chunks
WHERE retrieval_profile = 'bge_m3_v1';

SELECT count(*) AS bge_child_embeddings
FROM fah_sai_lpk_rag.child_chunk_embeddings
WHERE retrieval_profile = 'bge_m3_v1';

SELECT count(*) AS bad_bge_embedding_dims
FROM fah_sai_lpk_rag.child_chunk_embeddings
WHERE retrieval_profile = 'bge_m3_v1'
  AND vector_dims(embedding) <> 1024;

SELECT artifact_format, relation_count, retrieval_profile
FROM fah_sai_lpk_meta.mschema_artifacts
WHERE artifact_name = 'fahmai_model_mschema'
ORDER BY artifact_format;

SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('vector', 'pgcrypto', 'pg_trgm');
```
