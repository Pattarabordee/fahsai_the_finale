-- FahMai model-facing schema.
-- This layer minimizes the table/view surface exposed to LLM Text-to-SQL while
-- preserving the official core/RAG schemas as the source of truth.

CREATE SCHEMA IF NOT EXISTS fah_sai_lpk_model;

DROP VIEW IF EXISTS fah_sai_lpk_model.document_evidence;
DROP VIEW IF EXISTS fah_sai_lpk_model.policy_catalog;
DROP VIEW IF EXISTS fah_sai_lpk_model.product_catalog;
DROP VIEW IF EXISTS fah_sai_lpk_model.inventory_event;
DROP VIEW IF EXISTS fah_sai_lpk_model.customer_ops_event;
DROP VIEW IF EXISTS fah_sai_lpk_model.finance_event;
DROP VIEW IF EXISTS fah_sai_lpk_model.sales_line_360;
DROP VIEW IF EXISTS fah_sai_lpk_model.sales_order_360;

CREATE OR REPLACE VIEW fah_sai_lpk_model.sales_order_360 AS
SELECT
    'FACT_SALES'::text AS source_table,
    s.txn_id AS source_pk,
    ARRAY[
        'FACT_SALES',
        'DIM_BRANCH',
        'DIM_CUSTOMER',
        'DIM_EMPLOYEE',
        'DIM_PROMO_CAMPAIGN',
        'FACT_BANK_TRANSACTION'
    ]::text[] AS source_aliases,
    s.txn_id,
    s.business_event_date,
    s.posting_date,
    s.effective_date,
    s.as_of_date,
    s.branch_code,
    b.name_en AS branch_name_en,
    b.branch_type,
    b.is_service_center,
    s.customer_id,
    c.customer_type,
    c.b2b_subtype,
    c.payment_terms AS customer_payment_terms,
    c.loyalty_tier,
    c.province AS customer_province,
    c.region AS customer_region,
    c.account_manager_id,
    s.employee_id,
    e.position_title AS sales_employee_position,
    e.position_level AS sales_employee_position_level,
    e.dept_code AS sales_employee_dept_code,
    s.channel,
    s.basket_total_thb,
    s.discount_total_thb,
    s.net_total_thb,
    s.shipping_charge_thb,
    s.shipping_method,
    s.promo_campaign_id,
    pc.description_en AS promo_description_en,
    pc.start_timestamp AS promo_start_timestamp,
    pc.end_timestamp AS promo_end_timestamp,
    s.payment_method,
    s.payment_status,
    s.payment_due_date,
    s.payment_received_date,
    s.settlement_bank_txn_id,
    bt.account_id AS settlement_account_id,
    bt.transaction_type AS settlement_transaction_type,
    bt.amount_thb AS settlement_amount_thb,
    s.web_log_line_id,
    s.schema_version,
    s.is_b2b,
    s.retry_idempotency_marker
FROM fah_sai_lpk_core.fact_sales s
LEFT JOIN fah_sai_lpk_core.dim_branch b ON b.branch_code = s.branch_code
LEFT JOIN fah_sai_lpk_core.dim_customer c ON c.customer_id = s.customer_id
LEFT JOIN fah_sai_lpk_core.dim_employee e ON e.employee_id = s.employee_id
LEFT JOIN fah_sai_lpk_core.dim_promo_campaign pc ON pc.campaign_id = s.promo_campaign_id
LEFT JOIN fah_sai_lpk_core.fact_bank_transaction bt ON bt.bank_txn_id = s.settlement_bank_txn_id;

CREATE OR REPLACE VIEW fah_sai_lpk_model.sales_line_360 AS
SELECT
    'FACT_SALES_LINE_ITEM'::text AS source_table,
    li.line_item_id AS source_pk,
    ARRAY[
        'FACT_SALES_LINE_ITEM',
        'FACT_SALES',
        'DIM_PRODUCT',
        'DIM_VENDOR',
        'DIM_DEPARTMENT'
    ]::text[] AS source_aliases,
    li.line_item_id,
    li.txn_id,
    li.business_event_date,
    li.posting_date,
    li.effective_date,
    li.as_of_date,
    s.branch_code,
    s.customer_id,
    s.employee_id,
    s.channel,
    s.payment_method,
    s.payment_status,
    s.is_b2b,
    s.net_total_thb AS order_net_total_thb,
    li.sku_id,
    p.brand_family,
    p.dept_code,
    d.dept_name_en,
    p.category,
    p.subcategory,
    p.msrp_thb,
    p.msrp_tier,
    p.is_third_party,
    p.vendor_id,
    v.name_en AS vendor_name_en,
    p.launch_date,
    p.end_of_life_date,
    p.warranty_months,
    p.care_plus_eligible,
    li.quantity,
    li.unit_price_thb,
    li.line_discount_thb,
    li.line_total_thb,
    li.is_care_plus,
    li.pos_log_line_id
FROM fah_sai_lpk_core.fact_sales_line_item li
LEFT JOIN fah_sai_lpk_core.fact_sales s ON s.txn_id = li.txn_id
LEFT JOIN fah_sai_lpk_core.dim_product p ON p.sku_id = li.sku_id
LEFT JOIN fah_sai_lpk_core.dim_vendor v ON v.vendor_id = p.vendor_id
LEFT JOIN fah_sai_lpk_core.dim_department d ON d.dept_code = p.dept_code;

CREATE OR REPLACE VIEW fah_sai_lpk_model.finance_event AS
SELECT
    'FACT_BANK_TRANSACTION'::text AS source_table,
    bt.bank_txn_id AS source_pk,
    ARRAY['FACT_BANK_TRANSACTION', 'DIM_BANK_ACCOUNT']::text[] AS source_aliases,
    'bank_transaction'::text AS event_type,
    bt.bank_txn_id AS event_id,
    bt.business_event_date,
    bt.posting_date,
    bt.effective_date,
    bt.as_of_date,
    bt.bank_txn_id,
    bt.account_id,
    ba.bank,
    ba.account_role,
    ba.associated_branch_code,
    bt.transaction_type,
    bt.related_entity_table,
    bt.related_entity_id,
    bt.amount_thb,
    CASE
        WHEN bt.amount_thb > 0 THEN 'inflow'
        WHEN bt.amount_thb < 0 THEN 'outflow'
        ELSE 'zero'
    END AS amount_direction,
    bt.balance_after_thb,
    bt.counterparty,
    bt.description,
    NULL::text AS customer_id,
    NULL::text AS vendor_id,
    NULL::text AS vendor_name_en,
    NULL::text AS employee_id,
    NULL::text AS employee_position_level,
    NULL::text AS refund_id,
    NULL::text AS return_id,
    NULL::text AS payment_id,
    NULL::text AS payroll_id,
    NULL::text AS vendor_invoice_id,
    NULL::date AS invoice_period_start,
    NULL::date AS invoice_period_end,
    NULL::date AS request_date,
    NULL::text AS approver_employee_id,
    NULL::text AS cosig_employee_id,
    jsonb_build_object(
        'bank_description', bt.description,
        'currency', ba.currency,
        'statement_cadence', ba.statement_cadence
    ) AS attributes
FROM fah_sai_lpk_core.fact_bank_transaction bt
LEFT JOIN fah_sai_lpk_core.dim_bank_account ba ON ba.account_id = bt.account_id

UNION ALL

SELECT
    'FACT_REFUND_PAID'::text AS source_table,
    r.refund_id AS source_pk,
    ARRAY[
        'FACT_REFUND_PAID',
        'FACT_RETURN',
        'FACT_CS_INTERACTION',
        'DIM_CUSTOMER',
        'DIM_EMPLOYEE',
        'FACT_BANK_TRANSACTION'
    ]::text[] AS source_aliases,
    'refund_paid'::text AS event_type,
    r.refund_id AS event_id,
    r.business_event_date,
    r.posting_date,
    r.effective_date,
    r.as_of_date,
    r.bank_txn_id,
    bt.account_id,
    ba.bank,
    ba.account_role,
    ba.associated_branch_code,
    bt.transaction_type,
    'FACT_RETURN'::text AS related_entity_table,
    r.return_id AS related_entity_id,
    r.refund_amount_thb AS amount_thb,
    'outflow'::text AS amount_direction,
    bt.balance_after_thb,
    r.customer_id AS counterparty,
    'refund paid'::text AS description,
    r.customer_id,
    NULL::text AS vendor_id,
    NULL::text AS vendor_name_en,
    r.approver_employee_id AS employee_id,
    ae.position_level AS employee_position_level,
    r.refund_id,
    r.return_id,
    NULL::text AS payment_id,
    NULL::text AS payroll_id,
    NULL::text AS vendor_invoice_id,
    NULL::date AS invoice_period_start,
    NULL::date AS invoice_period_end,
    r.request_date,
    r.approver_employee_id,
    r.cosig_employee_id,
    jsonb_build_object(
        'cs_interaction_id', r.cs_interaction_id,
        'customer_type', c.customer_type,
        'cosig_employee_position_level', ce.position_level,
        'bank_amount_thb', bt.amount_thb
    ) AS attributes
FROM fah_sai_lpk_core.fact_refund_paid r
LEFT JOIN fah_sai_lpk_core.fact_bank_transaction bt ON bt.bank_txn_id = r.bank_txn_id
LEFT JOIN fah_sai_lpk_core.dim_bank_account ba ON ba.account_id = bt.account_id
LEFT JOIN fah_sai_lpk_core.dim_customer c ON c.customer_id = r.customer_id
LEFT JOIN fah_sai_lpk_core.dim_employee ae ON ae.employee_id = r.approver_employee_id
LEFT JOIN fah_sai_lpk_core.dim_employee ce ON ce.employee_id = r.cosig_employee_id

UNION ALL

SELECT
    'FACT_VENDOR_PAYMENT'::text AS source_table,
    vp.payment_id AS source_pk,
    ARRAY[
        'FACT_VENDOR_PAYMENT',
        'DIM_VENDOR',
        'DIM_VENDOR_CONTRACT_VERSION',
        'DIM_EMPLOYEE',
        'FACT_BANK_TRANSACTION'
    ]::text[] AS source_aliases,
    'vendor_payment'::text AS event_type,
    vp.payment_id AS event_id,
    vp.business_event_date,
    vp.posting_date,
    vp.effective_date,
    vp.as_of_date,
    vp.bank_txn_id,
    bt.account_id,
    ba.bank,
    ba.account_role,
    ba.associated_branch_code,
    bt.transaction_type,
    'DIM_VENDOR'::text AS related_entity_table,
    vp.vendor_id AS related_entity_id,
    vp.paid_amount_thb AS amount_thb,
    'outflow'::text AS amount_direction,
    bt.balance_after_thb,
    v.name_en AS counterparty,
    'vendor payment'::text AS description,
    NULL::text AS customer_id,
    vp.vendor_id,
    v.name_en AS vendor_name_en,
    vp.signing_employee_id AS employee_id,
    se.position_level AS employee_position_level,
    NULL::text AS refund_id,
    NULL::text AS return_id,
    vp.payment_id,
    NULL::text AS payroll_id,
    vp.vendor_invoice_id,
    vp.invoice_period_start,
    vp.invoice_period_end,
    vp.request_date,
    vp.signing_employee_id AS approver_employee_id,
    vp.cosig_employee_id,
    jsonb_build_object(
        'vendor_category', v.category,
        'vendor_contract_version_id', vp.vendor_contract_version_id,
        'contract_version_number', cv.version_number,
        'contract_effective_date', cv.effective_date,
        'contract_end_date', cv.end_date,
        'cosig_employee_position_level', ce.position_level,
        'bank_amount_thb', bt.amount_thb
    ) AS attributes
FROM fah_sai_lpk_core.fact_vendor_payment vp
LEFT JOIN fah_sai_lpk_core.dim_vendor v ON v.vendor_id = vp.vendor_id
LEFT JOIN fah_sai_lpk_core.dim_vendor_contract_version cv ON cv.contract_version_id = vp.vendor_contract_version_id
LEFT JOIN fah_sai_lpk_core.dim_employee se ON se.employee_id = vp.signing_employee_id
LEFT JOIN fah_sai_lpk_core.dim_employee ce ON ce.employee_id = vp.cosig_employee_id
LEFT JOIN fah_sai_lpk_core.fact_bank_transaction bt ON bt.bank_txn_id = vp.bank_txn_id
LEFT JOIN fah_sai_lpk_core.dim_bank_account ba ON ba.account_id = bt.account_id

UNION ALL

SELECT
    'FACT_PAYROLL'::text AS source_table,
    p.payroll_id AS source_pk,
    ARRAY[
        'FACT_PAYROLL',
        'DIM_EMPLOYEE',
        'DIM_BRANCH',
        'DIM_DEPARTMENT',
        'FACT_BANK_TRANSACTION'
    ]::text[] AS source_aliases,
    'payroll'::text AS event_type,
    p.payroll_id AS event_id,
    p.business_event_date,
    p.posting_date,
    p.effective_date,
    p.as_of_date,
    p.bank_txn_id,
    bt.account_id,
    ba.bank,
    ba.account_role,
    ba.associated_branch_code,
    bt.transaction_type,
    'DIM_EMPLOYEE'::text AS related_entity_table,
    p.employee_id AS related_entity_id,
    p.net_pay_thb AS amount_thb,
    'outflow'::text AS amount_direction,
    bt.balance_after_thb,
    p.employee_id AS counterparty,
    'payroll'::text AS description,
    NULL::text AS customer_id,
    NULL::text AS vendor_id,
    NULL::text AS vendor_name_en,
    p.employee_id,
    e.position_level AS employee_position_level,
    NULL::text AS refund_id,
    NULL::text AS return_id,
    NULL::text AS payment_id,
    p.payroll_id,
    NULL::text AS vendor_invoice_id,
    p.pay_period_start AS invoice_period_start,
    p.pay_period_end AS invoice_period_end,
    NULL::date AS request_date,
    NULL::text AS approver_employee_id,
    NULL::text AS cosig_employee_id,
    jsonb_build_object(
        'gross_pay_thb', p.gross_pay_thb,
        'tax_deduction_thb', p.tax_deduction_thb,
        'social_security_thb', p.social_security_thb,
        'employment_status_at_period_end', p.employment_status_at_period_end,
        'employee_branch_code', e.branch_code,
        'employee_dept_code', e.dept_code,
        'employee_dept_name_en', d.dept_name_en,
        'bank_amount_thb', bt.amount_thb
    ) AS attributes
FROM fah_sai_lpk_core.fact_payroll p
LEFT JOIN fah_sai_lpk_core.dim_employee e ON e.employee_id = p.employee_id
LEFT JOIN fah_sai_lpk_core.dim_department d ON d.dept_code = e.dept_code
LEFT JOIN fah_sai_lpk_core.fact_bank_transaction bt ON bt.bank_txn_id = p.bank_txn_id
LEFT JOIN fah_sai_lpk_core.dim_bank_account ba ON ba.account_id = bt.account_id;

CREATE OR REPLACE VIEW fah_sai_lpk_model.customer_ops_event AS
SELECT
    'FACT_RETURN'::text AS source_table,
    r.return_id AS source_pk,
    ARRAY[
        'FACT_RETURN',
        'FACT_SALES',
        'FACT_SALES_LINE_ITEM',
        'DIM_PRODUCT',
        'DIM_BRANCH',
        'DIM_CUSTOMER',
        'DIM_EMPLOYEE'
    ]::text[] AS source_aliases,
    'return'::text AS event_type,
    r.return_id AS event_id,
    r.business_event_date,
    r.posting_date,
    r.effective_date,
    r.as_of_date,
    r.customer_id,
    c.customer_type,
    c.loyalty_tier,
    r.approved_by_employee_id AS employee_id,
    ae.position_level AS employee_position_level,
    r.branch_code,
    b.name_en AS branch_name_en,
    r.original_txn_id AS txn_id,
    r.line_item_id,
    r.sku_id,
    p.brand_family,
    p.category,
    p.subcategory,
    p.vendor_id,
    NULL::text AS shipping_vendor_id,
    NULL::text AS shipping_vendor_name_en,
    r.return_amount_thb AS amount_thb,
    NULL::integer AS points_delta,
    NULL::integer AS resulting_balance_points,
    NULL::text AS resulting_tier,
    r.return_id,
    NULL::text AS refund_id,
    NULL::text AS warranty_claim_id,
    NULL::text AS shipping_id,
    NULL::text AS cs_interaction_id,
    NULL::text AS loyalty_ledger_id,
    NULL::text AS promo_redemption_id,
    NULL::text AS campaign_id,
    NULL::text AS channel,
    NULL::text AS interaction_type,
    NULL::text AS resolution_type,
    r.return_reason,
    NULL::text AS claim_reason,
    NULL::text AS routing_destination,
    NULL::text AS shipping_confirmation_status,
    NULL::text AS loyalty_event_type,
    NULL::numeric(18,2) AS discount_applied_thb,
    jsonb_build_object(
        'approved_by_employee_id', r.approved_by_employee_id,
        'days_since_purchase', r.days_since_purchase
    ) AS attributes
FROM fah_sai_lpk_core.fact_return r
LEFT JOIN fah_sai_lpk_core.dim_customer c ON c.customer_id = r.customer_id
LEFT JOIN fah_sai_lpk_core.dim_employee ae ON ae.employee_id = r.approved_by_employee_id
LEFT JOIN fah_sai_lpk_core.dim_branch b ON b.branch_code = r.branch_code
LEFT JOIN fah_sai_lpk_core.dim_product p ON p.sku_id = r.sku_id

UNION ALL

SELECT
    'FACT_WARRANTY_CLAIM'::text AS source_table,
    w.claim_id AS source_pk,
    ARRAY[
        'FACT_WARRANTY_CLAIM',
        'FACT_SALES',
        'DIM_PRODUCT',
        'DIM_CUSTOMER'
    ]::text[] AS source_aliases,
    'warranty_claim'::text AS event_type,
    w.claim_id AS event_id,
    w.business_event_date,
    w.posting_date,
    w.effective_date,
    w.as_of_date,
    w.customer_id,
    c.customer_type,
    c.loyalty_tier,
    NULL::text AS employee_id,
    NULL::text AS employee_position_level,
    s.branch_code,
    b.name_en AS branch_name_en,
    w.original_txn_id AS txn_id,
    NULL::text AS line_item_id,
    w.sku_id,
    p.brand_family,
    p.category,
    p.subcategory,
    p.vendor_id,
    NULL::text AS shipping_vendor_id,
    NULL::text AS shipping_vendor_name_en,
    w.claim_amount_thb AS amount_thb,
    NULL::integer AS points_delta,
    NULL::integer AS resulting_balance_points,
    NULL::text AS resulting_tier,
    NULL::text AS return_id,
    NULL::text AS refund_id,
    w.claim_id AS warranty_claim_id,
    NULL::text AS shipping_id,
    NULL::text AS cs_interaction_id,
    NULL::text AS loyalty_ledger_id,
    NULL::text AS promo_redemption_id,
    NULL::text AS campaign_id,
    NULL::text AS channel,
    NULL::text AS interaction_type,
    w.resolution_type,
    NULL::text AS return_reason,
    w.claim_reason,
    w.routing_destination,
    NULL::text AS shipping_confirmation_status,
    NULL::text AS loyalty_event_type,
    NULL::numeric(18,2) AS discount_applied_thb,
    jsonb_build_object(
        'original_txn_id', w.original_txn_id
    ) AS attributes
FROM fah_sai_lpk_core.fact_warranty_claim w
LEFT JOIN fah_sai_lpk_core.dim_customer c ON c.customer_id = w.customer_id
LEFT JOIN fah_sai_lpk_core.fact_sales s ON s.txn_id = w.original_txn_id
LEFT JOIN fah_sai_lpk_core.dim_branch b ON b.branch_code = s.branch_code
LEFT JOIN fah_sai_lpk_core.dim_product p ON p.sku_id = w.sku_id

UNION ALL

SELECT
    'FACT_CS_INTERACTION'::text AS source_table,
    cs.cs_interaction_id AS source_pk,
    ARRAY[
        'FACT_CS_INTERACTION',
        'DIM_CUSTOMER',
        'DIM_EMPLOYEE',
        'DIM_BRANCH',
        'FACT_REFUND_PAID',
        'FACT_WARRANTY_CLAIM'
    ]::text[] AS source_aliases,
    'cs_interaction'::text AS event_type,
    cs.cs_interaction_id AS event_id,
    cs.business_event_date,
    cs.posting_date,
    cs.effective_date,
    cs.as_of_date,
    cs.customer_id,
    c.customer_type,
    c.loyalty_tier,
    cs.employee_id,
    e.position_level AS employee_position_level,
    cs.branch_code,
    b.name_en AS branch_name_en,
    NULL::text AS txn_id,
    NULL::text AS line_item_id,
    NULL::text AS sku_id,
    NULL::text AS brand_family,
    NULL::text AS category,
    NULL::text AS subcategory,
    NULL::text AS vendor_id,
    NULL::text AS shipping_vendor_id,
    NULL::text AS shipping_vendor_name_en,
    NULL::numeric(18,2) AS amount_thb,
    NULL::integer AS points_delta,
    NULL::integer AS resulting_balance_points,
    NULL::text AS resulting_tier,
    NULL::text AS return_id,
    cs.related_refund_id AS refund_id,
    cs.related_warranty_claim_id AS warranty_claim_id,
    NULL::text AS shipping_id,
    cs.cs_interaction_id,
    NULL::text AS loyalty_ledger_id,
    NULL::text AS promo_redemption_id,
    NULL::text AS campaign_id,
    cs.channel,
    cs.interaction_type,
    cs.resolution_type,
    NULL::text AS return_reason,
    NULL::text AS claim_reason,
    NULL::text AS routing_destination,
    NULL::text AS shipping_confirmation_status,
    NULL::text AS loyalty_event_type,
    NULL::numeric(18,2) AS discount_applied_thb,
    jsonb_build_object(
        'chat_session_id', cs.chat_session_id
    ) AS attributes
FROM fah_sai_lpk_core.fact_cs_interaction cs
LEFT JOIN fah_sai_lpk_core.dim_customer c ON c.customer_id = cs.customer_id
LEFT JOIN fah_sai_lpk_core.dim_employee e ON e.employee_id = cs.employee_id
LEFT JOIN fah_sai_lpk_core.dim_branch b ON b.branch_code = cs.branch_code

UNION ALL

SELECT
    'FACT_SHIPPING'::text AS source_table,
    sh.shipping_id AS source_pk,
    ARRAY[
        'FACT_SHIPPING',
        'FACT_SALES',
        'DIM_VENDOR',
        'DIM_BRANCH',
        'DIM_CUSTOMER'
    ]::text[] AS source_aliases,
    'shipping'::text AS event_type,
    sh.shipping_id AS event_id,
    sh.business_event_date,
    sh.posting_date,
    sh.effective_date,
    sh.as_of_date,
    s.customer_id,
    c.customer_type,
    c.loyalty_tier,
    s.employee_id,
    e.position_level AS employee_position_level,
    sh.origin_branch_code AS branch_code,
    b.name_en AS branch_name_en,
    sh.txn_id,
    NULL::text AS line_item_id,
    NULL::text AS sku_id,
    NULL::text AS brand_family,
    NULL::text AS category,
    NULL::text AS subcategory,
    NULL::text AS vendor_id,
    sh.vendor_id AS shipping_vendor_id,
    v.name_en AS shipping_vendor_name_en,
    NULL::numeric(18,2) AS amount_thb,
    NULL::integer AS points_delta,
    NULL::integer AS resulting_balance_points,
    NULL::text AS resulting_tier,
    NULL::text AS return_id,
    NULL::text AS refund_id,
    NULL::text AS warranty_claim_id,
    sh.shipping_id,
    NULL::text AS cs_interaction_id,
    NULL::text AS loyalty_ledger_id,
    NULL::text AS promo_redemption_id,
    NULL::text AS campaign_id,
    NULL::text AS channel,
    NULL::text AS interaction_type,
    NULL::text AS resolution_type,
    NULL::text AS return_reason,
    NULL::text AS claim_reason,
    NULL::text AS routing_destination,
    sh.confirmation_status AS shipping_confirmation_status,
    NULL::text AS loyalty_event_type,
    NULL::numeric(18,2) AS discount_applied_thb,
    jsonb_build_object(
        'tracking_number', sh.tracking_number,
        'destination_province', sh.destination_province,
        'shipping_vendor_id', sh.vendor_id
    ) AS attributes
FROM fah_sai_lpk_core.fact_shipping sh
LEFT JOIN fah_sai_lpk_core.fact_sales s ON s.txn_id = sh.txn_id
LEFT JOIN fah_sai_lpk_core.dim_customer c ON c.customer_id = s.customer_id
LEFT JOIN fah_sai_lpk_core.dim_employee e ON e.employee_id = s.employee_id
LEFT JOIN fah_sai_lpk_core.dim_branch b ON b.branch_code = sh.origin_branch_code
LEFT JOIN fah_sai_lpk_core.dim_vendor v ON v.vendor_id = sh.vendor_id

UNION ALL

SELECT
    'FACT_LOYALTY_LEDGER'::text AS source_table,
    ll.ledger_id AS source_pk,
    ARRAY[
        'FACT_LOYALTY_LEDGER',
        'FACT_SALES',
        'DIM_CUSTOMER'
    ]::text[] AS source_aliases,
    'loyalty_ledger'::text AS event_type,
    ll.ledger_id AS event_id,
    ll.business_event_date,
    ll.posting_date,
    ll.effective_date,
    ll.as_of_date,
    ll.customer_id,
    c.customer_type,
    c.loyalty_tier,
    NULL::text AS employee_id,
    NULL::text AS employee_position_level,
    s.branch_code,
    b.name_en AS branch_name_en,
    ll.txn_id,
    NULL::text AS line_item_id,
    NULL::text AS sku_id,
    NULL::text AS brand_family,
    NULL::text AS category,
    NULL::text AS subcategory,
    NULL::text AS vendor_id,
    NULL::text AS shipping_vendor_id,
    NULL::text AS shipping_vendor_name_en,
    NULL::numeric(18,2) AS amount_thb,
    ll.points_delta,
    ll.resulting_balance_points,
    ll.resulting_tier,
    NULL::text AS return_id,
    NULL::text AS refund_id,
    NULL::text AS warranty_claim_id,
    NULL::text AS shipping_id,
    NULL::text AS cs_interaction_id,
    ll.ledger_id AS loyalty_ledger_id,
    NULL::text AS promo_redemption_id,
    NULL::text AS campaign_id,
    NULL::text AS channel,
    NULL::text AS interaction_type,
    NULL::text AS resolution_type,
    NULL::text AS return_reason,
    NULL::text AS claim_reason,
    NULL::text AS routing_destination,
    NULL::text AS shipping_confirmation_status,
    ll.event_type AS loyalty_event_type,
    NULL::numeric(18,2) AS discount_applied_thb,
    jsonb_build_object(
        'resulting_tier', ll.resulting_tier
    ) AS attributes
FROM fah_sai_lpk_core.fact_loyalty_ledger ll
LEFT JOIN fah_sai_lpk_core.dim_customer c ON c.customer_id = ll.customer_id
LEFT JOIN fah_sai_lpk_core.fact_sales s ON s.txn_id = ll.txn_id
LEFT JOIN fah_sai_lpk_core.dim_branch b ON b.branch_code = s.branch_code

UNION ALL

SELECT
    'FACT_PROMO_REDEMPTION'::text AS source_table,
    pr.redemption_id AS source_pk,
    ARRAY[
        'FACT_PROMO_REDEMPTION',
        'FACT_SALES',
        'DIM_CUSTOMER',
        'DIM_PROMO_CAMPAIGN'
    ]::text[] AS source_aliases,
    'promo_redemption'::text AS event_type,
    pr.redemption_id AS event_id,
    pr.business_event_date,
    pr.posting_date,
    pr.effective_date,
    pr.as_of_date,
    pr.customer_id,
    c.customer_type,
    c.loyalty_tier,
    s.employee_id,
    e.position_level AS employee_position_level,
    s.branch_code,
    b.name_en AS branch_name_en,
    pr.txn_id,
    NULL::text AS line_item_id,
    NULL::text AS sku_id,
    NULL::text AS brand_family,
    NULL::text AS category,
    NULL::text AS subcategory,
    NULL::text AS vendor_id,
    NULL::text AS shipping_vendor_id,
    NULL::text AS shipping_vendor_name_en,
    pr.discount_applied_thb AS amount_thb,
    NULL::integer AS points_delta,
    NULL::integer AS resulting_balance_points,
    NULL::text AS resulting_tier,
    NULL::text AS return_id,
    NULL::text AS refund_id,
    NULL::text AS warranty_claim_id,
    NULL::text AS shipping_id,
    NULL::text AS cs_interaction_id,
    NULL::text AS loyalty_ledger_id,
    pr.redemption_id AS promo_redemption_id,
    pr.campaign_id,
    pr.channel,
    NULL::text AS interaction_type,
    NULL::text AS resolution_type,
    NULL::text AS return_reason,
    NULL::text AS claim_reason,
    NULL::text AS routing_destination,
    NULL::text AS shipping_confirmation_status,
    NULL::text AS loyalty_event_type,
    pr.discount_applied_thb,
    jsonb_build_object(
        'campaign_description_en', pc.description_en,
        'campaign_start_timestamp', pc.start_timestamp,
        'campaign_end_timestamp', pc.end_timestamp
    ) AS attributes
FROM fah_sai_lpk_core.fact_promo_redemption pr
LEFT JOIN fah_sai_lpk_core.dim_customer c ON c.customer_id = pr.customer_id
LEFT JOIN fah_sai_lpk_core.fact_sales s ON s.txn_id = pr.txn_id
LEFT JOIN fah_sai_lpk_core.dim_employee e ON e.employee_id = s.employee_id
LEFT JOIN fah_sai_lpk_core.dim_branch b ON b.branch_code = s.branch_code
LEFT JOIN fah_sai_lpk_core.dim_promo_campaign pc ON pc.campaign_id = pr.campaign_id;

CREATE OR REPLACE VIEW fah_sai_lpk_model.inventory_event AS
SELECT
    'FACT_INVENTORY_MOVEMENT'::text AS source_table,
    im.movement_id AS source_pk,
    ARRAY[
        'FACT_INVENTORY_MOVEMENT',
        'DIM_PRODUCT',
        'DIM_BRANCH',
        'DIM_VENDOR',
        'DIM_DEPARTMENT'
    ]::text[] AS source_aliases,
    'inventory_movement'::text AS event_type,
    im.movement_id AS event_id,
    im.business_event_date,
    im.posting_date,
    im.effective_date,
    im.as_of_date,
    NULL::date AS month_end_date,
    im.sku_id,
    p.brand_family,
    p.dept_code,
    d.dept_name_en,
    p.category,
    p.subcategory,
    p.vendor_id,
    v.name_en AS vendor_name_en,
    im.branch_code,
    b.name_en AS branch_name_en,
    b.branch_type,
    im.movement_type,
    im.quantity,
    im.related_txn_id,
    NULL::integer AS closing_units,
    NULL::boolean AS is_stockout,
    jsonb_build_object(
        'related_txn_id', im.related_txn_id
    ) AS attributes
FROM fah_sai_lpk_core.fact_inventory_movement im
LEFT JOIN fah_sai_lpk_core.dim_product p ON p.sku_id = im.sku_id
LEFT JOIN fah_sai_lpk_core.dim_vendor v ON v.vendor_id = p.vendor_id
LEFT JOIN fah_sai_lpk_core.dim_department d ON d.dept_code = p.dept_code
LEFT JOIN fah_sai_lpk_core.dim_branch b ON b.branch_code = im.branch_code

UNION ALL

SELECT
    'FACT_INVENTORY_MONTHLY_SNAPSHOT'::text AS source_table,
    ims.snapshot_id AS source_pk,
    ARRAY[
        'FACT_INVENTORY_MONTHLY_SNAPSHOT',
        'DIM_PRODUCT',
        'DIM_BRANCH',
        'DIM_VENDOR',
        'DIM_DEPARTMENT'
    ]::text[] AS source_aliases,
    'inventory_monthly_snapshot'::text AS event_type,
    ims.snapshot_id AS event_id,
    ims.business_event_date,
    ims.posting_date,
    ims.effective_date,
    ims.as_of_date,
    ims.month_end_date,
    ims.sku_id,
    p.brand_family,
    p.dept_code,
    d.dept_name_en,
    p.category,
    p.subcategory,
    p.vendor_id,
    v.name_en AS vendor_name_en,
    ims.branch_code,
    b.name_en AS branch_name_en,
    b.branch_type,
    NULL::text AS movement_type,
    NULL::integer AS quantity,
    NULL::text AS related_txn_id,
    ims.closing_units,
    (ims.closing_units = 0) AS is_stockout,
    jsonb_build_object(
        'month_end_date', ims.month_end_date
    ) AS attributes
FROM fah_sai_lpk_core.fact_inventory_monthly_snapshot ims
LEFT JOIN fah_sai_lpk_core.dim_product p ON p.sku_id = ims.sku_id
LEFT JOIN fah_sai_lpk_core.dim_vendor v ON v.vendor_id = p.vendor_id
LEFT JOIN fah_sai_lpk_core.dim_department d ON d.dept_code = p.dept_code
LEFT JOIN fah_sai_lpk_core.dim_branch b ON b.branch_code = ims.branch_code;

CREATE OR REPLACE VIEW fah_sai_lpk_model.product_catalog AS
WITH care_plus AS (
    SELECT
        sku_id,
        count(*)::integer AS care_plus_tier_count,
        min(care_plus_price_thb)::numeric(18,2) AS min_care_plus_price_thb,
        max(care_plus_price_thb)::numeric(18,2) AS max_care_plus_price_thb,
        max(coverage_months)::integer AS max_care_plus_coverage_months,
        jsonb_agg(
            jsonb_build_object(
                'tier_row_id', tier_row_id,
                'policy_version_id', policy_version_id,
                'sku_category', sku_category,
                'care_plus_price_thb', care_plus_price_thb,
                'coverage_months', coverage_months,
                'description_th', description_th
            )
            ORDER BY tier_row_id
        ) AS care_plus_tiers
    FROM fah_sai_lpk_core.dim_care_plus_sku_tier
    GROUP BY sku_id
),
recall AS (
    SELECT
        sku_id,
        count(*)::integer AS recall_history_count,
        (array_agg(status ORDER BY transition_date DESC, history_id DESC))[1] AS latest_recall_status,
        max(transition_date) AS latest_recall_transition_date,
        jsonb_agg(
            jsonb_build_object(
                'history_id', history_id,
                'status', status,
                'transition_date', transition_date
            )
            ORDER BY transition_date, history_id
        ) AS recall_history
    FROM fah_sai_lpk_core.dim_product_recall_history
    GROUP BY sku_id
)
SELECT
    'DIM_PRODUCT'::text AS source_table,
    p.sku_id AS source_pk,
    ARRAY[
        'DIM_PRODUCT',
        'DIM_DEPARTMENT',
        'DIM_VENDOR',
        'dim_care_plus_sku_tier',
        'dim_product_recall_history'
    ]::text[] AS source_aliases,
    p.sku_id,
    p.brand_family,
    p.dept_code,
    d.dept_name_en,
    d.dept_type,
    p.category,
    p.subcategory,
    p.msrp_thb,
    p.msrp_tier,
    p.is_third_party,
    p.vendor_id,
    v.name_en AS vendor_name_en,
    v.category AS vendor_category,
    v.role AS vendor_role,
    p.launch_date,
    p.end_of_life_date,
    p.warranty_months,
    p.care_plus_eligible,
    coalesce(cp.care_plus_tier_count, 0) AS care_plus_tier_count,
    cp.min_care_plus_price_thb,
    cp.max_care_plus_price_thb,
    cp.max_care_plus_coverage_months,
    coalesce(r.recall_history_count, 0) AS recall_history_count,
    r.latest_recall_status,
    r.latest_recall_transition_date,
    coalesce(cp.care_plus_tiers, '[]'::jsonb) AS care_plus_tiers,
    coalesce(r.recall_history, '[]'::jsonb) AS recall_history
FROM fah_sai_lpk_core.dim_product p
LEFT JOIN fah_sai_lpk_core.dim_department d ON d.dept_code = p.dept_code
LEFT JOIN fah_sai_lpk_core.dim_vendor v ON v.vendor_id = p.vendor_id
LEFT JOIN care_plus cp ON cp.sku_id = p.sku_id
LEFT JOIN recall r ON r.sku_id = p.sku_id;

CREATE OR REPLACE VIEW fah_sai_lpk_model.policy_catalog AS
SELECT
    'DIM_POLICY_VERSION'::text AS source_table,
    pv.policy_version_id AS source_pk,
    ARRAY['DIM_POLICY_VERSION']::text[] AS source_aliases,
    'policy_version'::text AS policy_domain,
    pv.policy_version_id AS catalog_row_id,
    pv.policy_class,
    pv.policy_variable,
    pv.scope_filter,
    pv.value_numeric,
    pv.value_text,
    pv.effective_date,
    pv.end_date,
    NULL::timestamptz AS start_timestamp,
    NULL::timestamptz AS end_timestamp,
    NULL::text AS campaign_id,
    NULL::text AS promo_mechanic_id,
    NULL::text AS vendor_id,
    NULL::text AS vendor_name_en,
    NULL::text AS vendor_contract_version_id,
    NULL::integer AS contract_version_number,
    NULL::text AS position_level_code,
    NULL::text AS dept_code,
    NULL::numeric(18,2) AS amount_ceiling_thb,
    NULL::integer AS min_co_signers,
    NULL::text AS co_signer_min_position_level_code,
    pv.policy_doc_filename AS document_filename,
    NULL::text AS description_th,
    NULL::text AS description_en,
    jsonb_build_object(
        'policy_value_table_ref', pv.policy_value_table_ref
    ) AS attributes
FROM fah_sai_lpk_core.dim_policy_version pv

UNION ALL

SELECT
    'dim_signing_authority_ladder'::text AS source_table,
    l.ladder_row_id AS source_pk,
    ARRAY[
        'dim_signing_authority_ladder',
        'DIM_POLICY_VERSION',
        'DIM_POSITION_LEVEL',
        'DIM_DEPARTMENT'
    ]::text[] AS source_aliases,
    'signing_authority_ladder'::text AS policy_domain,
    l.ladder_row_id AS catalog_row_id,
    pv.policy_class,
    pv.policy_variable,
    pv.scope_filter,
    pv.value_numeric,
    pv.value_text,
    pv.effective_date,
    pv.end_date,
    NULL::timestamptz AS start_timestamp,
    NULL::timestamptz AS end_timestamp,
    NULL::text AS campaign_id,
    NULL::text AS promo_mechanic_id,
    NULL::text AS vendor_id,
    NULL::text AS vendor_name_en,
    NULL::text AS vendor_contract_version_id,
    NULL::integer AS contract_version_number,
    l.position_level_code,
    l.dept_code,
    l.amount_ceiling_thb,
    l.min_co_signers,
    l.co_signer_min_position_level_code,
    pv.policy_doc_filename AS document_filename,
    l.description_th,
    NULL::text AS description_en,
    jsonb_build_object(
        'policy_version_id', l.policy_version_id,
        'position_rank', pl.rank,
        'dept_name_en', d.dept_name_en
    ) AS attributes
FROM fah_sai_lpk_core.dim_signing_authority_ladder l
LEFT JOIN fah_sai_lpk_core.dim_policy_version pv ON pv.policy_version_id = l.policy_version_id
LEFT JOIN fah_sai_lpk_core.dim_position_level pl ON pl.position_level_code = l.position_level_code
LEFT JOIN fah_sai_lpk_core.dim_department d ON d.dept_code = l.dept_code

UNION ALL

SELECT
    'DIM_PROMO_CAMPAIGN'::text AS source_table,
    pc.campaign_id AS source_pk,
    ARRAY['DIM_PROMO_CAMPAIGN']::text[] AS source_aliases,
    'promo_campaign'::text AS policy_domain,
    pc.campaign_id AS catalog_row_id,
    'promotion'::text AS policy_class,
    'campaign'::text AS policy_variable,
    pc.scope_filter,
    NULL::numeric AS value_numeric,
    NULL::text AS value_text,
    pc.start_timestamp::date AS effective_date,
    pc.end_timestamp::date AS end_date,
    pc.start_timestamp,
    pc.end_timestamp,
    pc.campaign_id,
    NULL::text AS promo_mechanic_id,
    NULL::text AS vendor_id,
    NULL::text AS vendor_name_en,
    NULL::text AS vendor_contract_version_id,
    NULL::integer AS contract_version_number,
    NULL::text AS position_level_code,
    NULL::text AS dept_code,
    NULL::numeric(18,2) AS amount_ceiling_thb,
    NULL::integer AS min_co_signers,
    NULL::text AS co_signer_min_position_level_code,
    NULL::text AS document_filename,
    pc.description_th,
    pc.description_en,
    '{}'::jsonb AS attributes
FROM fah_sai_lpk_core.dim_promo_campaign pc

UNION ALL

SELECT
    'dim_promo_mechanic'::text AS source_table,
    pm.promo_mechanic_id AS source_pk,
    ARRAY['dim_promo_mechanic', 'DIM_PROMO_CAMPAIGN']::text[] AS source_aliases,
    'promo_mechanic'::text AS policy_domain,
    pm.promo_mechanic_id AS catalog_row_id,
    'promotion'::text AS policy_class,
    'mechanic'::text AS policy_variable,
    pc.scope_filter,
    pm.discount_value AS value_numeric,
    pm.discount_type AS value_text,
    pc.start_timestamp::date AS effective_date,
    pc.end_timestamp::date AS end_date,
    pc.start_timestamp,
    pc.end_timestamp,
    pm.campaign_id,
    pm.promo_mechanic_id,
    NULL::text AS vendor_id,
    NULL::text AS vendor_name_en,
    NULL::text AS vendor_contract_version_id,
    NULL::integer AS contract_version_number,
    NULL::text AS position_level_code,
    NULL::text AS dept_code,
    NULL::numeric(18,2) AS amount_ceiling_thb,
    NULL::integer AS min_co_signers,
    NULL::text AS co_signer_min_position_level_code,
    NULL::text AS document_filename,
    pm.description_th,
    pc.description_en,
    jsonb_build_object(
        'discount_type', pm.discount_type,
        'discount_value', pm.discount_value,
        'point_multiplier', pm.point_multiplier,
        'min_basket_thb', pm.min_basket_thb,
        'campaign_description_en', pc.description_en
    ) AS attributes
FROM fah_sai_lpk_core.dim_promo_mechanic pm
LEFT JOIN fah_sai_lpk_core.dim_promo_campaign pc ON pc.campaign_id = pm.campaign_id

UNION ALL

SELECT
    'DIM_VENDOR_CONTRACT_VERSION'::text AS source_table,
    cv.contract_version_id AS source_pk,
    ARRAY['DIM_VENDOR_CONTRACT_VERSION', 'DIM_VENDOR']::text[] AS source_aliases,
    'vendor_contract_version'::text AS policy_domain,
    cv.contract_version_id AS catalog_row_id,
    'vendor_contract'::text AS policy_class,
    'contract_version'::text AS policy_variable,
    v.category AS scope_filter,
    NULL::numeric AS value_numeric,
    cv.amendment_summary AS value_text,
    cv.effective_date,
    cv.end_date,
    NULL::timestamptz AS start_timestamp,
    NULL::timestamptz AS end_timestamp,
    NULL::text AS campaign_id,
    NULL::text AS promo_mechanic_id,
    cv.vendor_id,
    v.name_en AS vendor_name_en,
    cv.contract_version_id AS vendor_contract_version_id,
    cv.version_number AS contract_version_number,
    NULL::text AS position_level_code,
    NULL::text AS dept_code,
    NULL::numeric(18,2) AS amount_ceiling_thb,
    NULL::integer AS min_co_signers,
    NULL::text AS co_signer_min_position_level_code,
    cv.contract_pdf_filename AS document_filename,
    NULL::text AS description_th,
    cv.amendment_summary AS description_en,
    jsonb_build_object(
        'vendor_payment_terms', v.payment_terms,
        'vendor_invoice_cadence', v.invoice_cadence
    ) AS attributes
FROM fah_sai_lpk_core.dim_vendor_contract_version cv
LEFT JOIN fah_sai_lpk_core.dim_vendor v ON v.vendor_id = cv.vendor_id;

CREATE OR REPLACE VIEW fah_sai_lpk_model.document_evidence AS
SELECT
    CASE
        WHEN el.entity_link_id IS NULL THEN c.chunk_id
        ELSE c.chunk_id || ':' || el.entity_link_id::text
    END AS evidence_row_id,
    coalesce(el.linked_table, c.source_table) AS source_table,
    coalesce(el.entity_id, c.source_pk) AS source_pk,
    ARRAY[
        'fah_sai_lpk_rag.source_documents',
        'fah_sai_lpk_rag.document_chunks',
        'fah_sai_lpk_rag.chunk_embeddings',
        'fah_sai_lpk_rag.entity_links',
        'T2_DOC_INVENTORY'
    ]::text[] AS source_aliases,
    c.chunk_id,
    c.source_document_id,
    c.source_path,
    c.source_kind,
    c.artifact_id,
    c.doc_id,
    c.chunk_index,
    c.chunk_text,
    c.token_count,
    c.search_tsv,
    c.embedding_model,
    (c.embedding_model IS NOT NULL) AS has_embedding,
    c.source_table AS document_source_table,
    c.source_pk AS document_source_pk,
    el.entity_link_id,
    el.entity_type,
    el.entity_id,
    el.linked_table,
    el.linked_column,
    el.link_method,
    el.confidence,
    c.chunk_metadata,
    c.source_metadata
FROM fah_sai_lpk_rag.v_public_retrievable_chunks c
LEFT JOIN fah_sai_lpk_rag.entity_links el
  ON el.chunk_id = c.chunk_id
 AND el.is_public_safe = true;

COMMENT ON SCHEMA fah_sai_lpk_model IS
    'LLM-facing schema with eight denormalized query surfaces. Keep fah_sai_lpk_core, fah_sai_lpk_raw, fah_sai_lpk_rag, and fah_sai_lpk_audit as source-of-truth schemas; expose only this schema to Text-to-SQL prompts by default.';

COMMENT ON VIEW fah_sai_lpk_model.sales_order_360 IS
    'Model-facing sales order surface. Grain: one row per FACT_SALES.txn_id. Use for order counts, branch/channel/customer/payment status, basket/net totals, B2B AR, and sales-header questions.';
COMMENT ON VIEW fah_sai_lpk_model.sales_line_360 IS
    'Model-facing sales line surface. Grain: one row per FACT_SALES_LINE_ITEM.line_item_id. Use for SKU/product/category/vendor units, gross revenue from line_total_thb, and product-mix questions. Do not sum order totals from this line-grain view.';
COMMENT ON VIEW fah_sai_lpk_model.finance_event IS
    'Model-facing finance event surface combining FACT_BANK_TRANSACTION, FACT_REFUND_PAID, FACT_VENDOR_PAYMENT, and FACT_PAYROLL. Preserve source_table/source_pk for official citations.';
COMMENT ON VIEW fah_sai_lpk_model.customer_ops_event IS
    'Model-facing customer operations event surface combining returns, warranty claims, CS interactions, shipping, loyalty ledger, and promo redemptions.';
COMMENT ON VIEW fah_sai_lpk_model.inventory_event IS
    'Model-facing inventory event surface combining inventory movements and monthly snapshots. XFER-* related_txn_id values are internal transfer ids, not missing sales FKs.';
COMMENT ON VIEW fah_sai_lpk_model.product_catalog IS
    'Model-facing product catalog surface. Grain: one row per DIM_PRODUCT.sku_id with department, vendor, care-plus, and recall context.';
COMMENT ON VIEW fah_sai_lpk_model.policy_catalog IS
    'Model-facing policy/catalog surface for policy versions, signing authority ladder rows, promo campaigns/mechanics, and vendor contract versions.';
COMMENT ON VIEW fah_sai_lpk_model.document_evidence IS
    'Model-facing public-safe document evidence surface over RAG chunks and entity links. Does not expose unsafe audit provenance; source_table/source_pk map to official cited entities when available.';

COMMENT ON COLUMN fah_sai_lpk_model.sales_order_360.business_event_date IS
    'Canonical default date axis for sales/order period filters. If a question says year/month/quarter without naming a date column, filter on business_event_date.';
COMMENT ON COLUMN fah_sai_lpk_model.sales_line_360.business_event_date IS
    'Canonical default date axis for sales-line period filters. If a question says year/month/quarter without naming a date column, filter on business_event_date.';
COMMENT ON COLUMN fah_sai_lpk_model.finance_event.business_event_date IS
    'Canonical default date axis for finance event period filters. Use posting_date only when the question explicitly asks for posted/booked/accounting timing.';
COMMENT ON COLUMN fah_sai_lpk_model.customer_ops_event.business_event_date IS
    'Canonical default date axis for customer operations period filters. Use posting_date only when explicitly requested.';
COMMENT ON COLUMN fah_sai_lpk_model.inventory_event.business_event_date IS
    'Canonical default date axis for inventory event period filters. Use month_end_date for monthly snapshot questions that explicitly ask for month-end stock.';
COMMENT ON COLUMN fah_sai_lpk_model.policy_catalog.effective_date IS
    'Policy/catalog start date. For active-version lookup use effective_date <= target date and (end_date IS NULL OR target date < end_date) unless the question states an inclusive end-date rule.';
COMMENT ON COLUMN fah_sai_lpk_model.finance_event.source_table IS
    'Official source table for citation and routing; values include FACT_BANK_TRANSACTION, FACT_REFUND_PAID, FACT_VENDOR_PAYMENT, and FACT_PAYROLL.';
COMMENT ON COLUMN fah_sai_lpk_model.customer_ops_event.source_table IS
    'Official source table for citation and routing; values include FACT_RETURN, FACT_WARRANTY_CLAIM, FACT_CS_INTERACTION, FACT_SHIPPING, FACT_LOYALTY_LEDGER, and FACT_PROMO_REDEMPTION.';
COMMENT ON COLUMN fah_sai_lpk_model.document_evidence.has_embedding IS
    'True when this public-safe chunk has an embedding available through the underlying RAG retrieval functions.';
