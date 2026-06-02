-- FahMai SQL template cookbook.
-- These are reusable patterns. Replace :parameters with values from a question.
-- Do not hardcode public-answer constants unless the question explicitly gives them.

-- 1) Top-selling SKU by units in a date window.
SELECT
    li.sku_id,
    p.brand_family,
    p.category,
    SUM(li.quantity) AS units_sold
FROM core.fact_sales_line_item li
JOIN core.fact_sales s ON s.txn_id = li.txn_id
LEFT JOIN core.dim_product p ON p.sku_id = li.sku_id
WHERE s.business_event_date >= :start_date::date
  AND s.business_event_date < :end_date_exclusive::date
GROUP BY li.sku_id, p.brand_family, p.category
ORDER BY units_sold DESC, li.sku_id
LIMIT :limit_rows;

-- 2) Resolve an active policy at a date.
SELECT *
FROM core.dim_policy_version
WHERE policy_class = :policy_class
  AND policy_variable = :policy_variable
  AND effective_date <= :business_date::date
  AND (end_date IS NULL OR end_date >= :business_date::date)
ORDER BY effective_date DESC
LIMIT 1;

-- 3) Largest deposit in an optional window.
SELECT
    bank_txn_id,
    business_event_date,
    account_id,
    related_entity_table,
    related_entity_id,
    amount_thb
FROM core.fact_bank_transaction
WHERE amount_thb > 0
  AND (:start_date::date IS NULL OR business_event_date >= :start_date::date)
  AND (:end_date_exclusive::date IS NULL OR business_event_date < :end_date_exclusive::date)
ORDER BY amount_thb DESC, bank_txn_id
LIMIT 1;

-- 4) Refund authority check with per-row policy resolution.
WITH active_policy AS (
    SELECT
        r.refund_id,
        r.business_event_date,
        r.refund_amount_thb,
        r.approver_employee_id,
        r.cosig_employee_id,
        e.dept_code,
        e.position_level,
        pv.policy_version_id
    FROM core.fact_refund_paid r
    JOIN core.dim_employee e ON e.employee_id = r.approver_employee_id
    JOIN core.dim_policy_version pv
      ON pv.policy_class = 'signing_authority'
     AND pv.effective_date <= r.business_event_date
     AND (pv.end_date IS NULL OR pv.end_date >= r.business_event_date)
    WHERE (:employee_id::text IS NULL OR r.approver_employee_id = :employee_id)
      AND (:start_date::date IS NULL OR r.business_event_date >= :start_date::date)
      AND (:end_date_exclusive::date IS NULL OR r.business_event_date < :end_date_exclusive::date)
)
SELECT
    ap.*,
    l.amount_ceiling_thb,
    (ap.refund_amount_thb > l.amount_ceiling_thb AND ap.cosig_employee_id IS NULL) AS over_threshold_without_cosigner
FROM active_policy ap
JOIN core.dim_signing_authority_ladder l
  ON l.policy_version_id = ap.policy_version_id
 AND l.position_level_code = ap.position_level
 AND (l.dept_code IS NULL OR l.dept_code = ap.dept_code);

-- 5) Vendor contract resolution by business_event_date.
SELECT
    vp.payment_id,
    vp.vendor_id,
    vp.vendor_invoice_id,
    vp.business_event_date,
    vp.posting_date,
    vp.vendor_contract_version_id AS explicit_contract_version_id,
    cv.contract_version_id AS business_date_contract_version_id,
    vp.paid_amount_thb
FROM core.fact_vendor_payment vp
LEFT JOIN core.dim_vendor_contract_version cv
  ON cv.vendor_id = vp.vendor_id
 AND cv.effective_date <= vp.business_event_date
 AND (cv.end_date IS NULL OR cv.end_date >= vp.business_event_date)
WHERE (:vendor_id::text IS NULL OR vp.vendor_id = :vendor_id)
  AND (:start_date::date IS NULL OR vp.business_event_date >= :start_date::date)
  AND (:end_date_exclusive::date IS NULL OR vp.business_event_date < :end_date_exclusive::date);

-- 6) B2B open AR in a fiscal/date window.
SELECT
    s.customer_id,
    c.first_name_en || ' ' || c.last_name_en AS customer_name_en,
    c.account_manager_id,
    s.txn_id,
    s.business_event_date,
    s.net_total_thb,
    SUM(s.net_total_thb) OVER (PARTITION BY s.customer_id) AS customer_open_ar_thb
FROM core.fact_sales s
JOIN core.dim_customer c ON c.customer_id = s.customer_id
WHERE s.is_b2b = true
  AND s.payment_received_date IS NULL
  AND s.business_event_date >= :start_date::date
  AND s.business_event_date < :end_date_exclusive::date
ORDER BY s.net_total_thb DESC, s.txn_id
LIMIT :limit_rows;

-- 7) Return rate for SKU + branch + period.
WITH sales_units AS (
    SELECT SUM(li.quantity)::numeric AS units_sold
    FROM core.fact_sales_line_item li
    JOIN core.fact_sales s ON s.txn_id = li.txn_id
    WHERE li.sku_id = :sku_id
      AND s.branch_code = :branch_code
      AND s.business_event_date >= :start_date::date
      AND s.business_event_date < :end_date_exclusive::date
),
returns AS (
    SELECT COUNT(*)::numeric AS return_rows
    FROM core.fact_return r
    WHERE r.sku_id = :sku_id
      AND r.branch_code = :branch_code
      AND r.business_event_date >= :start_date::date
      AND r.business_event_date < :end_date_exclusive::date
      AND (:return_reason_contains::text IS NULL OR r.return_reason ILIKE '%' || :return_reason_contains || '%')
)
SELECT
    return_rows,
    units_sold,
    ROUND(100 * return_rows / NULLIF(units_sold, 0), 2) AS return_rate_pct
FROM returns CROSS JOIN sales_units;

-- 8) Public-safe entity-linked document retrieval.
SELECT
    c.chunk_id,
    c.source_path,
    c.source_kind,
    c.chunk_text,
    el.linked_table,
    el.linked_column,
    el.entity_id
FROM rag.v_public_retrievable_chunks c
JOIN rag.entity_links el ON el.chunk_id = c.chunk_id
WHERE el.is_public_safe = true
  AND el.linked_table = :linked_table
  AND el.entity_id = :entity_id
ORDER BY c.source_path, c.chunk_index
LIMIT :limit_rows;

-- 9) Public-safe vector retrieval RPC usage.
SELECT *
FROM rag.match_public_chunks(:query_embedding::vector(4096), :match_count);

-- 10) Public-safe keyword/trigram retrieval RPC usage.
SELECT *
FROM rag.search_public_chunks_text(:query_text, :match_count);
