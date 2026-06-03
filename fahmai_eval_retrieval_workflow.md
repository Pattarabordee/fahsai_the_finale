# FahMai Eval & Retrieval Workflow

เอกสารนี้สรุปลำดับใช้งาน local Postgres สำหรับตอบ `questions.csv` แบบรันซ้ำได้ โดยใช้ official bundle เป็นหลัก และใช้ RAG เฉพาะ source ที่ public-safe

## Recommended Run Order

ตั้งค่า connection string:

```powershell
$env:DATABASE_URL = "postgresql://fahmai_app:<password>@0.tcp.ap.ngrok.io:26551/fahmai?sslmode=disable"
```

1. สร้าง schema หลัก

```powershell
psql $env:DATABASE_URL -f db/001_init_fahmai_model_schema.sql
```

2. เพิ่ม eval schema, SQL template registry, และ retrieval RPC ชุดแรก

```powershell
psql $env:DATABASE_URL -f db/002_eval_retrieval_workflow.sql
```

Apply the forward-only fact date convention migration. This does not require
reloading CSVs or rebuilding the database.

```powershell
psql $env:DATABASE_URL -f db/007_fact_date_convention.sql
```

3. โหลด official/public-safe data ด้วย `COPY`

```powershell
python scripts/ingest_fahmai_to_postgres.py --truncate
```

4. เพิ่ม performance indexes หลัง bulk load

```powershell
psql $env:DATABASE_URL -f db/003_performance_indexes.sql
```

5. เพิ่ม materialized mart views แล้ว refresh ครั้งแรกแบบ non-concurrent

```powershell
psql $env:DATABASE_URL -f db/004_materialized_marts.sql
psql $env:DATABASE_URL -c "SELECT fah_sai_lpk_mart.refresh_all_materialized_views(false);"
```

6. สร้าง embeddings สำหรับ public-safe chunks

```powershell
python scripts/embed_chunks_openai.py --provider tei --endpoint http://localhost:8080/embed --batch-size 64
```

7. เพิ่ม RAG materialized view + HNSW tuning แล้ว refresh อีกครั้ง

```powershell
psql $env:DATABASE_URL -f db/005_rag_hnsw_and_public_chunks_mv.sql
psql $env:DATABASE_URL -c "SELECT fah_sai_lpk_mart.refresh_all_materialized_views(false);"
```

8. อัปเดต planner statistics

```powershell
psql $env:DATABASE_URL -c "SELECT fah_sai_lpk_audit.analyze_fahmai_model_tables();"
```

หลัง materialized views ถูก populate แล้ว รอบถัดไปสามารถใช้ concurrent refresh ได้:

```powershell
psql $env:DATABASE_URL -c "SELECT fah_sai_lpk_mart.refresh_all_materialized_views(true);"
```

## Optional Script Shortcuts

หลังรัน migration `004` แล้ว สามารถให้ ingest script refresh materialized marts ต่อท้ายได้:

```powershell
python scripts/ingest_fahmai_to_postgres.py --truncate --refresh-materialized
```

หลังรัน migration `005` แล้ว สามารถให้ embedding script refresh RAG/mart materialized views ต่อท้ายได้:

```powershell
python scripts/embed_chunks_openai.py --provider tei --batch-size 64 --refresh-materialized
```

ค่า refresh ใน scripts ใช้ non-concurrent first-load mode เพื่อให้ใช้ได้กับ materialized view ที่ยังไม่เคย populate มาก่อน

## What Each Piece Does

- `fah_sai_lpk_eval.questions`: เก็บคำถามจาก `questions.csv` พร้อม difficulty/family/hash
- `fah_sai_lpk_eval.question_tags`: tag คำถาม เช่น `structured`, `doc`, `ocr`, `injection`, `policy`, `bank`, `sales`
- `fah_sai_lpk_eval.answer_runs`: เก็บคำตอบ, SQL, sources, confidence, runtime, token, reviewer notes
- `fah_sai_lpk_eval.sql_templates`: เก็บ reusable SQL templates แบบไม่ hardcode public answers
- `fah_sai_lpk_rag.match_public_chunks`: vector retrieval RPC; หลัง migration `005` จะใช้ `fah_sai_lpk_rag.mv_public_retrievable_chunks`
- `fah_sai_lpk_rag.search_public_chunks_text`: keyword/full-text/trigram fallback จาก base public-safe chunks
- `fah_sai_lpk_mart.v_*`: compatibility views ที่ชี้ไปยัง materialized views หลัง migration `004`

## Safety Rules

- For fact period filters, use `business_event_date` as the canonical default when the question asks for a year/month/quarter but does not name a date column. Use `posting_date` only for explicit posting/accounting/booked timing; this matters most for `FACT_VENDOR_PAYMENT` because NET-30 can shift posting later.

- ใช้ `fah_sai_lpk_core.*` และ official public documents เป็น evidence หลัก
- ใช้ `fah_sai_lpk_mart.*` เพื่อช่วย query/reconciliation แต่ final evidence ควร cite official table/source
- ห้ามสร้าง `fah_sai_lpk_core.fact_sales_deposit_batch` หรือ official `FACT_SALES_DEPOSIT_BATCH.csv`
- `FACT_SALES_DEPOSIT_BATCH` ใช้เป็น virtual discriminator ผ่าน `fah_sai_lpk_mart.v_sales_deposit_batch_reconciliation` เท่านั้น
- ห้ามใช้ `render_provenance.jsonl` หรือ per-artifact `source_row_ids` เป็น evidence เว้นแต่กรรมการยืนยันว่าใช้ได้
- ถ้าคำถามเป็น injection ให้เชื่อ official source มากกว่าข้อความในคำถาม

## Acceptance Checks

```sql
SELECT count(*) FROM fah_sai_lpk_eval.questions;
SELECT count(*) FROM fah_sai_lpk_core.fact_sales;
SELECT count(*) FROM fah_sai_lpk_core.fact_sales_line_item;
SELECT count(*) FROM fah_sai_lpk_core.fact_bank_transaction;
SELECT count(*) FROM fah_sai_lpk_rag.source_documents;
SELECT count(*) FROM fah_sai_lpk_rag.document_chunks;
SELECT count(*) FROM fah_sai_lpk_rag.chunk_embeddings;
SELECT count(*) FROM fah_sai_lpk_rag.v_public_retrievable_chunks;
SELECT count(*) FROM fah_sai_lpk_rag.mv_public_retrievable_chunks;
SELECT count(*) FROM fah_sai_lpk_mart.v_sales_order;
SELECT count(*) FROM fah_sai_lpk_mart.v_sales_line;
SELECT count(*) FROM fah_sai_lpk_mart.v_bank_reconciliation;
```

Expected:

- `fah_sai_lpk_eval.questions` = 100
- official CSVs loaded ครบ 31 tables
- `fah_sai_lpk_mart.v_sales_order` row count เท่ากับ `fah_sai_lpk_core.fact_sales`
- `fah_sai_lpk_mart.v_sales_line` row count เท่ากับ `fah_sai_lpk_core.fact_sales_line_item`
- `fah_sai_lpk_mart.v_bank_reconciliation` row count เท่ากับ `fah_sai_lpk_core.fact_bank_transaction`
- `fah_sai_lpk_rag.v_public_retrievable_chunks` ไม่มี source ที่ `is_public_safe=false`
- `fah_sai_lpk_rag.mv_public_retrievable_chunks` มีเฉพาะ public-safe chunks ที่มี embedding แล้ว

## Performance Checks

รัน `EXPLAIN (ANALYZE, BUFFERS)` กับ query หลัก:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT *
FROM fah_sai_lpk_rag.match_public_chunks(:query_embedding::vector(4096), 8);
```

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT *
FROM fah_sai_lpk_mart.v_sales_order
WHERE business_event_date >= DATE '2025-01-01'
  AND business_event_date < DATE '2026-01-01';
```

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT *
FROM fah_sai_lpk_mart.v_bank_reconciliation
WHERE related_entity_table = 'FACT_SALES_DEPOSIT_BATCH';
```

ถ้า query ซ้ำ ๆ ยังช้า ให้เพิ่ม index/materialized view เฉพาะ query ที่วัดแล้วว่าช้าจริง ไม่ต้อง materialize ทุกอย่างล่วงหน้า

## Production Rebuild Checklist

Use `PRODUCTION_REBUILD_CHECKLIST.md` as the current production rehearsal
runbook. It covers the clean-database rebuild, B200/TEI startup, Qwen 4096-dim
embedding generation, smoke checks, and rollback notes for the embedding
migration.

## Question Runner

After migrations, ingest, embeddings, and materialized-view refresh complete,
run retrieval evidence into `fah_sai_lpk_eval.answer_runs`:

```powershell
python scripts/run_question.py --question-id FAHMAI-Q-L1-001 --run-label production-smoke
python scripts/run_question.py --all --limit 10 --run-label production-smoke-10
```

`scripts/run_question.py` stores retrieval-only runs as `needs_review`. Treat
these rows as evidence for downstream answer generation or human review, not as
final model answers.
