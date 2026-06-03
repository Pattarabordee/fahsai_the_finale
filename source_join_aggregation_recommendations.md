# Source Comparison: Join And Aggregation Recommendations

This note summarizes the source comparison between:

- `C:\Users\ZBook\Downloads\answers_with_sources.csv`
- `C:\Users\ZBook\Downloads\ground_truth.csv`

Detailed per-question output:

- `source_comparison_by_question.csv`
- `source_comparison_report.md`

## High-Level Result

After normalizing file paths, table names, and ground-truth shorthand views:

| Status | Count | Meaning |
|---|---:|---|
| exact same sources | 48 | Both answers used the same logical source set. |
| answer superset of ground truth | 42 | The answer cited extra dimensions/docs/supporting sources. |
| answer subset of ground truth | 6 | The answer missed a dimension/context source used by ground truth. |
| partial overlap | 2 | Both shared a core source but diverged on supporting joins. |
| no overlap / unparsed | 2 | Source descriptions incompatible or missing parseable citation. |

The biggest lesson: most disagreement is not about the core fact table. It is about whether to include dimension tables or narrative evidence.

## Common Difference Patterns

### 1. Fact Table Plus Dimension Labels

Examples:

```text
FACT_SALES -> needs DIM_BRANCH or DIM_CUSTOMER for branch/customer labels
FACT_SALES_LINE_ITEM -> needs DIM_PRODUCT for brand/category/MSRP
FACT_RETURN -> needs DIM_BRANCH, DIM_PRODUCT, DIM_EMPLOYEE depending on question wording
FACT_SHIPPING -> needs DIM_VENDOR for vendor name
```

Recommendation: create semantic views that include common labels, but preserve the raw fact table columns.

Useful views:

```text
v_sales_enriched
v_sales_line_item_enriched
v_return_enriched
v_shipping_enriched
v_inventory_snapshot_enriched
```

### 2. Tables Plus Narrative Evidence

Many hard questions mention LINE Works, LINE OA, memos, email, or reports. Ground truth often lists only the table because the final numeric answer comes from tables, while the answer model cited narrative evidence too.

Most frequent extra narrative source:

```text
docs/chat_line_works
```

Recommendation: do not merge narrative text into fact tables. Instead create an event evidence index:

```text
event_code
event_date
source_family
source_path
claim_marker
entity_ids
linked_table_hint
```

Then questions can retrieve narrative context and run SQL separately.

### 3. Authority / Policy Questions

Common source cluster:

```text
FACT_REFUND_PAID
DIM_EMPLOYEE
DIM_POLICY_VERSION
dim_signing_authority_ladder
docs/memo
docs/chat_line_works
```

Recommendation: build a policy-resolved authority view:

```text
v_refund_authority_check
```

Suggested columns:

```text
refund_id
return_id
business_event_date
refund_amount_thb
approver_employee_id
approver_dept_code
approver_position_level
cosig_employee_id
active_policy_version_id
authority_threshold_thb
requires_cosig
is_over_threshold
is_policy_violation_candidate
```

### 4. Sales Header Versus Line Item

Some questions can be answered from `FACT_SALES`, but others need `FACT_SALES_LINE_ITEM`.

Use `FACT_SALES` for:

```text
basket_total_thb
discount_total_thb
net_total_thb
channel
payment_status
customer_id
branch_code
promo_campaign_id
```

Use `FACT_SALES_LINE_ITEM` for:

```text
sku_id
quantity
unit_price_thb
line_total_thb
line_discount_thb
product-level aggregation
```

Recommendation: create:

```text
v_sales_line_item_enriched = FACT_SALES_LINE_ITEM
  join FACT_SALES
  join DIM_PRODUCT
  join DIM_BRANCH
  left join DIM_CUSTOMER
```

This view should be used for SKU/month/branch/customer product analytics.

### 5. Bank Reconciliation

Hard/XHard questions often need:

```text
FACT_BANK_TRANSACTION
FACT_SALES
FACT_VENDOR_PAYMENT
FACT_REFUND_PAID
FACT_PROMO_REDEMPTION
```

Recommendation: keep bank as an evidence spine. Do not flatten all bank relationships into one giant view because `related_entity_table` points to different domains.

Create domain-specific bridge views:

```text
v_sales_deposit_reconciliation
v_refund_bank_reconciliation
v_vendor_payment_bank_reconciliation
v_promo_redemption_reconciliation
```

For sales deposits, prefer:

```text
FACT_SALES_DEPOSIT_BATCH_CORRECTED.csv
```

not the original generated file.

### 6. Inventory And Report Reconciliation

Report questions may cite OPS report summaries, but exact values should be checked against:

```text
FACT_INVENTORY_MONTHLY_SNAPSHOT
FACT_INVENTORY_MOVEMENT
DIM_PRODUCT
DIM_BRANCH
```

Recommendation:

```text
v_inventory_snapshot_enriched
v_inventory_movement_enriched
v_report_inventory_health_claims
```

The last view should store parsed report claims so they can be compared with table truth.

## Suggested Prebuilt Views

### v_sales_enriched

Base:

```text
FACT_SALES
```

Joins:

```text
DIM_BRANCH
DIM_CUSTOMER
DIM_EMPLOYEE
DIM_PROMO_CAMPAIGN
FACT_BANK_TRANSACTION via settlement_bank_txn_id
```

Use for basket, channel, branch, customer, payment, and promo questions.

### v_sales_line_item_enriched

Base:

```text
FACT_SALES_LINE_ITEM
```

Joins:

```text
FACT_SALES
DIM_PRODUCT
DIM_BRANCH through FACT_SALES
DIM_CUSTOMER through FACT_SALES
```

Use for SKU revenue, units, discount, price, and product mix questions.

### v_return_refund_enriched

Base:

```text
FACT_RETURN
```

Joins:

```text
FACT_REFUND_PAID
FACT_BANK_TRANSACTION
DIM_PRODUCT
DIM_CUSTOMER
DIM_BRANCH
DIM_EMPLOYEE approver
```

Use for return amount, refund payout, approver, branch, customer, and recall questions.

### v_warranty_claim_enriched

Base:

```text
FACT_WARRANTY_CLAIM
```

Joins:

```text
DIM_PRODUCT
DIM_CUSTOMER
FACT_SALES original_txn_id
dim_product_recall_history by sku/date where needed
```

Use for warranty cluster, pre-recall signal, and routing questions.

### v_vendor_payment_enriched

Base:

```text
FACT_VENDOR_PAYMENT
```

Joins:

```text
DIM_VENDOR
DIM_VENDOR_CONTRACT_VERSION
DIM_EMPLOYEE signing/cosig
FACT_BANK_TRANSACTION
```

Use for duplicate invoice, vendor contract, authority, and payment reconciliation questions.

### v_promo_enriched

Base:

```text
FACT_PROMO_REDEMPTION
```

Joins:

```text
DIM_PROMO_CAMPAIGN
dim_promo_mechanic
FACT_SALES
DIM_CUSTOMER
```

Use for campaign ROI, phantom redemption dedup, discount cost, and cohort analysis.

### v_inventory_snapshot_enriched

Base:

```text
FACT_INVENTORY_MONTHLY_SNAPSHOT
```

Joins:

```text
DIM_PRODUCT
DIM_BRANCH
```

Use for month-end stock, zero/negative inventory, SKU/branch inventory health.

### v_event_evidence

Base:

```text
docs/chat_line_works
docs/chat_line_oa
docs/memo
docs/minutes
docs/email
reports
```

Columns:

```text
source_path
source_family
event_code
event_date
claim_marker
entity_ids
business_domain
linked_table_hint
text_chunk_id
```

Use this to avoid embedding table rows while still connecting narrative evidence to SQL queries.

## M-Schema Treatment

The primary M-Schema artifact should contain only executable objects that exist
in the current PostgreSQL migrations:

- `fah_sai_lpk_core.*` official typed tables
- model-facing `fah_sai_lpk_mart.v_*` views
- public-safe retrieval/eval helpers such as `fah_sai_lpk_rag.v_public_retrievable_chunks`,
  `fah_sai_lpk_rag.entity_links`, and selected `fah_sai_lpk_eval.*` tables

The suggested views in this document are future modeling recommendations. Keep
them documented here until they are implemented in SQL; do not mix them into the
primary M-Schema prompt as virtual tables.

## What This Means For RAG

Do not chunk all table rows as text.

Instead:

1. Put CSV tables into SQL.
2. Build enriched views for common fact-dimension joins.
3. Chunk and embed docs/reports/chat/OCR text.
4. Store event metadata so retrieved text can produce SQL filters.
5. For exact answers, run SQL against tables/views.

The source comparison shows that most questions agree on the core table. The hard part is adding the right dimension labels and narrative evidence at the right time.
