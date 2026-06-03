-- FahMai materialized mart views.
-- Run after db/003_performance_indexes.sql. The views are created WITH NO DATA
-- so first refresh should use fah_sai_lpk_mart.refresh_all_materialized_views(false).

-- Drop compatibility views first because some of them depend on each other.
DROP VIEW IF EXISTS fah_sai_lpk_mart.v_bank_reconciliation;
DROP VIEW IF EXISTS fah_sai_lpk_mart.v_vendor_payment;
DROP VIEW IF EXISTS fah_sai_lpk_mart.v_sales_line;
DROP VIEW IF EXISTS fah_sai_lpk_mart.v_sales_order;
DROP VIEW IF EXISTS fah_sai_lpk_mart.v_sales_deposit_batch_reconciliation;

DROP MATERIALIZED VIEW IF EXISTS fah_sai_lpk_mart.mv_bank_reconciliation;
DROP MATERIALIZED VIEW IF EXISTS fah_sai_lpk_mart.mv_vendor_payment;
DROP MATERIALIZED VIEW IF EXISTS fah_sai_lpk_mart.mv_sales_line;
DROP MATERIALIZED VIEW IF EXISTS fah_sai_lpk_mart.mv_sales_order;
DROP MATERIALIZED VIEW IF EXISTS fah_sai_lpk_mart.mv_sales_deposit_batch_reconciliation;

CREATE MATERIALIZED VIEW fah_sai_lpk_mart.mv_sales_deposit_batch_reconciliation AS
WITH sales_batches AS (
    SELECT
        concat_ws('|', branch_code, business_event_date::text, payment_method) AS sales_deposit_batch_id,
        business_event_date,
        branch_code,
        payment_method,
        count(*)::integer AS txn_count,
        sum(net_total_thb)::numeric(18,2) AS net_total_thb
    FROM fah_sai_lpk_core.fact_sales
    WHERE payment_method IN ('cash', 'credit_card', 'debit_card', 'mobile_wallet')
    GROUP BY branch_code, business_event_date, payment_method
),
bank_batches AS (
    SELECT DISTINCT ON (related_entity_id)
        bank_txn_id,
        related_entity_id,
        business_event_date,
        account_id,
        amount_thb
    FROM fah_sai_lpk_core.fact_bank_transaction
    WHERE related_entity_table = 'FACT_SALES_DEPOSIT_BATCH'
    ORDER BY related_entity_id, bank_txn_id
)
SELECT
    sb.sales_deposit_batch_id,
    sb.business_event_date,
    sb.branch_code,
    sb.payment_method,
    sb.txn_count,
    sb.net_total_thb,
    bb.bank_txn_id AS settlement_bank_txn_id,
    bb.account_id AS settlement_account_id,
    bb.amount_thb AS bank_amount_thb,
    CASE
        WHEN bb.bank_txn_id IS NULL THEN 'missing_bank_transaction'
        WHEN sb.net_total_thb = bb.amount_thb THEN 'matched'
        ELSE 'amount_mismatch'
    END AS reconciliation_status
FROM sales_batches sb
LEFT JOIN bank_batches bb
  ON bb.related_entity_id = sb.sales_deposit_batch_id
WITH NO DATA;

CREATE UNIQUE INDEX mv_sales_deposit_batch_reconciliation_uidx
    ON fah_sai_lpk_mart.mv_sales_deposit_batch_reconciliation (sales_deposit_batch_id);
CREATE INDEX mv_sales_deposit_batch_reconciliation_date_branch_idx
    ON fah_sai_lpk_mart.mv_sales_deposit_batch_reconciliation (business_event_date, branch_code, payment_method);
CREATE INDEX mv_sales_deposit_batch_reconciliation_status_idx
    ON fah_sai_lpk_mart.mv_sales_deposit_batch_reconciliation (reconciliation_status);

COMMENT ON MATERIALIZED VIEW fah_sai_lpk_mart.mv_sales_deposit_batch_reconciliation IS
    'Materialized virtual QA/reconciliation view only. Does not recreate FACT_SALES_DEPOSIT_BATCH as an official table.';

CREATE MATERIALIZED VIEW fah_sai_lpk_mart.mv_sales_order AS
SELECT
    s.*,
    c.customer_type,
    c.loyalty_tier,
    b.name_en AS branch_name_en,
    e.position_title AS sales_employee_position,
    pc.description_en AS promo_description_en,
    bt.transaction_type AS settlement_transaction_type,
    bt.amount_thb AS settlement_amount_thb
FROM fah_sai_lpk_core.fact_sales s
LEFT JOIN fah_sai_lpk_core.dim_customer c ON c.customer_id = s.customer_id
LEFT JOIN fah_sai_lpk_core.dim_branch b ON b.branch_code = s.branch_code
LEFT JOIN fah_sai_lpk_core.dim_employee e ON e.employee_id = s.employee_id
LEFT JOIN fah_sai_lpk_core.dim_promo_campaign pc ON pc.campaign_id = s.promo_campaign_id
LEFT JOIN fah_sai_lpk_core.fact_bank_transaction bt ON bt.bank_txn_id = s.settlement_bank_txn_id
WITH NO DATA;

CREATE UNIQUE INDEX mv_sales_order_txn_id_uidx
    ON fah_sai_lpk_mart.mv_sales_order (txn_id);
CREATE INDEX mv_sales_order_date_branch_idx
    ON fah_sai_lpk_mart.mv_sales_order (business_event_date, branch_code);
CREATE INDEX mv_sales_order_customer_date_idx
    ON fah_sai_lpk_mart.mv_sales_order (customer_id, business_event_date);
CREATE INDEX mv_sales_order_payment_status_date_idx
    ON fah_sai_lpk_mart.mv_sales_order (payment_status, business_event_date);
CREATE INDEX mv_sales_order_b2b_open_ar_idx
    ON fah_sai_lpk_mart.mv_sales_order (business_event_date, customer_id, net_total_thb DESC)
    WHERE is_b2b = true AND payment_received_date IS NULL;

CREATE MATERIALIZED VIEW fah_sai_lpk_mart.mv_sales_line AS
SELECT
    li.*,
    s.branch_code,
    s.customer_id,
    s.employee_id,
    s.channel,
    s.payment_method,
    p.brand_family,
    p.category,
    p.subcategory,
    p.vendor_id,
    v.name_en AS vendor_name_en,
    d.dept_name_en
FROM fah_sai_lpk_core.fact_sales_line_item li
LEFT JOIN fah_sai_lpk_core.fact_sales s ON s.txn_id = li.txn_id
LEFT JOIN fah_sai_lpk_core.dim_product p ON p.sku_id = li.sku_id
LEFT JOIN fah_sai_lpk_core.dim_vendor v ON v.vendor_id = p.vendor_id
LEFT JOIN fah_sai_lpk_core.dim_department d ON d.dept_code = p.dept_code
WITH NO DATA;

CREATE UNIQUE INDEX mv_sales_line_line_item_id_uidx
    ON fah_sai_lpk_mart.mv_sales_line (line_item_id);
CREATE INDEX mv_sales_line_txn_sku_idx
    ON fah_sai_lpk_mart.mv_sales_line (txn_id, sku_id);
CREATE INDEX mv_sales_line_sku_date_idx
    ON fah_sai_lpk_mart.mv_sales_line (sku_id, business_event_date);
CREATE INDEX mv_sales_line_branch_date_idx
    ON fah_sai_lpk_mart.mv_sales_line (branch_code, business_event_date);
CREATE INDEX mv_sales_line_category_date_idx
    ON fah_sai_lpk_mart.mv_sales_line (category, subcategory, business_event_date);

CREATE MATERIALIZED VIEW fah_sai_lpk_mart.mv_bank_reconciliation AS
SELECT
    bt.bank_txn_id,
    bt.business_event_date,
    bt.posting_date,
    bt.account_id,
    ba.bank,
    ba.account_role,
    ba.associated_branch_code,
    bt.transaction_type,
    bt.related_entity_table,
    bt.related_entity_id,
    bt.amount_thb,
    bt.balance_after_thb,
    bt.description,
    db.reconciliation_status AS deposit_batch_reconciliation_status,
    fs.txn_id AS direct_sales_txn_id,
    fp.payroll_id,
    fr.refund_id,
    fll.ledger_id,
    fvp.payment_id AS vendor_payment_id
FROM fah_sai_lpk_core.fact_bank_transaction bt
LEFT JOIN fah_sai_lpk_core.dim_bank_account ba ON ba.account_id = bt.account_id
LEFT JOIN fah_sai_lpk_mart.mv_sales_deposit_batch_reconciliation db
  ON bt.related_entity_table = 'FACT_SALES_DEPOSIT_BATCH'
 AND bt.related_entity_id = db.sales_deposit_batch_id
LEFT JOIN fah_sai_lpk_core.fact_sales fs
  ON bt.related_entity_table = 'FACT_SALES'
 AND bt.related_entity_id = fs.txn_id
LEFT JOIN fah_sai_lpk_core.fact_payroll fp
  ON bt.related_entity_table = 'FACT_PAYROLL'
 AND bt.related_entity_id = fp.payroll_id
LEFT JOIN fah_sai_lpk_core.fact_refund_paid fr
  ON bt.related_entity_table = 'FACT_REFUND_PAID'
 AND bt.related_entity_id = fr.refund_id
LEFT JOIN fah_sai_lpk_core.fact_loyalty_ledger fll
  ON bt.related_entity_table = 'FACT_LOYALTY_LEDGER'
 AND bt.related_entity_id = fll.ledger_id
LEFT JOIN fah_sai_lpk_core.fact_vendor_payment fvp
  ON bt.related_entity_table = 'FACT_VENDOR_PAYMENT'
 AND bt.related_entity_id = fvp.payment_id
WITH NO DATA;

CREATE UNIQUE INDEX mv_bank_reconciliation_bank_txn_id_uidx
    ON fah_sai_lpk_mart.mv_bank_reconciliation (bank_txn_id);
CREATE INDEX mv_bank_reconciliation_date_account_idx
    ON fah_sai_lpk_mart.mv_bank_reconciliation (business_event_date, account_id);
CREATE INDEX mv_bank_reconciliation_related_entity_idx
    ON fah_sai_lpk_mart.mv_bank_reconciliation (related_entity_table, related_entity_id);
CREATE INDEX mv_bank_reconciliation_amount_idx
    ON fah_sai_lpk_mart.mv_bank_reconciliation (amount_thb DESC);

CREATE MATERIALIZED VIEW fah_sai_lpk_mart.mv_vendor_payment AS
SELECT
    vp.*,
    v.name_en AS vendor_name_en,
    v.category AS vendor_category,
    cv.version_number AS contract_version_number,
    cv.effective_date AS contract_effective_date,
    cv.end_date AS contract_end_date,
    se.position_level AS signing_employee_position_level,
    ce.position_level AS cosig_employee_position_level,
    bt.amount_thb AS bank_amount_thb
FROM fah_sai_lpk_core.fact_vendor_payment vp
LEFT JOIN fah_sai_lpk_core.dim_vendor v ON v.vendor_id = vp.vendor_id
LEFT JOIN fah_sai_lpk_core.dim_vendor_contract_version cv ON cv.contract_version_id = vp.vendor_contract_version_id
LEFT JOIN fah_sai_lpk_core.dim_employee se ON se.employee_id = vp.signing_employee_id
LEFT JOIN fah_sai_lpk_core.dim_employee ce ON ce.employee_id = vp.cosig_employee_id
LEFT JOIN fah_sai_lpk_core.fact_bank_transaction bt ON bt.bank_txn_id = vp.bank_txn_id
WITH NO DATA;

CREATE UNIQUE INDEX mv_vendor_payment_payment_id_uidx
    ON fah_sai_lpk_mart.mv_vendor_payment (payment_id);
CREATE INDEX mv_vendor_payment_vendor_date_idx
    ON fah_sai_lpk_mart.mv_vendor_payment (vendor_id, business_event_date);
CREATE INDEX mv_vendor_payment_invoice_idx
    ON fah_sai_lpk_mart.mv_vendor_payment (vendor_invoice_id);
CREATE INDEX mv_vendor_payment_contract_idx
    ON fah_sai_lpk_mart.mv_vendor_payment (vendor_contract_version_id);

CREATE OR REPLACE FUNCTION fah_sai_lpk_mart.refresh_all_materialized_views(use_concurrently boolean DEFAULT false)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    refresh_prefix text := CASE
        WHEN use_concurrently THEN 'REFRESH MATERIALIZED VIEW CONCURRENTLY '
        ELSE 'REFRESH MATERIALIZED VIEW '
    END;
BEGIN
    EXECUTE refresh_prefix || 'fah_sai_lpk_mart.mv_sales_deposit_batch_reconciliation';
    EXECUTE refresh_prefix || 'fah_sai_lpk_mart.mv_sales_order';
    EXECUTE refresh_prefix || 'fah_sai_lpk_mart.mv_sales_line';
    EXECUTE refresh_prefix || 'fah_sai_lpk_mart.mv_bank_reconciliation';
    EXECUTE refresh_prefix || 'fah_sai_lpk_mart.mv_vendor_payment';

    EXECUTE 'ANALYZE fah_sai_lpk_mart.mv_sales_deposit_batch_reconciliation';
    EXECUTE 'ANALYZE fah_sai_lpk_mart.mv_sales_order';
    EXECUTE 'ANALYZE fah_sai_lpk_mart.mv_sales_line';
    EXECUTE 'ANALYZE fah_sai_lpk_mart.mv_bank_reconciliation';
    EXECUTE 'ANALYZE fah_sai_lpk_mart.mv_vendor_payment';
END;
$$;

COMMENT ON FUNCTION fah_sai_lpk_mart.refresh_all_materialized_views(boolean) IS
    'Refresh materialized mart caches. Use false for first load; true only after materialized views are already populated.';

CREATE OR REPLACE VIEW fah_sai_lpk_mart.v_sales_deposit_batch_reconciliation AS
SELECT * FROM fah_sai_lpk_mart.mv_sales_deposit_batch_reconciliation;

CREATE OR REPLACE VIEW fah_sai_lpk_mart.v_sales_order AS
SELECT * FROM fah_sai_lpk_mart.mv_sales_order;

CREATE OR REPLACE VIEW fah_sai_lpk_mart.v_sales_line AS
SELECT * FROM fah_sai_lpk_mart.mv_sales_line;

CREATE OR REPLACE VIEW fah_sai_lpk_mart.v_bank_reconciliation AS
SELECT * FROM fah_sai_lpk_mart.mv_bank_reconciliation;

CREATE OR REPLACE VIEW fah_sai_lpk_mart.v_vendor_payment AS
SELECT * FROM fah_sai_lpk_mart.mv_vendor_payment;

COMMENT ON VIEW fah_sai_lpk_mart.v_sales_deposit_batch_reconciliation IS
    'Compatibility view over fah_sai_lpk_mart.mv_sales_deposit_batch_reconciliation.';
COMMENT ON VIEW fah_sai_lpk_mart.v_sales_order IS
    'Compatibility view over fah_sai_lpk_mart.mv_sales_order.';
COMMENT ON VIEW fah_sai_lpk_mart.v_sales_line IS
    'Compatibility view over fah_sai_lpk_mart.mv_sales_line.';
COMMENT ON VIEW fah_sai_lpk_mart.v_bank_reconciliation IS
    'Compatibility view over fah_sai_lpk_mart.mv_bank_reconciliation.';
COMMENT ON VIEW fah_sai_lpk_mart.v_vendor_payment IS
    'Compatibility view over fah_sai_lpk_mart.mv_vendor_payment.';
