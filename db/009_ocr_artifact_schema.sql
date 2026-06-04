-- FahMai OCR artifact schema.
-- Keeps OCR predictions separate from official core facts and stores render
-- provenance as audit-only metadata.

CREATE SCHEMA IF NOT EXISTS fah_sai_lpk_ocr;
CREATE SCHEMA IF NOT EXISTS fah_sai_lpk_audit;

DROP VIEW IF EXISTS fah_sai_lpk_ocr.v_ocr_bank_transaction_reconciliation;
DROP VIEW IF EXISTS fah_sai_lpk_ocr.v_ocr_warranty_reconciliation;
DROP VIEW IF EXISTS fah_sai_lpk_ocr.v_ocr_vendor_invoice_reconciliation;
DROP VIEW IF EXISTS fah_sai_lpk_ocr.v_ocr_receipt_reconciliation;
DROP VIEW IF EXISTS fah_sai_lpk_ocr.v_ocr_public_entity_link_candidates;
DROP VIEW IF EXISTS fah_sai_lpk_ocr.v_ocr_artifact_summary;

CREATE TABLE IF NOT EXISTS fah_sai_lpk_ocr.ocr_runs (
    ocr_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_name text NOT NULL,
    source_csv_path text NOT NULL,
    model_name text,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_ocr.artifact_predictions (
    prediction_id bigserial PRIMARY KEY,
    ocr_run_id uuid NOT NULL REFERENCES fah_sai_lpk_ocr.ocr_runs(ocr_run_id) ON DELETE CASCADE,
    artifact_id text NOT NULL,
    artifact_type text NOT NULL,
    pred_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    raw_pred_json text,
    pred_status text NOT NULL DEFAULT 'ok'
        CHECK (pred_status IN ('ok', 'empty', 'invalid_json', 'needs_review')),
    parse_error text,
    source_row_number integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ocr_run_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_ocr.prediction_fields (
    prediction_field_id bigserial PRIMARY KEY,
    prediction_id bigint NOT NULL REFERENCES fah_sai_lpk_ocr.artifact_predictions(prediction_id) ON DELETE CASCADE,
    field_path text NOT NULL,
    field_name text NOT NULL,
    raw_value text,
    value_jsonb jsonb,
    normalized_text text,
    normalized_date date,
    normalized_numeric numeric(18,2),
    normalized_boolean boolean,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (prediction_id, field_path)
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_ocr.ocr_receipts (
    prediction_id bigint PRIMARY KEY REFERENCES fah_sai_lpk_ocr.artifact_predictions(prediction_id) ON DELETE CASCADE,
    txn_id text,
    business_event_date date,
    branch_code text,
    branch_name_th text,
    branch_name_en text,
    customer_id text,
    employee_id text,
    channel text,
    basket_total_thb numeric(18,2),
    discount_total_thb numeric(18,2),
    net_total_thb numeric(18,2),
    shipping_charge_thb numeric(18,2),
    promo_campaign_id text,
    payment_method text,
    payment_status text,
    schema_version text,
    is_b2b boolean,
    artifact_id text,
    pos_id text,
    cash_received_thb numeric(18,2),
    change_thb numeric(18,2),
    ocr_validation_status text,
    ocr_validation_score numeric(18,2),
    ocr_validation_issues text,
    ocr_status text,
    ocr_txn_id text,
    ocr_date_iso date,
    ocr_branch_code text,
    ocr_payment_method text,
    ocr_net_total numeric(18,2),
    ocr_item_count integer,
    ocr_cache_path text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_ocr.ocr_receipt_line_items (
    prediction_id bigint NOT NULL REFERENCES fah_sai_lpk_ocr.artifact_predictions(prediction_id) ON DELETE CASCADE,
    line_item_ordinal integer NOT NULL,
    line_item_id text,
    sku_id text,
    brand_family text,
    category text,
    subcategory text,
    quantity integer,
    unit_price_thb numeric(18,2),
    line_discount_thb numeric(18,2),
    line_total_thb numeric(18,2),
    is_care_plus boolean,
    PRIMARY KEY (prediction_id, line_item_ordinal)
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_ocr.ocr_vendor_invoices (
    prediction_id bigint PRIMARY KEY REFERENCES fah_sai_lpk_ocr.artifact_predictions(prediction_id) ON DELETE CASCADE,
    payment_id text,
    vendor_id text,
    vendor_invoice_id text,
    invoice_period_start date,
    invoice_period_end date,
    paid_amount_thb numeric(18,2),
    business_event_date date
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_ocr.ocr_warranty_claims (
    prediction_id bigint PRIMARY KEY REFERENCES fah_sai_lpk_ocr.artifact_predictions(prediction_id) ON DELETE CASCADE,
    claim_id_raw text,
    claim_id_normalized text,
    business_event_date date,
    customer_id text,
    sku_id text,
    claim_reason text,
    claim_amount_thb numeric(18,2)
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_ocr.ocr_bank_statement_headers (
    prediction_id bigint PRIMARY KEY REFERENCES fah_sai_lpk_ocr.artifact_predictions(prediction_id) ON DELETE CASCADE,
    account_id text,
    bank text,
    account_number text,
    account_role text,
    currency text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_ocr.ocr_bank_statement_transactions (
    prediction_id bigint NOT NULL REFERENCES fah_sai_lpk_ocr.artifact_predictions(prediction_id) ON DELETE CASCADE,
    group_label text NOT NULL,
    sequence_in_prediction integer NOT NULL,
    bank_txn_id text NOT NULL,
    business_event_date date,
    transaction_type text,
    amount_thb numeric(18,2),
    balance_after_thb numeric(18,2),
    description text,
    account_id text,
    PRIMARY KEY (prediction_id, bank_txn_id)
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_ocr.ocr_e7_banners (
    prediction_id bigint PRIMARY KEY REFERENCES fah_sai_lpk_ocr.artifact_predictions(prediction_id) ON DELETE CASCADE,
    campaign_id text,
    description_th text,
    start_timestamp timestamptz,
    end_timestamp timestamptz,
    scope_filter text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_ocr.ocr_t3_entity_snapshots (
    prediction_id bigint PRIMARY KEY REFERENCES fah_sai_lpk_ocr.artifact_predictions(prediction_id) ON DELETE CASCADE,
    entity_kind text,
    branch_code text,
    vendor_id text,
    name_th text,
    name_en text,
    branch_type text,
    category text,
    role text,
    payment_terms text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_ocr.prediction_validations (
    validation_id bigserial PRIMARY KEY,
    prediction_id bigint NOT NULL REFERENCES fah_sai_lpk_ocr.artifact_predictions(prediction_id) ON DELETE CASCADE,
    rule_code text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    field_path text,
    raw_value text,
    message text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_audit.render_provenance_pages (
    render_provenance_page_id bigserial PRIMARY KEY,
    artifact_id text NOT NULL,
    artifact_type text NOT NULL,
    output_path text NOT NULL,
    page_kind text,
    renderer_template_id text,
    template_version text,
    source_fact_table text,
    source_row_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
    visible_fields text[] NOT NULL DEFAULT ARRAY[]::text[],
    is_public_safe boolean NOT NULL DEFAULT false,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (artifact_id, output_path)
);

COMMENT ON SCHEMA fah_sai_lpk_ocr IS
    'OCR predictions and typed OCR extraction tables. These are not official business facts.';
COMMENT ON TABLE fah_sai_lpk_ocr.artifact_predictions IS
    'One row per OCR artifact prediction from a submission CSV. Keep raw JSON for audit and parse into typed OCR tables separately.';
COMMENT ON TABLE fah_sai_lpk_ocr.prediction_fields IS
    'Generic flattened field/value index over pred_json, including nested paths such as line_items[0].sku_id.';
COMMENT ON TABLE fah_sai_lpk_audit.render_provenance_pages IS
    'Audit-only render sidecar provenance. source_row_ids are grader-only shortcuts and must not be loaded into public RAG entity links.';

CREATE INDEX IF NOT EXISTS artifact_predictions_type_status_idx
    ON fah_sai_lpk_ocr.artifact_predictions (artifact_type, pred_status);
CREATE INDEX IF NOT EXISTS artifact_predictions_pred_json_gin_idx
    ON fah_sai_lpk_ocr.artifact_predictions USING gin (pred_json);
CREATE INDEX IF NOT EXISTS prediction_fields_name_text_idx
    ON fah_sai_lpk_ocr.prediction_fields (field_name, normalized_text);
CREATE INDEX IF NOT EXISTS prediction_fields_name_date_idx
    ON fah_sai_lpk_ocr.prediction_fields (field_name, normalized_date);
CREATE INDEX IF NOT EXISTS prediction_fields_name_numeric_idx
    ON fah_sai_lpk_ocr.prediction_fields (field_name, normalized_numeric);
CREATE INDEX IF NOT EXISTS prediction_validations_prediction_idx
    ON fah_sai_lpk_ocr.prediction_validations (prediction_id);
CREATE INDEX IF NOT EXISTS prediction_validations_rule_severity_idx
    ON fah_sai_lpk_ocr.prediction_validations (rule_code, severity);

CREATE INDEX IF NOT EXISTS ocr_receipts_txn_idx
    ON fah_sai_lpk_ocr.ocr_receipts (txn_id);
CREATE INDEX IF NOT EXISTS ocr_receipts_date_idx
    ON fah_sai_lpk_ocr.ocr_receipts (business_event_date);
CREATE INDEX IF NOT EXISTS ocr_receipts_branch_idx
    ON fah_sai_lpk_ocr.ocr_receipts (branch_code);
CREATE INDEX IF NOT EXISTS ocr_receipt_line_items_line_item_idx
    ON fah_sai_lpk_ocr.ocr_receipt_line_items (line_item_id);
CREATE INDEX IF NOT EXISTS ocr_receipt_line_items_sku_idx
    ON fah_sai_lpk_ocr.ocr_receipt_line_items (sku_id);
CREATE INDEX IF NOT EXISTS ocr_vendor_invoices_invoice_idx
    ON fah_sai_lpk_ocr.ocr_vendor_invoices (vendor_invoice_id);
CREATE INDEX IF NOT EXISTS ocr_vendor_invoices_vendor_date_idx
    ON fah_sai_lpk_ocr.ocr_vendor_invoices (vendor_id, business_event_date);
CREATE INDEX IF NOT EXISTS ocr_warranty_claims_claim_idx
    ON fah_sai_lpk_ocr.ocr_warranty_claims (claim_id_normalized);
CREATE INDEX IF NOT EXISTS ocr_warranty_claims_sku_date_idx
    ON fah_sai_lpk_ocr.ocr_warranty_claims (sku_id, business_event_date);
CREATE INDEX IF NOT EXISTS ocr_bank_statement_headers_account_idx
    ON fah_sai_lpk_ocr.ocr_bank_statement_headers (account_id);
CREATE INDEX IF NOT EXISTS ocr_bank_statement_transactions_bank_txn_idx
    ON fah_sai_lpk_ocr.ocr_bank_statement_transactions (bank_txn_id);
CREATE INDEX IF NOT EXISTS ocr_bank_statement_transactions_date_idx
    ON fah_sai_lpk_ocr.ocr_bank_statement_transactions (business_event_date);
CREATE INDEX IF NOT EXISTS ocr_bank_statement_transactions_account_idx
    ON fah_sai_lpk_ocr.ocr_bank_statement_transactions (account_id);
CREATE INDEX IF NOT EXISTS ocr_e7_banners_campaign_idx
    ON fah_sai_lpk_ocr.ocr_e7_banners (campaign_id);
CREATE INDEX IF NOT EXISTS ocr_t3_entity_snapshots_branch_idx
    ON fah_sai_lpk_ocr.ocr_t3_entity_snapshots (branch_code);
CREATE INDEX IF NOT EXISTS ocr_t3_entity_snapshots_vendor_idx
    ON fah_sai_lpk_ocr.ocr_t3_entity_snapshots (vendor_id);

CREATE INDEX IF NOT EXISTS render_provenance_pages_artifact_idx
    ON fah_sai_lpk_audit.render_provenance_pages (artifact_id);
CREATE INDEX IF NOT EXISTS render_provenance_pages_source_idx
    ON fah_sai_lpk_audit.render_provenance_pages (source_fact_table);
CREATE INDEX IF NOT EXISTS render_provenance_pages_public_safe_idx
    ON fah_sai_lpk_audit.render_provenance_pages (is_public_safe);

CREATE OR REPLACE VIEW fah_sai_lpk_ocr.v_ocr_artifact_summary AS
SELECT
    r.ocr_run_id,
    r.run_name,
    p.artifact_type,
    p.pred_status,
    count(DISTINCT p.prediction_id) AS artifact_count,
    count(DISTINCT p.prediction_id) FILTER (WHERE p.pred_json = '{}'::jsonb) AS empty_json_count,
    count(v.validation_id) AS validation_count
FROM fah_sai_lpk_ocr.ocr_runs r
JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.ocr_run_id = r.ocr_run_id
LEFT JOIN fah_sai_lpk_ocr.prediction_validations v ON v.prediction_id = p.prediction_id
GROUP BY r.ocr_run_id, r.run_name, p.artifact_type, p.pred_status;

CREATE OR REPLACE VIEW fah_sai_lpk_ocr.v_ocr_receipt_reconciliation AS
SELECT
    p.ocr_run_id,
    p.artifact_id,
    p.pred_status,
    o.txn_id,
    s.txn_id IS NOT NULL AS core_found,
    o.business_event_date AS ocr_business_event_date,
    s.business_event_date AS core_business_event_date,
    o.branch_code AS ocr_branch_code,
    s.branch_code AS core_branch_code,
    o.net_total_thb AS ocr_net_total_thb,
    s.net_total_thb AS core_net_total_thb,
    o.payment_method AS ocr_payment_method,
    s.payment_method AS core_payment_method,
    (o.business_event_date IS NOT DISTINCT FROM s.business_event_date) AS date_matches,
    (o.branch_code IS NOT DISTINCT FROM s.branch_code) AS branch_matches,
    (o.net_total_thb IS NOT DISTINCT FROM s.net_total_thb) AS net_total_matches,
    (o.payment_method IS NOT DISTINCT FROM s.payment_method) AS payment_method_matches
FROM fah_sai_lpk_ocr.ocr_receipts o
JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = o.prediction_id
LEFT JOIN fah_sai_lpk_core.fact_sales s ON s.txn_id = o.txn_id;

CREATE OR REPLACE VIEW fah_sai_lpk_ocr.v_ocr_vendor_invoice_reconciliation AS
SELECT
    p.ocr_run_id,
    p.artifact_id,
    p.pred_status,
    o.vendor_invoice_id,
    vp.payment_id AS core_payment_id,
    vp.payment_id IS NOT NULL AS core_found,
    o.payment_id AS ocr_payment_id,
    o.vendor_id AS ocr_vendor_id,
    vp.vendor_id AS core_vendor_id,
    o.business_event_date AS ocr_business_event_date,
    vp.business_event_date AS core_business_event_date,
    o.paid_amount_thb AS ocr_paid_amount_thb,
    vp.paid_amount_thb AS core_paid_amount_thb,
    (o.vendor_id IS NOT DISTINCT FROM vp.vendor_id) AS vendor_matches,
    (o.business_event_date IS NOT DISTINCT FROM vp.business_event_date) AS date_matches,
    (o.paid_amount_thb IS NOT DISTINCT FROM vp.paid_amount_thb) AS paid_amount_matches
FROM fah_sai_lpk_ocr.ocr_vendor_invoices o
JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = o.prediction_id
LEFT JOIN fah_sai_lpk_core.fact_vendor_payment vp ON vp.vendor_invoice_id = o.vendor_invoice_id;

CREATE OR REPLACE VIEW fah_sai_lpk_ocr.v_ocr_warranty_reconciliation AS
SELECT
    p.ocr_run_id,
    p.artifact_id,
    p.pred_status,
    o.claim_id_raw,
    o.claim_id_normalized,
    w.claim_id IS NOT NULL AS core_found,
    o.business_event_date AS ocr_business_event_date,
    w.business_event_date AS core_business_event_date,
    o.customer_id AS ocr_customer_id,
    w.customer_id AS core_customer_id,
    o.sku_id AS ocr_sku_id,
    w.sku_id AS core_sku_id,
    o.claim_reason AS ocr_claim_reason,
    w.claim_reason AS core_claim_reason,
    o.claim_amount_thb AS ocr_claim_amount_thb,
    w.claim_amount_thb AS core_claim_amount_thb,
    (o.business_event_date IS NOT DISTINCT FROM w.business_event_date) AS date_matches,
    (o.customer_id IS NOT DISTINCT FROM w.customer_id) AS customer_matches,
    (o.sku_id IS NOT DISTINCT FROM w.sku_id) AS sku_matches,
    (o.claim_reason IS NOT DISTINCT FROM w.claim_reason) AS reason_matches,
    (o.claim_amount_thb IS NOT DISTINCT FROM w.claim_amount_thb) AS amount_matches
FROM fah_sai_lpk_ocr.ocr_warranty_claims o
JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = o.prediction_id
LEFT JOIN fah_sai_lpk_core.fact_warranty_claim w ON w.claim_id = o.claim_id_normalized;

CREATE OR REPLACE VIEW fah_sai_lpk_ocr.v_ocr_bank_transaction_reconciliation AS
SELECT
    p.ocr_run_id,
    p.artifact_id,
    p.pred_status,
    o.group_label,
    o.sequence_in_prediction,
    o.bank_txn_id,
    bt.bank_txn_id IS NOT NULL AS core_found,
    o.business_event_date AS ocr_business_event_date,
    bt.business_event_date AS core_business_event_date,
    o.account_id AS ocr_account_id,
    bt.account_id AS core_account_id,
    o.transaction_type AS ocr_transaction_type,
    bt.transaction_type AS core_transaction_type,
    o.amount_thb AS ocr_amount_thb,
    bt.amount_thb AS core_amount_thb,
    o.balance_after_thb AS ocr_balance_after_thb,
    bt.balance_after_thb AS core_balance_after_thb,
    (o.business_event_date IS NOT DISTINCT FROM bt.business_event_date) AS date_matches,
    (o.account_id IS NOT DISTINCT FROM bt.account_id) AS account_matches,
    (o.amount_thb IS NOT DISTINCT FROM bt.amount_thb) AS amount_matches,
    (o.balance_after_thb IS NOT DISTINCT FROM bt.balance_after_thb) AS balance_matches
FROM fah_sai_lpk_ocr.ocr_bank_statement_transactions o
JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = o.prediction_id
LEFT JOIN fah_sai_lpk_core.fact_bank_transaction bt ON bt.bank_txn_id = o.bank_txn_id;

CREATE OR REPLACE VIEW fah_sai_lpk_ocr.v_ocr_public_entity_link_candidates AS
SELECT
    p.ocr_run_id,
    p.artifact_id,
    'ocr_prediction'::text AS source_type,
    'sales_transaction'::text AS entity_type,
    r.txn_id AS entity_id,
    'FACT_SALES'::text AS linked_table,
    'txn_id'::text AS linked_column,
    'ocr_extracted_field'::text AS link_method,
    1.0::numeric(5,4) AS confidence,
    true AS is_public_safe,
    'Candidate link from OCR-extracted txn_id; not derived from sidecar source_row_ids.'::text AS notes
FROM fah_sai_lpk_ocr.ocr_receipts r
JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = r.prediction_id
WHERE r.txn_id IS NOT NULL
UNION ALL
SELECT
    p.ocr_run_id, p.artifact_id, 'ocr_prediction', 'vendor_invoice',
    v.vendor_invoice_id, 'FACT_VENDOR_PAYMENT', 'vendor_invoice_id',
    'ocr_extracted_field', 1.0::numeric(5,4), true,
    'Candidate link from OCR-extracted vendor_invoice_id; not derived from sidecar source_row_ids.'
FROM fah_sai_lpk_ocr.ocr_vendor_invoices v
JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = v.prediction_id
WHERE v.vendor_invoice_id IS NOT NULL
UNION ALL
SELECT
    p.ocr_run_id, p.artifact_id, 'ocr_prediction', 'warranty_claim',
    w.claim_id_normalized, 'FACT_WARRANTY_CLAIM', 'claim_id',
    'ocr_extracted_field', 1.0::numeric(5,4), true,
    'Candidate link from OCR-extracted claim_id; not derived from sidecar source_row_ids.'
FROM fah_sai_lpk_ocr.ocr_warranty_claims w
JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = w.prediction_id
WHERE w.claim_id_normalized IS NOT NULL
UNION ALL
SELECT
    p.ocr_run_id, p.artifact_id, 'ocr_prediction', 'bank_transaction',
    bt.bank_txn_id, 'FACT_BANK_TRANSACTION', 'bank_txn_id',
    'ocr_extracted_field', 1.0::numeric(5,4), true,
    'Candidate link from OCR-extracted bank_txn_id; not derived from sidecar source_row_ids.'
FROM fah_sai_lpk_ocr.ocr_bank_statement_transactions bt
JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = bt.prediction_id
WHERE bt.bank_txn_id IS NOT NULL
UNION ALL
SELECT
    p.ocr_run_id, p.artifact_id, 'ocr_prediction', 'promo_campaign',
    b.campaign_id, 'DIM_PROMO_CAMPAIGN', 'campaign_id',
    'ocr_extracted_field', 1.0::numeric(5,4), true,
    'Candidate link from OCR-extracted campaign_id; not derived from sidecar source_row_ids.'
FROM fah_sai_lpk_ocr.ocr_e7_banners b
JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = b.prediction_id
WHERE b.campaign_id IS NOT NULL
UNION ALL
SELECT
    p.ocr_run_id, p.artifact_id, 'ocr_prediction', 'branch',
    coalesce(r.branch_code, t.branch_code), 'DIM_BRANCH', 'branch_code',
    'ocr_extracted_field', 1.0::numeric(5,4), true,
    'Candidate link from OCR-extracted branch_code; not derived from sidecar source_row_ids.'
FROM fah_sai_lpk_ocr.artifact_predictions p
LEFT JOIN fah_sai_lpk_ocr.ocr_receipts r ON r.prediction_id = p.prediction_id
LEFT JOIN fah_sai_lpk_ocr.ocr_t3_entity_snapshots t ON t.prediction_id = p.prediction_id
WHERE coalesce(r.branch_code, t.branch_code) IS NOT NULL
UNION ALL
SELECT
    p.ocr_run_id, p.artifact_id, 'ocr_prediction', 'vendor',
    coalesce(v.vendor_id, t.vendor_id), 'DIM_VENDOR', 'vendor_id',
    'ocr_extracted_field', 1.0::numeric(5,4), true,
    'Candidate link from OCR-extracted vendor_id; not derived from sidecar source_row_ids.'
FROM fah_sai_lpk_ocr.artifact_predictions p
LEFT JOIN fah_sai_lpk_ocr.ocr_vendor_invoices v ON v.prediction_id = p.prediction_id
LEFT JOIN fah_sai_lpk_ocr.ocr_t3_entity_snapshots t ON t.prediction_id = p.prediction_id
WHERE coalesce(v.vendor_id, t.vendor_id) IS NOT NULL;
