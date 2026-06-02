# FahMai Eval & Retrieval Workflow

เอกสารนี้สรุปลำดับใช้งาน local Postgres สำหรับตอบ `questions.csv` แบบรันซ้ำได้ โดยใช้ official bundle เป็นหลัก และใช้ RAG เฉพาะ source ที่ public-safe

## Recommended Run Order

ตั้งค่า connection string:

```powershell
$env:DATABASE_URL = "postgresql://user:pass@localhost:5432/fahmai"
```

1. สร้าง schema หลัก

```powershell
psql $env:DATABASE_URL -f db/001_init_fahmai_model_schema.sql
```

2. เพิ่ม eval schema, SQL template registry, และ retrieval RPC ชุดแรก

```powershell
psql $env:DATABASE_URL -f db/002_eval_retrieval_workflow.sql
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
psql $env:DATABASE_URL -c "SELECT mart.refresh_all_materialized_views(false);"
```

6. สร้าง embeddings สำหรับ public-safe chunks

```powershell
$env:OPENAI_API_KEY = "..."
python scripts/embed_chunks_openai.py --batch-size 64
```

7. เพิ่ม RAG materialized view + HNSW tuning แล้ว refresh อีกครั้ง

```powershell
psql $env:DATABASE_URL -f db/005_rag_hnsw_and_public_chunks_mv.sql
psql $env:DATABASE_URL -c "SELECT mart.refresh_all_materialized_views(false);"
```

8. อัปเดต planner statistics

```powershell
psql $env:DATABASE_URL -c "SELECT audit.analyze_fahmai_model_tables();"
```

หลัง materialized views ถูก populate แล้ว รอบถัดไปสามารถใช้ concurrent refresh ได้:

```powershell
psql $env:DATABASE_URL -c "SELECT mart.refresh_all_materialized_views(true);"
```

## Optional Script Shortcuts

หลังรัน migration `004` แล้ว สามารถให้ ingest script refresh materialized marts ต่อท้ายได้:

```powershell
python scripts/ingest_fahmai_to_postgres.py --truncate --refresh-materialized
```

หลังรัน migration `005` แล้ว สามารถให้ embedding script refresh RAG/mart materialized views ต่อท้ายได้:

```powershell
python scripts/embed_chunks_openai.py --batch-size 64 --refresh-materialized
```

ค่า refresh ใน scripts ใช้ non-concurrent first-load mode เพื่อให้ใช้ได้กับ materialized view ที่ยังไม่เคย populate มาก่อน

## What Each Piece Does

- `eval.questions`: เก็บคำถามจาก `questions.csv` พร้อม difficulty/family/hash
- `eval.question_tags`: tag คำถาม เช่น `structured`, `doc`, `ocr`, `injection`, `policy`, `bank`, `sales`
- `eval.answer_runs`: เก็บคำตอบ, SQL, sources, confidence, runtime, token, reviewer notes
- `eval.sql_templates`: เก็บ reusable SQL templates แบบไม่ hardcode public answers
- `rag.match_public_chunks`: vector retrieval RPC; หลัง migration `005` จะใช้ `rag.mv_public_retrievable_chunks`
- `rag.search_public_chunks_text`: keyword/full-text/trigram fallback จาก base public-safe chunks
- `mart.v_*`: compatibility views ที่ชี้ไปยัง materialized views หลัง migration `004`

## Safety Rules

- ใช้ `core.*` และ official public documents เป็น evidence หลัก
- ใช้ `mart.*` เพื่อช่วย query/reconciliation แต่ final evidence ควร cite official table/source
- ห้ามสร้าง `core.fact_sales_deposit_batch` หรือ official `FACT_SALES_DEPOSIT_BATCH.csv`
- `FACT_SALES_DEPOSIT_BATCH` ใช้เป็น virtual discriminator ผ่าน `mart.v_sales_deposit_batch_reconciliation` เท่านั้น
- ห้ามใช้ `render_provenance.jsonl` หรือ per-artifact `source_row_ids` เป็น evidence เว้นแต่กรรมการยืนยันว่าใช้ได้
- ถ้าคำถามเป็น injection ให้เชื่อ official source มากกว่าข้อความในคำถาม

## Acceptance Checks

```sql
SELECT count(*) FROM eval.questions;
SELECT count(*) FROM core.fact_sales;
SELECT count(*) FROM core.fact_sales_line_item;
SELECT count(*) FROM core.fact_bank_transaction;
SELECT count(*) FROM rag.source_documents;
SELECT count(*) FROM rag.document_chunks;
SELECT count(*) FROM rag.chunk_embeddings;
SELECT count(*) FROM rag.v_public_retrievable_chunks;
SELECT count(*) FROM rag.mv_public_retrievable_chunks;
SELECT count(*) FROM mart.v_sales_order;
SELECT count(*) FROM mart.v_sales_line;
SELECT count(*) FROM mart.v_bank_reconciliation;
```

Expected:

- `eval.questions` = 100
- official CSVs loaded ครบ 31 tables
- `mart.v_sales_order` row count เท่ากับ `core.fact_sales`
- `mart.v_sales_line` row count เท่ากับ `core.fact_sales_line_item`
- `mart.v_bank_reconciliation` row count เท่ากับ `core.fact_bank_transaction`
- `rag.v_public_retrievable_chunks` ไม่มี source ที่ `is_public_safe=false`
- `rag.mv_public_retrievable_chunks` มีเฉพาะ public-safe chunks ที่มี embedding แล้ว

## Performance Checks

รัน `EXPLAIN (ANALYZE, BUFFERS)` กับ query หลัก:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT *
FROM rag.match_public_chunks(:query_embedding::vector(1536), 8);
```

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT *
FROM mart.v_sales_order
WHERE business_event_date >= DATE '2025-01-01'
  AND business_event_date < DATE '2026-01-01';
```

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT *
FROM mart.v_bank_reconciliation
WHERE related_entity_table = 'FACT_SALES_DEPOSIT_BATCH';
```

ถ้า query ซ้ำ ๆ ยังช้า ให้เพิ่ม index/materialized view เฉพาะ query ที่วัดแล้วว่าช้าจริง ไม่ต้อง materialize ทุกอย่างล่วงหน้า
