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

Create the base schemas, tables, fact-date comments, and compact model-facing
views:

```powershell
python scripts/apply_db_migrations.py --migrations schema --verify
```

Apply the full schema, index, mart, and retrieval layers:

```powershell
python scripts/apply_db_migrations.py --migrations full --verify
```

Preview without touching the database:

```powershell
python scripts/apply_db_migrations.py --migrations schema --dry-run
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
SELECT to_regclass('fah_sai_lpk_rag.chunk_embeddings');
SELECT to_regclass('fah_sai_lpk_eval.questions');
SELECT to_regclass('fah_sai_lpk_model.sales_order_360');
SELECT to_regclass('fah_sai_lpk_model.document_evidence');

SELECT count(*) AS model_surface_count
FROM information_schema.views
WHERE table_schema = 'fah_sai_lpk_model';

SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('vector', 'pgcrypto', 'pg_trgm');
```
