-- FahMai canonical fact date convention.
-- Forward-only metadata migration. This records the judge clarification without
-- changing table shape, data, indexes, or mart grain.

-- Canonical convention:
-- For fact-table period questions such as "in year 2568", "in month X", or
-- "in quarter X" that do not name a date column, filter on business_event_date.
-- Use posting_date only when the question explicitly asks for accounting,
-- booked, posted, ledger, or payment-posting timing. FACT_VENDOR_PAYMENT is the
-- main exception where posting_date may lag business_event_date by about 28
-- days because of NET-30 terms.

COMMENT ON COLUMN fah_sai_lpk_core.fact_bank_transaction.business_event_date IS
    'Canonical default date axis for business/event period filters. If a question says year/month/quarter without naming a date column, filter on business_event_date.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_bank_transaction.posting_date IS
    'Accounting posting date. Use only when the question explicitly asks for posted/booked/accounting timing.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_bank_transaction.effective_date IS
    'Fact-row effective metadata; not the default period filter for business questions.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_bank_transaction.as_of_date IS
    'Bundle/snapshot as-of metadata; not the event period filter.';

COMMENT ON COLUMN fah_sai_lpk_core.fact_cs_interaction.business_event_date IS
    'Canonical default date axis for business/event period filters. If a question says year/month/quarter without naming a date column, filter on business_event_date.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_cs_interaction.posting_date IS
    'Accounting posting date. Use only when the question explicitly asks for posted/booked/accounting timing.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_cs_interaction.effective_date IS
    'Fact-row effective metadata; not the default period filter for business questions.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_cs_interaction.as_of_date IS
    'Bundle/snapshot as-of metadata; not the event period filter.';

COMMENT ON COLUMN fah_sai_lpk_core.fact_inventory_monthly_snapshot.business_event_date IS
    'Canonical default date axis for business/event period filters. If a question says year/month/quarter without naming a date column, filter on business_event_date.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_inventory_monthly_snapshot.posting_date IS
    'Accounting posting date. Use only when the question explicitly asks for posted/booked/accounting timing.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_inventory_monthly_snapshot.effective_date IS
    'Fact-row effective metadata; not the default period filter for business questions.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_inventory_monthly_snapshot.as_of_date IS
    'Bundle/snapshot as-of metadata; not the event period filter.';

COMMENT ON COLUMN fah_sai_lpk_core.fact_inventory_movement.business_event_date IS
    'Canonical default date axis for business/event period filters. If a question says year/month/quarter without naming a date column, filter on business_event_date.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_inventory_movement.posting_date IS
    'Accounting posting date. Use only when the question explicitly asks for posted/booked/accounting timing.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_inventory_movement.effective_date IS
    'Fact-row effective metadata; not the default period filter for business questions.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_inventory_movement.as_of_date IS
    'Bundle/snapshot as-of metadata; not the event period filter.';

COMMENT ON COLUMN fah_sai_lpk_core.fact_loyalty_ledger.business_event_date IS
    'Canonical default date axis for business/event period filters. If a question says year/month/quarter without naming a date column, filter on business_event_date.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_loyalty_ledger.posting_date IS
    'Accounting posting date. Use only when the question explicitly asks for posted/booked/accounting timing.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_loyalty_ledger.effective_date IS
    'Fact-row effective metadata; not the default period filter for business questions.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_loyalty_ledger.as_of_date IS
    'Bundle/snapshot as-of metadata; not the event period filter.';

COMMENT ON COLUMN fah_sai_lpk_core.fact_payroll.business_event_date IS
    'Canonical default date axis for business/event period filters. If a question says year/month/quarter without naming a date column, filter on business_event_date.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_payroll.posting_date IS
    'Accounting posting date. Use only when the question explicitly asks for posted/booked/accounting timing.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_payroll.effective_date IS
    'Fact-row effective metadata; not the default period filter for business questions.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_payroll.as_of_date IS
    'Bundle/snapshot as-of metadata; not the event period filter.';

COMMENT ON COLUMN fah_sai_lpk_core.fact_promo_redemption.business_event_date IS
    'Canonical default date axis for business/event period filters. If a question says year/month/quarter without naming a date column, filter on business_event_date.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_promo_redemption.posting_date IS
    'Accounting posting date. Use only when the question explicitly asks for posted/booked/accounting timing.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_promo_redemption.effective_date IS
    'Fact-row effective metadata; not the default period filter for business questions.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_promo_redemption.as_of_date IS
    'Bundle/snapshot as-of metadata; not the event period filter.';

COMMENT ON COLUMN fah_sai_lpk_core.fact_refund_paid.business_event_date IS
    'Canonical default date axis for business/event period filters. If a question says year/month/quarter without naming a date column, filter on business_event_date.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_refund_paid.posting_date IS
    'Accounting posting date. Use only when the question explicitly asks for posted/booked/accounting timing.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_refund_paid.effective_date IS
    'Fact-row effective metadata; not the default period filter for business questions.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_refund_paid.as_of_date IS
    'Bundle/snapshot as-of metadata; not the event period filter.';

COMMENT ON COLUMN fah_sai_lpk_core.fact_return.business_event_date IS
    'Canonical default date axis for business/event period filters. If a question says year/month/quarter without naming a date column, filter on business_event_date.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_return.posting_date IS
    'Accounting posting date. Use only when the question explicitly asks for posted/booked/accounting timing.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_return.effective_date IS
    'Fact-row effective metadata; not the default period filter for business questions.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_return.as_of_date IS
    'Bundle/snapshot as-of metadata; not the event period filter.';

COMMENT ON COLUMN fah_sai_lpk_core.fact_sales.business_event_date IS
    'Canonical default date axis for business/event period filters. If a question says year/month/quarter without naming a date column, filter on business_event_date.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_sales.posting_date IS
    'Accounting posting date. Use only when the question explicitly asks for posted/booked/accounting timing.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_sales.effective_date IS
    'Fact-row effective metadata; not the default period filter for business questions.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_sales.as_of_date IS
    'Bundle/snapshot as-of metadata; not the event period filter.';

COMMENT ON COLUMN fah_sai_lpk_core.fact_sales_line_item.business_event_date IS
    'Canonical default date axis for business/event period filters. If a question says year/month/quarter without naming a date column, filter on business_event_date.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_sales_line_item.posting_date IS
    'Accounting posting date. Use only when the question explicitly asks for posted/booked/accounting timing.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_sales_line_item.effective_date IS
    'Fact-row effective metadata; not the default period filter for business questions.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_sales_line_item.as_of_date IS
    'Bundle/snapshot as-of metadata; not the event period filter.';

COMMENT ON COLUMN fah_sai_lpk_core.fact_shipping.business_event_date IS
    'Canonical default date axis for business/event period filters. If a question says year/month/quarter without naming a date column, filter on business_event_date.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_shipping.posting_date IS
    'Accounting posting date. Use only when the question explicitly asks for posted/booked/accounting timing.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_shipping.effective_date IS
    'Fact-row effective metadata; not the default period filter for business questions.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_shipping.as_of_date IS
    'Bundle/snapshot as-of metadata; not the event period filter.';

COMMENT ON COLUMN fah_sai_lpk_core.fact_vendor_payment.business_event_date IS
    'Canonical default date axis for vendor-payment business/event period filters. Posting date may lag this date by about 28 days because of NET-30 terms.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_vendor_payment.posting_date IS
    'Accounting posting date for vendor payments. Use only when the question explicitly asks for posted/booked/accounting timing; this may lag business_event_date by about 28 days because of NET-30 terms.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_vendor_payment.effective_date IS
    'Fact-row effective metadata; not the default period filter for business questions.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_vendor_payment.as_of_date IS
    'Bundle/snapshot as-of metadata; not the event period filter.';

COMMENT ON COLUMN fah_sai_lpk_core.fact_warranty_claim.business_event_date IS
    'Canonical default date axis for business/event period filters. If a question says year/month/quarter without naming a date column, filter on business_event_date.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_warranty_claim.posting_date IS
    'Accounting posting date. Use only when the question explicitly asks for posted/booked/accounting timing.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_warranty_claim.effective_date IS
    'Fact-row effective metadata; not the default period filter for business questions.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_warranty_claim.as_of_date IS
    'Bundle/snapshot as-of metadata; not the event period filter.';

DO $$
BEGIN
    IF to_regclass('fah_sai_lpk_eval.sql_templates') IS NOT NULL THEN
        UPDATE fah_sai_lpk_eval.sql_templates AS t
        SET
            anti_overfit_notes = v.anti_overfit_notes,
            updated_at = now()
        FROM (
            VALUES
                (
                    'top_selling_sku_by_period',
                    'For year/month/quarter questions without an explicit date column, use business_event_date as the canonical period axis. Do not hardcode year/SKU unless the question provides it.'
                ),
                (
                    'resolve_policy_at_date',
                    'Policy date comes from the question or per-row business_event_date. Do not use current date unless asked.'
                ),
                (
                    'bank_largest_deposit',
                    'For fact period filters, use business_event_date unless the question explicitly asks for posting/accounting date. Use related_entity_table to route context.'
                ),
                (
                    'refund_authority_check',
                    'Resolve policy per row by refund business_event_date; do not apply latest policy to old rows or switch to posting_date unless asked.'
                ),
                (
                    'vendor_contract_resolution',
                    'Use business_event_date as the default vendor-payment period axis; posting_date is only for explicit posting/accounting questions and may lag because of NET-30. Do not resolve by vendor_id alone.'
                ),
                (
                    'b2b_open_ar',
                    'For sales period filters, use business_event_date unless the question explicitly names another date axis. Use unpaid/open status from data.'
                ),
                (
                    'return_rate_by_sku_branch_period',
                    'For sales and return period filters, use business_event_date unless the question explicitly names another date axis. Keep numerator and denominator grain explicit.'
                )
        ) AS v(template_name, anti_overfit_notes)
        WHERE t.template_name = v.template_name;
    END IF;
END $$;
