# FahMai Safe Join Blueprint

เอกสารนี้สรุปว่า table ไหนควร join เข้าด้วยกันเป็น analysis mart ได้บ้าง โดยไม่ทำให้ grain เปลี่ยนหรือ aggregate เพี้ยนจาก row explosion

Source หลัก:
- `fahmai_erd.mmd`
- `fahmai_table_schema.md`
- `super-ai-engineer-season-6-fah-mai-the-finale/tables/*.csv`
- `derived/sales_deposit_batch_reconciliation.csv`

## Golden Rules

- Canonical fact date axis: for year/month/quarter filters where the question does not name a date column, use `business_event_date`. Use `posting_date` only for explicit posting/accounting/booked timing; `FACT_VENDOR_PAYMENT` can lag because of NET-30.

- เลือก fact หลัก 1 ตัวเป็น base grain ของแต่ละ mart แล้วค่อย join dimension/lookup แบบ many-to-one
- หลีกเลี่ยงการ flatten fact-to-fact หลายตัวเข้าด้วยกันถ้ายังไม่ได้ aggregate ฝั่งลูกให้เหลือ 1 row ต่อ key
- ถ้า join fact อื่นเข้ามาเพื่อเอา context เช่น bank transaction ของ sales ให้ใช้เป็น metadata/reconciliation เท่านั้น อย่า sum amount จาก fact ที่ถูก repeat หลัง join
- ID-like columns ควรอ่านเป็น string เสมอ โดยเฉพาะ `line_item_id`, `related_entity_id`, `related_txn_id`, และ bank/sales IDs
- Date table ไม่ต้อง join ถาวรทุก mart ให้ join เฉพาะตอนต้องการ fiscal/holiday/date attributes

## Recommended Analysis Marts

| Mart | Base grain | Expected rows | Safe direct joins | Notes |
|---|---:|---:|---|---|
| `mart_sales_order` | 1 row ต่อ `FACT_SALES.txn_id` | 117,105 | `DIM_CUSTOMER`, `DIM_BRANCH`, `DIM_EMPLOYEE`, `DIM_PROMO_CAMPAIGN`, `FACT_BANK_TRANSACTION` via `settlement_bank_txn_id` | ใช้ `FACT_BANK_TRANSACTION` เป็น settlement metadata เท่านั้น ระวัง bank amount ถูก repeat ใน order-level analysis |
| `mart_sales_line` | 1 row ต่อ `FACT_SALES_LINE_ITEM.line_item_id` | 309,129 | `FACT_SALES`, `DIM_PRODUCT`, `DIM_VENDOR`, `DIM_DEPARTMENT`, sales customer/branch/employee/promo | เหมาะกับ product mix, SKU margin proxy, care-plus attach, line discount |
| `mart_return_refund` | 1 row ต่อ `FACT_RETURN.return_id` | 7,144 | `FACT_REFUND_PAID`, original `FACT_SALES`, `FACT_SALES_LINE_ITEM`, `DIM_PRODUCT`, `DIM_CUSTOMER`, `DIM_BRANCH`, approving employee, refund bank txn | `FACT_REFUND_PAID.return_id` is at most 1 row per return in current data, so it is safe as direct enrichment |
| `mart_inventory_movement` | 1 row ต่อ `FACT_INVENTORY_MOVEMENT.movement_id` | 310,827 | `DIM_PRODUCT`, `DIM_BRANCH`; optional `FACT_SALES` only for `related_txn_id` values beginning with `TXN-` | `XFER-*` values are internal transfer IDs and must not be treated as missing sales FKs |
| `mart_inventory_snapshot` | 1 row ต่อ `FACT_INVENTORY_MONTHLY_SNAPSHOT.snapshot_id` | 26,220 | `DIM_PRODUCT`, `DIM_BRANCH` | Keep separate from movement flow tables; snapshot is stock level, movement is transaction flow |
| `mart_bank_reconciliation` | 1 row ต่อ `FACT_BANK_TRANSACTION.bank_txn_id` | 65,334 | `DIM_BANK_ACCOUNT`, branch through bank account, conditional links to deposit batch/payroll/refund/vendor payment/sales | Use `related_entity_table` to route each row; do not join all possible target facts at once without conditional keys |
| `mart_vendor_payment` | 1 row ต่อ `FACT_VENDOR_PAYMENT.payment_id` | 809 | `DIM_VENDOR`, explicit `DIM_VENDOR_CONTRACT_VERSION`, signing employee, cosig employee, `FACT_BANK_TRANSACTION` | Use `vendor_contract_version_id`; do not resolve contract by `vendor_id` alone |
| `mart_customer_service` | 1 row ต่อ `FACT_CS_INTERACTION.cs_interaction_id` | 14,368 | `DIM_CUSTOMER`, `DIM_EMPLOYEE`, `DIM_BRANCH`, optional related refund/warranty IDs | Keep as CS interaction grain; do not union with warranty unless building a separate case timeline |
| `mart_warranty_claim` | 1 row ต่อ `FACT_WARRANTY_CLAIM.claim_id` | 3,973 | `DIM_CUSTOMER`, `DIM_PRODUCT`, original `FACT_SALES` | Separate sibling of customer-service mart because the primary key and grain differ |
| `mart_payroll` | 1 row ต่อ `FACT_PAYROLL.payroll_id` | 14,400 | `DIM_EMPLOYEE`, employee branch/department/position level, `FACT_BANK_TRANSACTION` | Safe for employee compensation and payroll reconciliation |

## Safe Dimension Packs

These packs are safe to materialize or treat as reusable CTEs because they keep one row per base dimension key.

| Dimension pack | Grain | Safe joins | Avoid |
|---|---|---|---|
| `dim_product_enriched` | 1 row ต่อ `DIM_PRODUCT.sku_id` | `DIM_PRODUCT` + `DIM_VENDOR` + `DIM_DEPARTMENT` | Do not join `dim_product_recall_history` unless aggregating recall history first |
| `dim_employee_enriched` | 1 row ต่อ `DIM_EMPLOYEE.employee_id` | `DIM_EMPLOYEE` + `DIM_BRANCH` + `DIM_DEPARTMENT` + `DIM_POSITION_LEVEL` | Self-join manager only with prefixed manager columns |
| `dim_bank_account_enriched` | 1 row ต่อ `DIM_BANK_ACCOUNT.account_id` | `DIM_BANK_ACCOUNT` + associated `DIM_BRANCH` | None observed |
| `dim_campaign` | 1 row ต่อ `DIM_PROMO_CAMPAIGN.campaign_id` | `DIM_PROMO_CAMPAIGN` only | `dim_promo_mechanic` has 8 rows for 7 campaigns, so aggregate or keep mechanic grain |

## Aggregate Before Joining

Use these only after summarizing to the target mart grain.

| Child table | Parent key | Observed multiplicity | Safe pattern |
|---|---|---:|---|
| `FACT_SALES_LINE_ITEM` | `txn_id` | max 620 lines per order | Aggregate to `txn_id` before joining into `mart_sales_order`, or use `mart_sales_line` |
| `FACT_PROMO_REDEMPTION` | `txn_id` | 4 txns have duplicate redemption rows | Dedupe or aggregate to `txn_id` before joining sales order |
| `FACT_LOYALTY_LEDGER` | `txn_id` | 1,255 txns have multiple ledger rows | Aggregate points/events to `txn_id` before joining sales order |
| `FACT_RETURN` | `original_txn_id` | 6 sales txns have multiple returns | Aggregate return metrics to `txn_id` before joining sales order |
| `dim_promo_mechanic` | `campaign_id` | 1 campaign has 2 mechanics | Aggregate mechanic descriptions/values or keep campaign-mechanic grain |
| `DIM_VENDOR_CONTRACT_VERSION` | `vendor_id` | every vendor has multiple contract versions | Join by explicit `vendor_contract_version_id`, not by `vendor_id` |
| `dim_product_recall_history` | `sku_id` | 1 SKU has 3 history rows | Aggregate latest/current recall status before joining product |

## Polymorphic Join Rules

### Bank Transactions

`FACT_BANK_TRANSACTION.related_entity_table` decides how `related_entity_id` should be interpreted.

Observed routing:

| `related_entity_table` | Rows | Target |
|---|---:|---|
| `FACT_SALES_DEPOSIT_BATCH` | 28,279 | literal virtual entity in bank transactions; optional helper `derived/sales_deposit_batch_reconciliation.sales_deposit_batch_id` |
| `FACT_PAYROLL` | 14,400 | `FACT_PAYROLL.payroll_id` |
| `FACT_SALES` | 13,313 | `FACT_SALES.txn_id` |
| `FACT_REFUND_PAID` | 7,134 | `FACT_REFUND_PAID.refund_id` |
| `FACT_LOYALTY_LEDGER` | 1,255 | `FACT_LOYALTY_LEDGER.ledger_id` |
| `FACT_VENDOR_PAYMENT` | 809 | `FACT_VENDOR_PAYMENT.payment_id` |
| null | 144 | no target entity |

Implementation rule: use conditional joins, one target at a time, filtered by `related_entity_table`. `FACT_SALES_DEPOSIT_BATCH` is a source discriminator value, not an official CSV table; use the derived reconciliation helper only for internal QA/trace.

### Inventory Movements

`FACT_INVENTORY_MOVEMENT.related_txn_id` is polymorphic:

- 304,817 rows have `TXN-*` style IDs and can be interpreted as sales-related movements
- 4,800 rows have `XFER-*` transfer IDs and should remain transfer movements
- 1,210 rows are null

Implementation rule: join to `FACT_SALES` only when `related_txn_id` is a sales transaction ID and never classify `XFER-*` as missing sales.

### Document Inventory

`T2_DOC_INVENTORY.source_table` and `source_pk` point to multiple source systems. Treat this as document lineage metadata, not as a normal FK to flatten into every fah_sai_lpk_mart.

## Do Not Flatten Directly

- Do not join `FACT_SALES` to `FACT_SALES_LINE_ITEM` and then report order counts without `COUNT(DISTINCT txn_id)`.
- Do not join `FACT_LOYALTY_LEDGER` or `FACT_PROMO_REDEMPTION` into `mart_sales_order` without dedupe/aggregation.
- Do not join `DIM_VENDOR` to every contract version and then attach that to vendor facts by `vendor_id`.
- Do not join `dim_product_recall_history` into `dim_product_enriched` unless the target grain intentionally becomes SKU-recall-history.
- Do not join inventory movement and monthly snapshot into one mart; movement is a flow, snapshot is a stock balance.
- Do not sum bank/refund/vendor/payment amounts from a repeated fact after joining to a lower grain table.

## Validation Checklist

Run these checks whenever materializing a mart:

- Row count equals the base fact row count, unless the mart is intentionally line-level.
- Primary key for the mart grain has no duplicates.
- Base fact totals match before and after enrichment:
  - `FACT_SALES.net_total_thb` for `mart_sales_order`
  - `FACT_SALES_LINE_ITEM.line_total_thb` for `mart_sales_line`
  - `FACT_RETURN.return_amount_thb` for `mart_return_refund`
  - `FACT_VENDOR_PAYMENT.paid_amount_thb` for `mart_vendor_payment`
  - `FACT_PAYROLL.net_pay_thb` for `mart_payroll`
- Any fact-to-fact child table is aggregated to one row per parent key before joining.
- Conditional joins use the right discriminator column, especially `related_entity_table`.

## DuckDB-Style Templates

These are templates, not generated tables.

```sql
-- Order-level sales mart: keep one row per FACT_SALES.txn_id.
select
  s.*,
  c.customer_type,
  c.loyalty_tier,
  b.name_en as branch_name_en,
  e.position_title as sales_employee_position,
  pc.description_en as promo_description_en,
  bt.transaction_type as settlement_bank_transaction_type
from FACT_SALES s
left join DIM_CUSTOMER c on s.customer_id = c.customer_id
left join DIM_BRANCH b on s.branch_code = b.branch_code
left join DIM_EMPLOYEE e on s.employee_id = e.employee_id
left join DIM_PROMO_CAMPAIGN pc on s.promo_campaign_id = pc.campaign_id
left join FACT_BANK_TRANSACTION bt on s.settlement_bank_txn_id = bt.bank_txn_id;
```

```sql
-- Sales line mart: line-level grain; order-level amounts from FACT_SALES repeat by line.
select
  li.*,
  s.branch_code,
  s.customer_id,
  s.employee_id,
  s.channel,
  p.brand_family,
  p.category,
  p.subcategory,
  v.name_en as vendor_name_en
from FACT_SALES_LINE_ITEM li
left join FACT_SALES s on li.txn_id = s.txn_id
left join DIM_PRODUCT p on li.sku_id = p.sku_id
left join DIM_VENDOR v on p.vendor_id = v.vendor_id;
```

```sql
-- Safe aggregate-before-join pattern for order-level line metrics.
with line_rollup as (
  select
    txn_id,
    count(*) as line_count,
    sum(quantity) as total_units,
    sum(line_total_thb) as line_total_thb
  from FACT_SALES_LINE_ITEM
  group by txn_id
)
select
  s.*,
  lr.line_count,
  lr.total_units,
  lr.line_total_thb
from FACT_SALES s
left join line_rollup lr on s.txn_id = lr.txn_id;
```

```sql
-- Bank reconciliation conditional deposit-batch helper link.
select
  bt.*,
  ba.bank,
  ba.account_role,
  db.sales_deposit_batch_id,
  db.txn_count as deposit_batch_txn_count,
  db.reconciliation_status
from FACT_BANK_TRANSACTION bt
left join DIM_BANK_ACCOUNT ba on bt.account_id = ba.account_id
left join sales_deposit_batch_reconciliation db
  on bt.related_entity_table = 'FACT_SALES_DEPOSIT_BATCH'
 and bt.related_entity_id = db.sales_deposit_batch_id;
```
