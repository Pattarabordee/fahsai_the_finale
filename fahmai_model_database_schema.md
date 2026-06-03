# FahMai Model Database Schema

เอกสารนี้อธิบาย PostgreSQL schema สำหรับทีม Model/RAG ของ Hackathon FahMai โดยออกแบบให้ใช้ official CSV bundle เป็นหลัก และใช้ `pgvector` สำหรับ semantic retrieval จากเอกสาร/ข้อความ/OCR-safe text

## Executive Summary

- ใช้ `db/001_init_fahmai_model_schema.sql` เป็น migration เริ่มต้นสำหรับ PostgreSQL + `pgvector`
- แบ่ง schema เป็น 5 ชั้น: `raw`, `core`, `rag`, `mart`, `audit`
- `core` เก็บ official tables ทั้ง 31 CSV เป็น typed relational schema
- `rag` เก็บเอกสาร, chunks, embeddings, และ entity links ที่ปลอดภัยต่อการใช้เป็น evidence
- `audit` เก็บ ingestion/retrieval trace และ provenance ที่ยังไม่ควรใช้ตอบคำถาม
- `mart` เป็น safe views สำหรับทีม Model เพื่อกัน row explosion และกันการ join ผิด grain
- `FACT_SALES_DEPOSIT_BATCH` ไม่ถูกสร้างเป็น official table; ใช้เฉพาะ `fah_sai_lpk_mart.v_sales_deposit_batch_reconciliation` เป็น virtual QA/reconciliation view

## Canonical Fact Date Convention

- All `fah_sai_lpk_core.fact_*` tables keep four bitemporal-style date columns: `business_event_date`, `posting_date`, `effective_date`, and `as_of_date`.
- If a question asks for a period such as year 2568, a month, or a quarter without naming a date column, filter facts on `business_event_date`.
- Use `posting_date` only when the question explicitly asks for posted/booked/accounting timing. This matters most for `FACT_VENDOR_PAYMENT`, where `posting_date` may lag `business_event_date` by about 28 days because of NET-30 terms.
- Treat fact `effective_date` as metadata rather than the default period filter. Treat `as_of_date` as bundle/snapshot metadata, not the event period.
- Convert BE years before filtering. For example, year 2568 is `business_event_date >= DATE '2025-01-01' AND business_event_date < DATE '2026-01-01'`.

## Schema Layers

### `raw`

ใช้เป็น landing layer จาก CSV/OCR โดยทุก column เป็น `text`

เหตุผล:
- โหลดไฟล์ CSV ได้ง่าย
- กันปัญหา ID ใหญ่ถูกอ่านเป็นตัวเลขแล้วเพี้ยน
- แยกปัญหา parsing/casting ออกจาก official source

Official CSV ที่รองรับมี 31 tables:
- 16 dimension/lookup tables
- 14 fact tables
- 1 document inventory table: `T2_DOC_INVENTORY`

### `core`

ใช้เป็น typed official data layer สำหรับ query หลัก

กฎสำคัญ:
- ID-like fields ใช้ `text`
- เงินใช้ `numeric(18,2)`
- วันที่ใช้ `date`
- timestamp ใช้ `timestamptz`
- polymorphic fields เช่น `related_entity_table`, `related_entity_id`, `source_table`, `source_pk` ไม่บังคับเป็น FK ปกติ

ตัวอย่าง core tables:
- `fah_sai_lpk_core.fact_sales`
- `fah_sai_lpk_core.fact_sales_line_item`
- `fah_sai_lpk_core.fact_bank_transaction`
- `fah_sai_lpk_core.fact_vendor_payment`
- `fah_sai_lpk_core.dim_product`
- `fah_sai_lpk_core.dim_customer`
- `fah_sai_lpk_core.t2_doc_inventory`

### `rag`

ใช้เป็น unified retrieval layer สำหรับทีม Model

ตารางหลัก:
- `fah_sai_lpk_rag.source_documents`: metadata ของเอกสาร/ไฟล์/ข้อความ
- `fah_sai_lpk_rag.document_chunks`: text chunks ที่นำไปค้นได้
- `fah_sai_lpk_rag.chunk_embeddings`: embedding แบบ `vector(4096)`
- `fah_sai_lpk_rag.entity_links`: public-safe links จากเอกสาร/chunk กลับไปหา official entities

ค่า default:
- embedding model: `Qwen/Qwen3-Embedding-8B`
- embedding dimension: `4096`
- vector index: HNSW cosine
- full-text index: GIN บน `search_tsv`

Retriever paths:
- `fah_sai_lpk_rag.v_public_retrievable_chunks` สำหรับ inspection, fallback, และ chunks ที่ยังไม่มี embedding
- `fah_sai_lpk_rag.match_public_chunks(...)` หลังรัน `db/005_rag_hnsw_and_public_chunks_mv.sql`; function นี้ใช้ `fah_sai_lpk_rag.mv_public_retrievable_chunks` เพื่อลด repeated joins ระหว่าง chunks/documents/embeddings

view นี้กรองเฉพาะ:
- `source_documents.is_public_safe = true`
- `document_chunks.is_public_safe = true`

### `mart`

ใช้เป็น model/query views ที่ join แล้วปลอดภัยกว่า query จาก fact หลายตารางตรง ๆ

Views ที่สร้างไว้:
- `fah_sai_lpk_mart.v_sales_order`: 1 row ต่อ `fact_sales.txn_id`
- `fah_sai_lpk_mart.v_sales_line`: 1 row ต่อ `fact_sales_line_item.line_item_id`
- `fah_sai_lpk_mart.v_bank_reconciliation`: 1 row ต่อ `fact_bank_transaction.bank_txn_id`
- `fah_sai_lpk_mart.v_sales_deposit_batch_reconciliation`: virtual deposit-batch QA view
- `fah_sai_lpk_mart.v_vendor_payment`: vendor payment พร้อม contract/bank context

กฎสำหรับ Model:
- ถ้าจะตอบคำถามระดับ order ใช้ `fah_sai_lpk_mart.v_sales_order`
- ถ้าจะตอบคำถามระดับสินค้า/line item ใช้ `fah_sai_lpk_mart.v_sales_line`
- ถ้าจะตอบคำถาม bank/reconciliation ใช้ `fah_sai_lpk_mart.v_bank_reconciliation`
- อย่า sum amount จาก fact ที่ถูก repeat หลัง join ลง grain ที่ละเอียดกว่า

### `audit`

ใช้เก็บ trace และข้อมูลที่ไม่ควรเป็น evidence หลัก

ตารางหลัก:
- `fah_sai_lpk_audit.ingestion_runs`
- `fah_sai_lpk_audit.source_safety_flags`
- `fah_sai_lpk_audit.provenance_entity_links`
- `fah_sai_lpk_audit.retrieval_traces`

ข้อมูลจาก OCR provenance JSON ที่มีลักษณะ grader-only หรือเสี่ยง data leak ให้เก็บใน `fah_sai_lpk_audit.provenance_entity_links` เท่านั้น ไม่โหลดเข้า `fah_sai_lpk_rag.entity_links` เว้นแต่กรรมการยืนยันว่าใช้ได้

## RAG Data Flow

1. โหลด official CSV เข้า `fah_sai_lpk_raw.*`
2. cast/normalize เข้า `fah_sai_lpk_core.*`
3. โหลด official docs และ OCR-safe text เข้า `fah_sai_lpk_rag.source_documents`
4. split text เป็น chunks เข้า `fah_sai_lpk_rag.document_chunks`
5. embed chunks เข้า `fah_sai_lpk_rag.chunk_embeddings`
6. โหลด public-safe entity links เข้า `fah_sai_lpk_rag.entity_links`
7. query ด้วย hybrid retrieval:
   - vector search จาก `chunk_embeddings.embedding`
   - full-text search จาก `document_chunks.search_tsv`
   - entity filter จาก `entity_links`
8. เขียนคำตอบโดย cite official source จาก `core`/official file path ไม่ใช่ helper/provenance

## Source Safety Rules

ใช้ได้เป็น evidence หลัก:
- official tables ใน `super-ai-engineer-season-6-fah-mai-the-finale/tables`
- official docs/reports/logs/renders ที่อยู่ใน bundle ปกติ
- OCR text ที่ไม่มี grader-only provenance หรือไม่ได้ใช้ `source_row_ids` เป็นทางลัด
- `derived/DOC_ENTITY_LINKS.csv` เฉพาะ row ที่ `is_public_safe=true`
- `derived/ARTIFACT_ENTITY_LINKS.csv` เฉพาะ row ที่ `is_public_safe=true`

ใช้ได้เฉพาะ QA/audit/internal trace:
- OCR provenance links ที่ `is_public_safe=false`
- `render_provenance.jsonl`
- per-artifact JSON ที่ expose mapping กลับ source tables ผ่าน grader-only provenance
- `derived/sales_deposit_batch_reconciliation.csv`

## `FACT_SALES_DEPOSIT_BATCH` Policy

กรรมการยืนยันว่า `FACT_SALES_DEPOSIT_BATCH` ถูกลบออกจาก bundle โดยตั้งใจ ดังนั้น schema นี้ไม่สร้าง `fah_sai_lpk_core.fact_sales_deposit_batch`

สิ่งที่มีแทน:
- `FACT_BANK_TRANSACTION.related_entity_table = 'FACT_SALES_DEPOSIT_BATCH'` เป็น literal virtual discriminator
- `fah_sai_lpk_mart.v_sales_deposit_batch_reconciliation` reconstruct batch จาก `fah_sai_lpk_core.fact_sales` เพื่อ QA/reconciliation

เวลา Model ตอบคำถาม final:
- cite `FACT_BANK_TRANSACTION`
- cite `FACT_SALES`
- cite downstream tables เช่น `FACT_SALES_LINE_ITEM`, `DIM_PRODUCT` ถ้าต้องอธิบายสินค้า/แคมเปญ
- ไม่ cite virtual view เป็น official source

## Recommended Retrieval Pattern

### Semantic search

```sql
SELECT
    chunk_id,
    source_path,
    source_kind,
    chunk_text,
    embedding <=> $1::vector AS cosine_distance
FROM fah_sai_lpk_rag.v_public_retrievable_chunks
WHERE embedding IS NOT NULL
ORDER BY embedding <=> $1::vector
LIMIT 8;
```

### Full-text search

```sql
SELECT
    chunk_id,
    source_path,
    source_kind,
    chunk_text,
    ts_rank(search_tsv, plainto_tsquery('simple', $1)) AS rank
FROM fah_sai_lpk_rag.v_public_retrievable_chunks
WHERE search_tsv @@ plainto_tsquery('simple', $1)
ORDER BY rank DESC
LIMIT 8;
```

### Entity-linked retrieval

```sql
SELECT
    c.chunk_id,
    c.source_path,
    c.chunk_text,
    el.linked_table,
    el.linked_column,
    el.entity_id
FROM fah_sai_lpk_rag.v_public_retrievable_chunks c
JOIN fah_sai_lpk_rag.entity_links el
  ON el.chunk_id = c.chunk_id
WHERE el.is_public_safe = true
  AND el.linked_table = 'DIM_PRODUCT'
  AND el.entity_id = $1;
```

## Safe Mart Usage

### Sales order grain

ใช้เมื่อคำถามนับ order, channel, branch, customer, payment

```sql
SELECT count(*) FROM fah_sai_lpk_mart.v_sales_order;
```

Expected row count หลัง load official data:
- `117,105`

### Sales line grain

ใช้เมื่อคำถามถาม SKU, product mix, line discount, care-plus

```sql
SELECT count(*) FROM fah_sai_lpk_mart.v_sales_line;
```

Expected row count หลัง load official data:
- `309,129`

### Bank reconciliation grain

ใช้เมื่อคำถามถาม bank transaction, settlement, deposit batch

```sql
SELECT count(*) FROM fah_sai_lpk_mart.v_bank_reconciliation;
```

Expected row count หลัง load official data:
- `65,334`

## Load/Validation Checklist

หลังสร้าง schema และ load data แล้วควรตรวจ:

- official CSV loaded ครบ 31 tables
- row counts ตรงกับไฟล์จริง
- primary keys ใน `core` ไม่ซ้ำและไม่ null
- FK สำคัญผ่าน
- `fah_sai_lpk_rag.chunk_embeddings.embedding` ทุก row มี dimension 4096
- `fah_sai_lpk_rag.v_public_retrievable_chunks` ไม่มี source ที่ `is_public_safe=false`
- `fah_sai_lpk_mart.v_sales_order` มี row count เท่ากับ `fah_sai_lpk_core.fact_sales`
- `fah_sai_lpk_mart.v_sales_line` มี row count เท่ากับ `fah_sai_lpk_core.fact_sales_line_item`
- `fah_sai_lpk_mart.v_bank_reconciliation` มี row count เท่ากับ `fah_sai_lpk_core.fact_bank_transaction`
- `fah_sai_lpk_mart.v_sales_deposit_batch_reconciliation` ใช้สำหรับ QA เท่านั้น ไม่ถูก treat เป็น official table

## Files Added

- `db/001_init_fahmai_model_schema.sql`
- `db/002_eval_retrieval_workflow.sql`
- `db/003_performance_indexes.sql`
- `db/004_materialized_marts.sql`
- `db/005_rag_hnsw_and_public_chunks_mv.sql`
- `db/sql_templates/fahmai_question_cookbook.sql`
- `db/007_fact_date_convention.sql`
- `db/008_model_facing_schema.sql`
- `scripts/ingest_fahmai_to_postgres.py`
- `scripts/embed_chunks_openai.py`
- `fahmai_model_erd.mmd`
- `fahmai_model_database_schema.md`
- `fahmai_eval_retrieval_workflow.md`

## Notes for the Model Team

- For fact period questions, default to `business_event_date` when the question says year/month/quarter without naming a date column. Use `posting_date` only for explicit posting/accounting/booked timing; `FACT_VENDOR_PAYMENT` is the main lagging-date case because of NET-30.

- Default Text-to-SQL prompts should use only `fah_sai_lpk_model` surfaces unless debugging source data. The compact schema has 8 views: `sales_order_360`, `sales_line_360`, `finance_event`, `customer_ops_event`, `inventory_event`, `product_catalog`, `policy_catalog`, and `document_evidence`.

- อย่า query จาก `raw` เพื่อทำ final answer ถ้าไม่จำเป็น; ใช้ `core` หรือ `mart`
- อย่า flatten fact-to-fact หลายตัวโดยไม่ aggregate ฝั่งลูกก่อน
- ถ้าเจอ `related_entity_table` ให้ route ตาม discriminator เสมอ
- ถ้าคำถามมี temporal logic ให้ใช้ date column ตามโจทย์ระบุ เช่น `business_event_date` หรือ `posting_date`
- ถ้าโจทย์ไม่ระบุ date-resolution rule สำหรับ policy/contract ให้ log assumption ในคำตอบ/trace
- ถ้าใช้ OCR ให้แยก OCR text ที่อ่านได้จาก provenance mapping ที่กรรมการอาจถือว่าเป็น data leak

## Learning Reference

DataCamp มี tutorial ชื่อ `pgvector Tutorial: Integrate Vector Search into PostgreSQL` สำหรับทีมที่อยากทบทวนพื้นฐาน pgvector:

https://app.datacamp.com/learn/tutorials/pgvector-tutorial
