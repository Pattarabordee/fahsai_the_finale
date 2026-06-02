# FahMai — Project Overview (Single Source of Truth)

> **For teams and AI agents** — Read this entire document before writing code, queries, or migrations.
> It defines what exists, what is authoritative, what is dangerous, and what is still pending.

---

## Table of Contents

1. [What Is This Project?](#1-what-is-this-project)
2. [Repository Layout](#2-repository-layout)
3. [Tech Stack](#3-tech-stack)
4. [Five-Schema Database Architecture](#4-five-schema-database-architecture)
5. [Core Schema — Key Tables & Row Counts](#5-core-schema--key-tables--row-counts)
6. [Entity Relationships (ERD)](#6-entity-relationships-erd)
7. [Mart Layer — Materialized Views](#7-mart-layer--materialized-views)
8. [Full Data Pipeline](#8-full-data-pipeline)
9. [RAG Retrieval Architecture](#9-rag-retrieval-architecture)
10. [Polymorphic Join Routing](#10-polymorphic-join-routing)
11. [Safe Join Rules](#11-safe-join-rules)
12. [Source Authority Hierarchy](#12-source-authority-hierarchy)
13. [Migration Execution Order](#13-migration-execution-order)
14. [Scripts Reference](#14-scripts-reference)
15. [Optimization Work Status](#15-optimization-work-status)
16. [Data-Quality Warnings](#16-data-quality-warnings)
17. [Rules of Engagement for AI Agents](#17-rules-of-engagement-for-ai-agents)

---

## 1. What Is This Project?

**FahMai** is a multi-channel electronics retailer in Thailand.
This repo is a complete **Data Warehouse + RAG system** for the Super AI Engineer Season 6 — Hackathon 4 competition.

The system:
- Ingests **2 years of operational data** (2024-01-01 → 2025-12-31, released 2026-01-15)
- Stores structured data in a **typed PostgreSQL warehouse** (5 schemas, 31 official tables)
- Chunks and embeds **50,000+ unstructured documents** (chats, memos, logs, reports)
- Exposes **hybrid SQL + vector retrieval** so an LLM can answer business questions accurately

---

## 2. Repository Layout

```
fahmai/
│
├── db/                                         SQL migrations — run in order 001 → 007
│   ├── 001_init_fahmai_model_schema.sql        All schemas + tables + basic views
│   ├── 002_eval_retrieval_workflow.sql         Eval schema, SQL templates, retrieval RPCs
│   ├── 003_performance_indexes.sql             All missing indexes + ANALYZE function
│   ├── 004_materialized_marts.sql              Materialized mart views + refresh function
│   ├── 005_rag_hnsw_and_public_chunks_mv.sql   HNSW rebuild + mv_public_retrievable_chunks
│   ├── 006_hybrid_retrieval.sql                ⚠ TODO  hybrid_search_public_chunks (RRF)
│   ├── 007_session_tuning.sql                  ⚠ TODO  pg_stat_statements + work_mem
│   └── sql_templates/
│       └── fahmai_question_cookbook.sql        Reusable parameterised query patterns
│
├── scripts/
│   ├── ingest_fahmai_to_postgres.py            Load CSVs + markdown docs → DB
│   ├── embed_chunks_openai.py                  Generate embeddings via Qwen/TEI or OpenAI-compatible API
│   └── run_question.py                         ⚠ TODO  end-to-end answer pipeline
│
├── super-ai-engineer-season-6-fah-mai-the-finale/
│   ├── tables/        31 official CSV files   ← PRIMARY structured source of truth
│   ├── docs/          memos, minutes, emails, 37 441 LINE OA chats, 15 802 LINE Works threads
│   ├── reports/       32 monthly OPS + quarterly FIN reports
│   ├── logs/          7 935 POS / web / WMS / helpdesk / PayWise logs
│   └── renders/       6 128 PDFs & PNGs  (bank statements, receipts, invoices, warranties)
│
├── derived/           QA helpers only — NOT official sources for final answers
├── OVERVIEW.md        ← this file
└── db/optimization_round*.md    Codex task lists per round
```

---

## 3. Tech Stack

| Layer | Technology | Details |
|-------|-----------|---------|
| Database | PostgreSQL 15+ | 5 schemas, 31 core tables |
| Vector search | pgvector + HNSW | `m=16`, `ef_construction=128`, 4 096-dim |
| Full-text search | GIN on tsvector | dictionary: `simple` (Thai + English) |
| Trigram search | pg_trgm | fuzzy / partial keyword match |
| Monitoring | pg_stat_statements | slow query tracking |
| Embedding model | `Qwen/Qwen3-Embedding-8B` | TEI/OpenAI-compatible API, dimension 4 096 |
| Ingestion | Python 3.11 + psycopg[binary] | bulk `COPY FROM STDIN` |
| Languages in data | Thai + English mixed | all documents and column values |

---

## 4. Five-Schema Database Architecture

```
 ┌─────────────────────────────────────────────────────────────────────────────────┐
 │                         PostgreSQL Database                                      │
 │                                                                                  │
 │  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────────────┐  │
 │  │   raw.*          │    │   core.*          │    │   rag.*                  │  │
 │  │                  │    │                   │    │                          │  │
 │  │  Landing zone    │───►│  Typed official   │    │  source_documents        │  │
 │  │  ALL columns     │    │  31 tables        │    │  document_chunks         │  │
 │  │  TEXT, no FKs    │    │  FK-constrained   │    │  chunk_embeddings        │  │
 │  │                  │    │  numeric(18,2)     │    │  entity_links            │  │
 │  │  Purpose:        │    │  date / timestamptz│    │                          │  │
 │  │  safe CSV load   │    │                   │    │  Purpose:                │  │
 │  │  no type errors  │    │  Source of truth  │    │  hybrid retrieval        │  │
 │  └──────────────────┘    └────────┬──────────┘    └──────────┬───────────────┘  │
 │         ▲                         │                           │                  │
 │         │                         ▼                           ▼                  │
 │   31 CSV files           ┌──────────────────┐    ┌──────────────────────────┐  │
 │   COPY FROM STDIN        │   mart.*          │    │   audit.*                │  │
 │                          │                   │    │                          │  │
 │   50 K+ markdown docs    │  mv_sales_order   │    │  ingestion_runs          │  │
 │   chunk + embed          │  mv_sales_line    │    │  provenance_entity_links │  │
 │   ──────────────────►    │  mv_bank_recon    │    │  source_safety_flags     │  │
 │                          │  mv_vendor_payment│    │  retrieval_traces        │  │
 │                          │                   │    │                          │  │
 │                          │  Pre-joined,       │    │  Purpose:                │  │
 │                          │  indexed,          │    │  QA/trace only           │  │
 │                          │  query-ready      │    │  never cite in answers   │  │
 │                          └──────────┬─────── ┘    └──────────────────────────┘  │
 │                                     │                                            │
 │                                     ▼                                            │
 │                           ┌──────────────────┐                                  │
 │                           │   eval.*          │                                  │
 │                           │                   │                                  │
 │                           │  questions        │                                  │
 │                           │  question_tags    │                                  │
 │                           │  answer_runs      │                                  │
 │                           │  sql_templates    │                                  │
 │                           │  source_authority │                                  │
 │                           └──────────────────┘                                  │
 └─────────────────────────────────────────────────────────────────────────────────┘
```

**Rule**: Never query `raw.*` for a final answer. Always use `core.*` or `mart.mv_*`.

---

## 5. Core Schema — Key Tables & Row Counts

```
 DIMENSION TABLES (lookup / reference)
 ──────────────────────────────────────────────────────────────
  dim_branch              5 rows     retail locations
  dim_department          ~20 rows   org structure
  dim_employee            ~300 rows  full org chart
  dim_customer            large      B2C + B2B customers
  dim_product             ~200 rows  SKU master
  dim_vendor              ~50 rows   supplier master
  dim_date                730 rows   2024-01-01 → 2025-12-31 + Thai holidays
  dim_policy_version      ~30 rows   signing authority, refund thresholds
  dim_promo_campaign      7 rows
  dim_vendor_contract_version         multiple versions per vendor ⚠
  dim_care_plus_sku_tier
  dim_promo_mechanic      8 rows     (1 campaign has 2 mechanics ⚠)
  dim_signing_authority_ladder
  dim_product_recall_history          (1 SKU has 3 rows ⚠)

 FACT TABLES (transactional data)
 ──────────────────────────────────────────────────────────────
  fact_sales                  117 105 rows   PRIMARY FACT — order grain
  fact_sales_line_item        309 129 rows   line-item grain (up to 620 per order ⚠)
  fact_bank_transaction        65 334 rows   polymorphic related_entity_table ⚠
  fact_loyalty_ledger         118 857 rows   1 255 txns have multiple rows ⚠
  fact_inventory_movement     310 827 rows   polymorphic related_txn_id ⚠
  fact_inventory_monthly_snapshot  26 220    stock balance (not flow)
  fact_payroll                 14 400 rows
  fact_cs_interaction          14 368 rows
  fact_return                   7 144 rows   6 txns have multiple returns ⚠
  fact_refund_paid              ~7 100 rows
  fact_warranty_claim           3 973 rows
  fact_promo_redemption         ~rows        4 txns have duplicate rows ⚠
  fact_shipping                 ~rows
  fact_vendor_payment             809 rows

  ⚠ = requires aggregation or deduplication before joining to a coarser grain
```

---

## 6. Entity Relationships (ERD)

```
                     ┌──────────────────┐
                     │  DIM_BRANCH      │
                     │  branch_code PK  │
                     └────────┬─────────┘
                              │ branch_code
              ┌───────────────┼──────────────────┐
              │               │                  │
              ▼               ▼                  ▼
  ┌───────────────┐  ┌─────────────────┐  ┌─────────────────┐
  │ DIM_EMPLOYEE  │  │   FACT_SALES    │  │ DIM_BANK_ACCOUNT│
  │ employee_id PK│◄─│ txn_id      PK  │  │ account_id   PK │
  │ branch_code FK│  │ branch_code FK  │  │ branch_code  FK │
  │ dept_code   FK│  │ customer_id FK  │  └─────────────────┘
  │ position_levelFK │ employee_id FK  │
  └───────────────┘  │ promo_campaign  │◄──── DIM_PROMO_CAMPAIGN
                     │    _id      FK  │       campaign_id PK
                     │ settlement_bank │
                     │   _txn_id   FK ─┼──►  FACT_BANK_TRANSACTION
                     │ net_total_thb   │      bank_txn_id  PK
                     │ schema_version  │      related_entity_table  ⚠ polymorphic
                     │ is_b2b          │      related_entity_id     ⚠ polymorphic
                     └────────┬────────┘
                              │ txn_id
              ┌───────────────┼─────────────────────┐
              │               │                     │
              ▼               ▼                     ▼
  ┌────────────────────┐  ┌──────────────────┐  ┌────────────────────┐
  │ FACT_SALES_LINE    │  │ FACT_LOYALTY     │  │ FACT_RETURN        │
  │   _ITEM            │  │   _LEDGER        │  │ return_id       PK │
  │ line_item_id    PK │  │ ledger_id     PK │  │ original_txn_id FK │
  │ txn_id          FK │  │ txn_id        FK │  │ line_item_id    FK │
  │ sku_id          FK │  │ customer_id   FK │  │ sku_id          FK │
  │ quantity           │  │ points_delta     │  │ customer_id     FK │
  │ line_total_thb     │  │ resulting_balance│  │ return_amount_thb  │
  │ is_care_plus       │  │ resulting_tier   │  └────────────────────┘
  └─────────┬──────────┘  └──────────────────┘
            │ sku_id
            ▼
  ┌───────────────────┐
  │   DIM_PRODUCT     │
  │   sku_id       PK │
  │   vendor_id    FK │──────► DIM_VENDOR
  │   dept_code    FK │──────► DIM_DEPARTMENT
  │   category        │
  │   brand_family    │
  │   care_plus_eligible│
  └───────────────────┘

  ┌───────────────────┐         ┌───────────────────────────────┐
  │   DIM_CUSTOMER    │         │   DIM_VENDOR_CONTRACT_VERSION │
  │   customer_id  PK │         │   contract_version_id      PK │
  │   customer_type   │         │   vendor_id                FK │
  │   loyalty_tier    │         │   effective_date              │
  │   is_b2b          │         │   end_date                    │
  │   account_manager │         │   ⚠ join by contract_version  │
  │     _id        FK │         │   NOT by vendor_id alone      │
  └───────────────────┘         └───────────────────────────────┘
```

---

## 7. Mart Layer — Materialized Views

All `mart.v_*` names are thin **compatibility aliases** pointing to the underlying `mart.mv_*`.
**Always query `mart.mv_*` directly** for best index utilisation.

```
 core.fact_sales ─────────────────────────────────────────────────────────┐
   + dim_customer                                                          │
   + dim_branch                                          ┌─────────────────▼──────────────────┐
   + dim_employee                     ──────────────────►│  mart.mv_sales_order               │
   + dim_promo_campaign               pre-joined         │  1 row per txn_id  (117 105 rows)  │
   + fact_bank_transaction            materialized       │  Indexes: date+branch, customer,   │
                                                         │           payment_status, b2b AR   │
                                                         └────────────────────────────────────┘

 core.fact_sales_line_item ───────────────────────────────────────────────┐
   + fact_sales                                                            │
   + dim_product                                        ┌─────────────────▼──────────────────┐
   + dim_vendor                       ──────────────────►│  mart.mv_sales_line                │
   + dim_department                   pre-joined         │  1 row per line_item_id (309 129)  │
                                      materialized       │  Indexes: sku+date, category+date, │
                                                         │           branch+date              │
                                                         └────────────────────────────────────┘

 core.fact_bank_transaction ──────────────────────────────────────────────┐
   + dim_bank_account                                                      │
   + mv_sales_deposit_batch_recon    ──────────────────►┌─────────────────▼──────────────────┐
   + fact_sales (conditional)        pre-joined         │  mart.mv_bank_reconciliation        │
   + fact_payroll (conditional)      materialized       │  1 row per bank_txn_id (65 334)     │
   + fact_refund_paid (conditional)                     │  Indexes: date+account,             │
   + fact_loyalty_ledger (conditional)                  │           related_entity routing    │
   + fact_vendor_payment (conditional)                  └────────────────────────────────────┘

 core.fact_vendor_payment ────────────────────────────────────────────────┐
   + dim_vendor                                                            │
   + dim_vendor_contract_version     ──────────────────►┌─────────────────▼──────────────────┐
   + dim_employee (signer)           pre-joined         │  mart.mv_vendor_payment             │
   + dim_employee (cosigner)         materialized       │  1 row per payment_id (809 rows)    │
   + fact_bank_transaction                              └────────────────────────────────────┘

 core.fact_sales (GROUP BY batch) ───────────────────────────────────────►┌────────────────────────────────────────────┐
 + fact_bank_transaction                                                   │  mart.mv_sales_deposit_batch_reconciliation│
   WHERE related_entity_table =                                            │  Virtual QA view only                      │
     'FACT_SALES_DEPOSIT_BATCH'                                            │  ⚠ DO NOT cite as official source          │
                                                                           └────────────────────────────────────────────┘
```

---

## 8. Full Data Pipeline

```
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │  STEP 1 — Load structured data                                                   │
 │                                                                                  │
 │   31 CSV files                                                                   │
 │   /tables/*.csv   ──────────────────────────────────────────────────────────►   │
 │                        python scripts/ingest_fahmai_to_postgres.py              │
 │                           SET CONSTRAINTS ALL DEFERRED                          │
 │                           COPY FROM STDIN (bulk, no row-by-row)                 │
 │                           ──► raw.*  (text landing)                             │
 │                           ──► core.* (typed official)                           │
 └──────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │  STEP 2 — Load unstructured documents                                            │
 │                                                                                  │
 │   /docs/**/*.md                                                                  │
 │   /reports/**/*.md   ──────────────────────────────────────────────────────►    │
 │   /logs/**/*.md           ingest_fahmai_to_postgres.py (continued)              │
 │                           chunk_text(chunk_chars=4500, overlap=500)             │
 │                           executemany batch 500 chunks                          │
 │                           skip if content_sha256 unchanged                      │
 │                           ──► rag.source_documents                              │
 │                           ──► rag.document_chunks  (search_tsv auto-generated) │
 │                           ──► rag.entity_links     (public-safe links)          │
 │                           ──► audit.provenance_entity_links (unsafe)            │
 └──────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │  STEP 3 — Generate embeddings                                                    │
 │                                                                                  │
 │   rag.document_chunks                                                            │
 │   WHERE embedding IS NULL  ────────────────────────────────────────────────►    │
 │                                 python scripts/embed_chunks_openai.py           │
 │                                 keyset pagination (chunk_id > last_seen)        │
 │                                 batch 128, retry on 429 (backoff 10s→120s)      │
 │                                 executemany upsert                              │
 │                                 ──► rag.chunk_embeddings  (vector 4096)         │
 └──────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │  STEP 4 — Refresh materialized views                                             │
 │                                                                                  │
 │   SELECT mart.refresh_all_materialized_views(false);   ← first load             │
 │   SELECT mart.refresh_all_materialized_views(true);    ← subsequent (concurrent)│
 │                                                                                  │
 │   Refresh order (dependency-safe):                                              │
 │     1. rag.mv_public_retrievable_chunks                                         │
 │     2. mart.mv_sales_deposit_batch_reconciliation                               │
 │     3. mart.mv_sales_order                                                      │
 │     4. mart.mv_sales_line                                                       │
 │     5. mart.mv_bank_reconciliation   (depends on #2)                            │
 │     6. mart.mv_vendor_payment                                                   │
 │   Then: ANALYZE on all materialized views                                       │
 └──────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │  STEP 5 — Answer questions (TODO: scripts/run_question.py)                       │
 │                                                                                  │
 │   input question text                                                            │
 │        │                                                                         │
 │        ├──► embed query  ──► rag.hybrid_search_public_chunks()  ──► top-K chunks │
 │        │                                                                         │
 │        └──► SQL path     ──► mart.mv_*  or  eval.sql_templates  ──► structured  │
 │                                                                      answer      │
 │        └──► merge results ──► INSERT eval.answer_runs                           │
 └──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. RAG Retrieval Architecture

```
 Query text  ──►  Qwen/Qwen3-Embedding-8B  ──►  query_vector(4096)
                                                              │
                               ┌──────────────────────────── │ ──────────────────────────────────┐
                               │  rag.hybrid_search_public_chunks(query_vector, query_text, k)   │
                               │                                                                   │
                               │   Signal 1 — HNSW Vector Search                                 │
                               │   ┌────────────────────────────────────────────────┐            │
                               │   │  rag.mv_public_retrievable_chunks              │            │
                               │   │  ORDER BY embedding <=> query_vector            │            │
                               │   │  LIMIT candidate_count (default 80)            │            │
                               │   │  → ranked list with cosine_distance            │            │
                               │   └────────────────────────────────────────────────┘            │
                               │                       │                                          │
                               │                       │  rank_v per chunk                        │
                               │                       ▼                                          │
                               │   Signal 2 — BM25 + Trigram Full-text                           │
                               │   ┌────────────────────────────────────────────────┐            │
                               │   │  search_tsv @@ plainto_tsquery('simple', text) │            │
                               │   │  OR chunk_text % query_text  (pg_trgm)          │            │
                               │   │  LIMIT candidate_count (default 80)            │            │
                               │   │  → ranked list with text_score                 │            │
                               │   └────────────────────────────────────────────────┘            │
                               │                       │                                          │
                               │                       │  rank_t per chunk                        │
                               │                       ▼                                          │
                               │   RRF Merge — Reciprocal Rank Fusion                            │
                               │   ┌────────────────────────────────────────────────┐            │
                               │   │  rrf_score = 1/(60 + rank_v)                  │            │
                               │   │            + 1/(60 + rank_t)                  │            │
                               │   │  FULL OUTER JOIN on chunk_id                  │            │
                               │   │  ORDER BY rrf_score DESC                      │            │
                               │   │  LIMIT match_count (default 8)                │            │
                               │   └────────────────────────────────────────────────┘            │
                               └───────────────────────────────────────────────────────────────── ┘
                                                              │
                                                              ▼
                                              Top-K chunks returned:
                                              chunk_text, source_path, source_kind,
                                              rrf_score, cosine_distance, text_score
```

### What `mv_public_retrievable_chunks` contains

```
 rag.document_chunks    ──┐
   is_public_safe = true   ├──► INNER JOIN ──► rag.mv_public_retrievable_chunks
 rag.source_documents   ──┤              │
   is_public_safe = true   │              │    HNSW index on embedding
 rag.chunk_embeddings   ──┘              │    GIN  index on search_tsv
   (INNER JOIN = only embedded chunks)   │    Unique index on chunk_id
                                         └──► rag.v_public_retrievable_chunks  (LEFT JOIN = includes un-embedded)
                                              Use v_ only to inspect un-embedded chunks
                                              Use mv_ for all retrieval
```

### Optional: Entity-linked retrieval (when you have a known entity ID)

```
 known entity  e.g. sku_id = 'SKU-001'
      │
      ▼
 rag.entity_links
   WHERE linked_table = 'DIM_PRODUCT'
     AND entity_id    = 'SKU-001'
     AND is_public_safe = true
      │
      ├──► chunk_id  ──► rag.mv_public_retrievable_chunks  ──► chunk_text
      │
      └──► source_path (for citation)
```

---

## 10. Polymorphic Join Routing

### Bank Transactions — `related_entity_table` discriminator

```
 FACT_BANK_TRANSACTION
 ┌──────────────────────────────────────────────────────────────────┐
 │  related_entity_table     │  related_entity_id points to         │
 ├──────────────────────────────────────────────────────────────────┤
 │  'FACT_SALES_DEPOSIT_BATCH' (28 279 rows)  ──►  VIRTUAL ENTITY   │
 │                                               (not a real table) │
 │                                               QA only via        │
 │                                               mv_sales_deposit   │
 │                                               _batch_recon ⚠     │
 ├──────────────────────────────────────────────────────────────────┤
 │  'FACT_PAYROLL'           (14 400 rows)  ──►  FACT_PAYROLL       │
 │                                               payroll_id         │
 ├──────────────────────────────────────────────────────────────────┤
 │  'FACT_SALES'             (13 313 rows)  ──►  FACT_SALES         │
 │                                               txn_id             │
 ├──────────────────────────────────────────────────────────────────┤
 │  'FACT_REFUND_PAID'        (7 134 rows)  ──►  FACT_REFUND_PAID   │
 │                                               refund_id          │
 ├──────────────────────────────────────────────────────────────────┤
 │  'FACT_LOYALTY_LEDGER'     (1 255 rows)  ──►  FACT_LOYALTY_LEDGER│
 │                                               ledger_id          │
 ├──────────────────────────────────────────────────────────────────┤
 │  'FACT_VENDOR_PAYMENT'       (809 rows)  ──►  FACT_VENDOR_PAYMENT│
 │                                               payment_id         │
 ├──────────────────────────────────────────────────────────────────┤
 │  NULL                        (144 rows)  ──►  no linked entity   │
 └──────────────────────────────────────────────────────────────────┘

 Rule: ALWAYS filter WHERE related_entity_table = 'TARGET' before joining.
       Never cross-join all target tables without the discriminator.
```

### Inventory Movements — `related_txn_id` discriminator

```
 FACT_INVENTORY_MOVEMENT.related_txn_id
 ┌─────────────────────────────────────────────────────────────────┐
 │  Starts with 'TXN-'   (304 817 rows)  ──►  FACT_SALES.txn_id   │
 │                                            Safe to LEFT JOIN    │
 ├─────────────────────────────────────────────────────────────────┤
 │  Starts with 'XFER-'    (4 800 rows)  ──►  Internal transfer ID │
 │                                            ⚠ DO NOT join to     │
 │                                            FACT_SALES — these   │
 │                                            are NOT missing FKs  │
 ├─────────────────────────────────────────────────────────────────┤
 │  IS NULL                (1 210 rows)  ──►  No linked transaction │
 └─────────────────────────────────────────────────────────────────┘
```

---

## 11. Safe Join Rules

### Child tables that MUST be aggregated before joining to a coarser grain

```
 ┌────────────────────────────────┬────────────────────┬────────────────────────────────────────┐
 │ Child table                    │ Parent key         │ Why aggregation is required            │
 ├────────────────────────────────┼────────────────────┼────────────────────────────────────────┤
 │ FACT_SALES_LINE_ITEM           │ txn_id             │ up to 620 lines per order              │
 │ FACT_LOYALTY_LEDGER            │ txn_id             │ 1 255 txns have multiple ledger rows   │
 │ FACT_PROMO_REDEMPTION          │ txn_id             │ 4 txns have duplicate redemption rows  │
 │ FACT_RETURN                    │ original_txn_id    │ 6 txns have multiple return rows       │
 │ DIM_VENDOR_CONTRACT_VERSION    │ vendor_id          │ every vendor has multiple versions     │
 │ DIM_PRODUCT_RECALL_HISTORY     │ sku_id             │ 1 SKU has 3 recall history rows        │
 │ DIM_PROMO_MECHANIC             │ campaign_id        │ 1 campaign has 2 mechanic rows         │
 └────────────────────────────────┴────────────────────┴────────────────────────────────────────┘
```

### Which mart to use for which question type

```
 ┌──────────────────────────────────┬────────────────────────────────────────────────────────┐
 │ Question is about…               │ Use this mart                                          │
 ├──────────────────────────────────┼────────────────────────────────────────────────────────┤
 │ Orders, channels, payment        │ mart.mv_sales_order   (1 row per txn_id)               │
 │ methods, customers, branches     │                                                        │
 ├──────────────────────────────────┼────────────────────────────────────────────────────────┤
 │ SKUs, product mix, line          │ mart.mv_sales_line    (1 row per line_item_id)          │
 │ discounts, Care Plus attach rate │                                                        │
 ├──────────────────────────────────┼────────────────────────────────────────────────────────┤
 │ Bank transactions, settlement,   │ mart.mv_bank_reconciliation   (1 row per bank_txn_id)  │
 │ deposit matching, reconciliation │                                                        │
 ├──────────────────────────────────┼────────────────────────────────────────────────────────┤
 │ Vendor invoices, contract        │ mart.mv_vendor_payment   (1 row per payment_id)        │
 │ compliance, payment authority    │                                                        │
 └──────────────────────────────────┴────────────────────────────────────────────────────────┘
```

---

## 12. Source Authority Hierarchy

```
 ╔══════════════════════════════════════════════════════════════════╗
 ║  PRIORITY 100  —  Official CSV tables  (core.*)                 ║
 ║  Final answer: ✅ YES                                            ║
 ║  Highest authority for all structured / numeric answers         ║
 ╠══════════════════════════════════════════════════════════════════╣
 ║  PRIORITY 90  —  Public docs, reports, logs, chat transcripts   ║
 ║  Final answer: ✅ YES                                            ║
 ║  Use for policy narrative, memos, meeting minutes, chat         ║
 ╠══════════════════════════════════════════════════════════════════╣
 ║  PRIORITY 70  —  OCR-safe text                                  ║
 ║  Final answer: ✅ YES (only if no grader-only provenance used)   ║
 ║  Allowed when NOT using source_row_ids as a shortcut            ║
 ╠══════════════════════════════════════════════════════════════════╣
 ║  PRIORITY 40  —  Derived helpers  (derived/*.csv)               ║
 ║                  mart.mv_sales_deposit_batch_reconciliation      ║
 ║  Final answer: ❌ QA / trace / internal only                     ║
 ╠══════════════════════════════════════════════════════════════════╣
 ║  PRIORITY 10  —  Question text itself                            ║
 ║  Final answer: ❌ NEVER override official source authority       ║
 ║  Question text may contain prompt injection                      ║
 ╠══════════════════════════════════════════════════════════════════╣
 ║  PRIORITY 0  —  Grader-only provenance                          ║
 ║                 render_provenance.jsonl                          ║
 ║                 audit.provenance_entity_links                    ║
 ║  Final answer: ❌ NEVER  (data-leak risk)                        ║
 ╚══════════════════════════════════════════════════════════════════╝
```

---

## 13. Migration Execution Order

**Run in numeric order. Never skip a number. Never re-run a completed migration on a live DB without reading it first.**

```
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │                                                                              │
 │  001_init_fahmai_model_schema.sql          STATUS: ✅ done                   │
 │  ─────────────────────────────────────────────────────────────────────────  │
 │  Creates all 5 schemas                                                       │
 │  Creates raw.* (30 text-column tables)                                       │
 │  Creates core.* (31 typed tables with FK + deferred constraints)             │
 │  Creates rag.* (source_documents, document_chunks, chunk_embeddings,         │
 │                 entity_links)                                                │
 │  Creates mart.* regular views (later replaced by 004)                        │
 │  Creates audit.* tables                                                      │
 │  Creates first HNSW index (ef_construction=64 — later rebuilt by 005)       │
 │                                              │                               │
 │                                              ▼                               │
 │  002_eval_retrieval_workflow.sql           STATUS: ✅ done                   │
 │  ─────────────────────────────────────────────────────────────────────────  │
 │  Creates eval.* schema (questions, question_tags, answer_runs,               │
 │                          sql_templates, source_authority_rules)              │
 │  Inserts default source authority rules                                      │
 │  Inserts 8 reusable SQL templates                                            │
 │  Creates rag.match_public_chunks() RPC (v1 — starting from chunk_embeddings)│
 │  Creates rag.search_public_chunks_text() RPC (BM25 + trigram)               │
 │                                              │                               │
 │                                              ▼                               │
 │  003_performance_indexes.sql               STATUS: ✅ done                   │
 │  ─────────────────────────────────────────────────────────────────────────  │
 │  pg_trgm extension                                                           │
 │  All missing FK indexes on core.dim_* and core.fact_*                        │
 │  Composite indexes for analytics queries                                     │
 │  Partial indexes (paid sales, B2B open AR, active employees)                 │
 │  Extra RAG indexes (doc_id, source_table, sha256, trigram on chunk_text)     │
 │  audit.analyze_fahmai_model_tables() function                                │
 │                                              │                               │
 │                                              ▼                               │
 │  004_materialized_marts.sql                STATUS: ✅ done                   │
 │  ─────────────────────────────────────────────────────────────────────────  │
 │  Drops old regular mart.v_* views                                            │
 │  Creates 5 materialized views (mv_sales_deposit_batch_reconciliation,        │
 │    mv_sales_order, mv_sales_line, mv_bank_reconciliation, mv_vendor_payment) │
 │  Creates unique + composite indexes on each MV                               │
 │  Creates mart.refresh_all_materialized_views(boolean) function               │
 │  Re-creates mart.v_* as thin compatibility aliases over mv_*                 │
 │                                              │                               │
 │                                              ▼                               │
 │  005_rag_hnsw_and_public_chunks_mv.sql     STATUS: ✅ done                   │
 │  ─────────────────────────────────────────────────────────────────────────  │
 │  Drops old HNSW index (ef_construction=64)                                   │
 │  Rebuilds HNSW with ef_construction=128                                      │
 │  Creates rag.mv_public_retrievable_chunks (INNER JOIN — embedded only)       │
 │  Adds HNSW + GIN + unique indexes on mv_public_retrievable_chunks            │
 │  Replaces rag.match_public_chunks() with v2 (uses mv_ directly)             │
 │  Updates mart.refresh_all_materialized_views() to include RAG refresh        │
 │                                              │                               │
 │                                              ▼                               │
 │  006_hybrid_retrieval.sql              STATUS: ⚠️ TODO                       │
 │  ─────────────────────────────────────────────────────────────────────────  │
 │  Creates rag.hybrid_search_public_chunks() — RRF vector + BM25 combined     │
 │  Creates rag.hybrid_search_hq() — convenience wrapper with ef_search setter │
 │  Fixes entity_linked_retrieval template to use mv_ not v_                   │
 │                                              │                               │
 │                                              ▼                               │
 │  007_session_tuning.sql                STATUS: ⚠️ TODO                       │
 │  ─────────────────────────────────────────────────────────────────────────  │
 │  pg_stat_statements extension                                                │
 │  ALTER DATABASE: work_mem=64MB, max_parallel_workers_per_gather=4,          │
 │    max_parallel_workers=8, jit=on, hnsw.ef_search=40                        │
 │                                                                              │
 └──────────────────────────────────────────────────────────────────────────────┘
```

Run command:
```bash
for f in db/001_init_fahmai_model_schema.sql \
         db/002_eval_retrieval_workflow.sql \
         db/003_performance_indexes.sql \
         db/004_materialized_marts.sql \
         db/005_rag_hnsw_and_public_chunks_mv.sql \
         db/006_hybrid_retrieval.sql \
         db/007_session_tuning.sql; do
  psql "$DATABASE_URL" -f "$f" && echo "✓ $f"
done
```

---

## 14. Scripts Reference

### `scripts/ingest_fahmai_to_postgres.py`

```
 Inputs:   /tables/*.csv   /docs/**/*.md   /reports/**/*.md   /logs/**/*.md
           /derived/DOC_ENTITY_LINKS.csv   /derived/ARTIFACT_ENTITY_LINKS.csv
           questions.csv

 What it does:
   1. TRUNCATE raw.* + core.* + rag.* (if --truncate)
   2. COPY 31 CSVs  ──►  raw.*  (all-text landing)
   3. COPY 31 CSVs  ──►  core.* (typed, deferred FK check)
   4. chunk markdown docs  ──►  rag.source_documents + rag.document_chunks
      skip files whose content_sha256 has not changed
      batch insert 500 chunks per executemany call
   5. entity links  ──►  rag.entity_links / audit.provenance_entity_links
   6. questions.csv  ──►  eval.questions + eval.question_tags
   7. ANALYZE all tables
   8. refresh materialized views (if --refresh-materialized)

 Key flags:
   --truncate              wipe and reload from scratch
   --skip-raw              skip raw.* (saves time on re-runs if raw is not needed)
   --skip-rag              skip document chunking
   --refresh-materialized  run mart.refresh_all_materialized_views(false) at end
   --chunk-chars 4500      characters per chunk (default 4500 ≈ 1125 tokens)
   --chunk-overlap-chars 500
```

### `scripts/embed_chunks_openai.py`

```
 Inputs:   rag.document_chunks WHERE embedding IS NULL (keyset paginated by chunk_id)

 What it does:
   1. fetch batch of unembedded chunks (ORDER BY chunk_id, LIMIT batch_size)
   2. call TEI /embed or an OpenAI-compatible embeddings API
      retry on RateLimitError / APITimeoutError (backoff: 10s → 20s → 40s → max 120s)
   3. executemany upsert  ──►  rag.chunk_embeddings
   4. advance keyset cursor (last_chunk_id = rows[-1][0])
   5. repeat until no more missing chunks
   6. refresh materialized views (if --refresh-materialized)

 Key flags:
   --batch-size 128        chunks per embedding request (default 128)
   --max-retries 5         retry attempts on rate-limit
   --refresh-materialized  run mart.refresh_all_materialized_views(false) at end
   --dry-run               count missing chunks without calling the embedding backend
```

### `scripts/run_question.py` ⚠ TODO

```
 What it will do:
   1. load question_text from eval.questions (or accept --question-text directly)
   2. embed query via Qwen embedding backend
   3. call rag.hybrid_search_public_chunks(vector, text, k)
   4. optionally run SQL templates from eval.sql_templates
   5. assemble context + answer
   6. INSERT result into eval.answer_runs

 Key flags (planned):
   --question-id FAHMAI-Q-L1-001
   --question-text "raw text"
   --match-count 8
   --run-label v1
```

---

## 15. Optimization Work Status

### Completed

```
 Round 1 ─ db/optimization_recommendations.md
   ✅  Missing indexes on fact_loyalty_ledger, fact_inventory_movement,
       fact_cs_interaction, fact_return, fact_warranty_claim, dim_customer
   ✅  Identified regular views → materialized views conversion
   ✅  HNSW parameter tuning recommendation

 Round 2 ─ db/optimization_round2.md
   ✅  Design for hybrid_search_public_chunks (RRF)
   ✅  Design for async concurrent embedding + retry
   ✅  Design for parallel dim table loading
   ✅  Design for executemany batch inserts

 Round 3 ─ db/optimization_round3.md  (Codex task list — pending execution)
   ✅  Specific code diffs written for every remaining gap
```

### Pending (assign to Codex via `db/optimization_round3.md`)

```
 ❌  db/006_hybrid_retrieval.sql              rag.hybrid_search_public_chunks() RRF function
 ❌  db/007_session_tuning.sql                pg_stat_statements + work_mem + parallel workers
 ❌  embed_chunks_openai.py                   executemany upsert + keyset pagination + retry
 ❌  ingest_fahmai_to_postgres.py             executemany chunks/questions/links,
                                              skip-unchanged-docs, fix double file read
 ❌  scripts/run_question.py                  end-to-end answer pipeline (new file)
 ❌  sql_templates/fahmai_question_cookbook.sql  query 8: v_ → mv_ reference fix
```

---

## 16. Data-Quality Warnings

These are **intentional real-world artifacts** in the data — not bugs.

```
 ┌──────────────────────────────────────┬───────────────────────────────────────────────────┐
 │ Artifact                             │ How to handle                                     │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────┤
 │ Mid-2025 schema-version cutover      │ Check FACT_SALES.schema_version before joining    │
 │ in FACT_SALES                        │ old and new schema rows together                  │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────┤
 │ Duplicate vendor invoices            │ GROUP BY vendor_invoice_id before SUM             │
 │ in FACT_VENDOR_PAYMENT               │                                                   │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────┤
 │ Phantom / duplicate redemptions      │ Deduplicate by txn_id before joining to           │
 │ in FACT_PROMO_REDEMPTION             │ order-grain mart                                  │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────┤
 │ Retry idempotency markers            │ Filter WHERE retry_idempotency_marker IS NULL      │
 │ in FACT_SALES                        │ for clean transaction counts                      │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────┤
 │ XFER-* inventory movement IDs        │ Never JOIN FACT_INVENTORY_MOVEMENT on XFER-* IDs  │
 │ in FACT_INVENTORY_MOVEMENT           │ to FACT_SALES — they are internal transfers        │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────┤
 │ FACT_SALES_DEPOSIT_BATCH             │ Not a real table. It is only a discriminator value │
 │ is not a real table                  │ in FACT_BANK_TRANSACTION.related_entity_table.    │
 │                                      │ Use mv_sales_deposit_batch_reconciliation for QA  │
 │                                      │ Never cite it as an official source               │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────┤
 │ Multiple contract versions           │ Always join by explicit vendor_contract_version_id │
 │ per vendor                           │ Never join DIM_VENDOR_CONTRACT_VERSION             │
 │                                      │ by vendor_id alone                                │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────┤
 │ Policy versions are time-ranged      │ Resolve by effective_date ≤ event_date            │
 │ in DIM_POLICY_VERSION                │   AND (end_date IS NULL OR end_date ≥ event_date) │
 │                                      │ Never assume latest version applies to old rows   │
 ├──────────────────────────────────────┼───────────────────────────────────────────────────┤
 │ Structured tables vs narrative       │ When sources conflict, structured table wins       │
 │ documents can disagree               │ unless a more recent memo / policy version        │
 │                                      │ explicitly supersedes it                          │
 └──────────────────────────────────────┴───────────────────────────────────────────────────┘
```

---

## 17. Rules of Engagement for AI Agents

```
 ┌─────────────────────────────────────────────────────────────────────────────────┐
 │  1. NEVER query raw.* for a final answer.                                       │
 │     raw.* is a text landing zone only.  Use core.* or mart.mv_*.               │
 ├─────────────────────────────────────────────────────────────────────────────────┤
 │  2. NEVER cite mart.mv_sales_deposit_batch_reconciliation as an official source.│
 │     It is a virtual QA view.  Cite FACT_BANK_TRANSACTION + FACT_SALES instead. │
 ├─────────────────────────────────────────────────────────────────────────────────┤
 │  3. ALWAYS check related_entity_table before joining FACT_BANK_TRANSACTION      │
 │     to any target table.  Never cross-join all possible targets at once.        │
 ├─────────────────────────────────────────────────────────────────────────────────┤
 │  4. ALWAYS aggregate child tables before joining to a coarser grain.            │
 │     See §11 table.  Especially FACT_SALES_LINE_ITEM → FACT_SALES.              │
 ├─────────────────────────────────────────────────────────────────────────────────┤
 │  5. When FACT_SALES_LINE_ITEM is joined to FACT_SALES,                          │
 │     use COUNT(DISTINCT txn_id), NOT COUNT(*).                                   │
 ├─────────────────────────────────────────────────────────────────────────────────┤
 │  6. For time-ranged policy lookups, ALWAYS resolve DIM_POLICY_VERSION by:       │
 │       effective_date ≤ event_date                                               │
 │       AND (end_date IS NULL OR end_date ≥ event_date)                           │
 │     Never assume the latest version applies to historical rows.                 │
 ├─────────────────────────────────────────────────────────────────────────────────┤
 │  7. Use mart.mv_* for analytics, rag.hybrid_search_public_chunks() for          │
 │     document retrieval.  Never mix grains between the two paths.               │
 ├─────────────────────────────────────────────────────────────────────────────────┤
 │  8. Prefer business_event_date over posting_date unless the question            │
 │     explicitly asks for posting date.                                           │
 ├─────────────────────────────────────────────────────────────────────────────────┤
 │  9. FACT_SALES.net_total_thb is the authoritative order total.                  │
 │     Do not recompute from line items without deduplicating Care Plus rows.      │
 ├─────────────────────────────────────────────────────────────────────────────────┤
 │ 10. All IDs (customer_id, txn_id, sku_id, etc.) are TEXT type.                  │
 │     Never cast to integer.                                                      │
 ├─────────────────────────────────────────────────────────────────────────────────┤
 │ 11. Do NOT join FACT_INVENTORY_MOVEMENT on XFER-* related_txn_id values         │
 │     to FACT_SALES.  XFER-* means internal warehouse transfer, not a sale.      │
 ├─────────────────────────────────────────────────────────────────────────────────┤
 │ 12. Before running any new SQL migration, verify the migration number is next   │
 │     in sequence.  Check db/ directory listing.                                  │
 └─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 18. Quick-Start Commands

```bash
# Apply all DB migrations
for f in db/001_init_fahmai_model_schema.sql \
         db/002_eval_retrieval_workflow.sql \
         db/003_performance_indexes.sql \
         db/004_materialized_marts.sql \
         db/005_rag_hnsw_and_public_chunks_mv.sql \
         db/006_hybrid_retrieval.sql \
         db/007_session_tuning.sql; do
  psql "$DATABASE_URL" -f "$f" && echo "✓ $f"
done

# Load all data (first time)
python scripts/ingest_fahmai_to_postgres.py \
  --truncate \
  --refresh-materialized

# Generate embeddings
python scripts/embed_chunks_openai.py \
  --provider tei \
  --batch-size 128 \
  --max-retries 5 \
  --refresh-materialized

# Incremental reload (no truncate, skip unchanged docs)
python scripts/ingest_fahmai_to_postgres.py \
  --skip-raw \
  --refresh-materialized

# Refresh materialized views after any data change
psql "$DATABASE_URL" -c "SELECT mart.refresh_all_materialized_views(true);"

# Run a retrieval-only eval question and persist evidence
python scripts/run_question.py \
  --question-id "FAHMAI-Q-L1-001" \
  --match-count 8 \
  --run-label "v1"

# Production rebuild checklist
# See PRODUCTION_REBUILD_CHECKLIST.md

# Check slow queries (after 007 is applied)
psql "$DATABASE_URL" -c "
  SELECT query, calls,
         round(total_exec_time::numeric / calls, 2) AS avg_ms,
         rows
  FROM pg_stat_statements
  ORDER BY avg_ms DESC
  LIMIT 20;"
```
