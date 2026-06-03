-- FahMai model/RAG database schema.
-- PostgreSQL + pgvector, designed for official CSV ingestion plus public-safe
-- document/OCR retrieval. Official bundle files are not modified.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS fah_sai_lpk_raw;
CREATE SCHEMA IF NOT EXISTS fah_sai_lpk_core;
CREATE SCHEMA IF NOT EXISTS fah_sai_lpk_rag;
CREATE SCHEMA IF NOT EXISTS fah_sai_lpk_mart;
CREATE SCHEMA IF NOT EXISTS fah_sai_lpk_audit;

-- ---------------------------------------------------------------------------
-- Raw landing tables
-- ---------------------------------------------------------------------------
-- Raw tables intentionally keep all CSV fields as text and use lower-case table
-- names. They are a direct landing layer before typed transformation to fah_sai_lpk_core.

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.dim_bank_account (
    account_id text,
    bank text,
    account_number text,
    account_role text,
    associated_branch_code text,
    currency text,
    opening_balance_thb text,
    statement_cadence text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.dim_branch (
    branch_code text,
    name_th text,
    name_en text,
    branch_type text,
    is_service_center text,
    retail_floor_coefficient text,
    traffic_share_pct text,
    employee_headcount_share_pct text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.dim_care_plus_sku_tier (
    tier_row_id text,
    policy_version_id text,
    sku_id text,
    sku_category text,
    care_plus_price_thb text,
    coverage_months text,
    description_th text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.dim_customer (
    customer_id text,
    first_name_th text,
    last_name_th text,
    first_name_en text,
    last_name_en text,
    email text,
    phone text,
    province text,
    region text,
    age text,
    gender text,
    signup_date text,
    customer_type text,
    b2b_subtype text,
    account_manager_id text,
    payment_terms text,
    loyalty_tier text,
    channel_pref text,
    uses_line_oa text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.dim_date (
    date_iso text,
    date_be_string text,
    day_of_week text,
    is_thai_public_holiday text,
    holiday_name text,
    fiscal_year text,
    fiscal_quarter text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.dim_department (
    dept_code text,
    dept_name_th text,
    dept_name_en text,
    dept_type text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.dim_employee (
    employee_id text,
    first_name_th text,
    last_name_th text,
    first_name_en text,
    last_name_en text,
    email text,
    phone text,
    branch_code text,
    dept_code text,
    section text,
    unit text,
    position_title text,
    position_level text,
    reports_to_employee_id text,
    hire_date text,
    termination_date text,
    termination_reason text,
    status text,
    employment_type text,
    is_canon_leader text,
    canon_role_label text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.dim_policy_version (
    policy_version_id text,
    policy_class text,
    policy_variable text,
    scope_filter text,
    value_numeric text,
    value_text text,
    policy_value_table_ref text,
    effective_date text,
    end_date text,
    policy_doc_filename text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.dim_position_level (
    position_level_code text,
    rank text,
    default_signing_authority_thb text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.dim_product (
    sku_id text,
    brand_family text,
    dept_code text,
    category text,
    subcategory text,
    msrp_thb text,
    msrp_tier text,
    is_third_party text,
    vendor_id text,
    launch_date text,
    end_of_life_date text,
    warranty_months text,
    care_plus_eligible text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.dim_product_recall_history (
    history_id text,
    sku_id text,
    status text,
    transition_date text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.dim_promo_campaign (
    campaign_id text,
    start_timestamp text,
    end_timestamp text,
    scope_filter text,
    description_th text,
    description_en text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.dim_promo_mechanic (
    promo_mechanic_id text,
    campaign_id text,
    discount_type text,
    discount_value text,
    point_multiplier text,
    min_basket_thb text,
    description_th text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.dim_signing_authority_ladder (
    ladder_row_id text,
    policy_version_id text,
    position_level_code text,
    dept_code text,
    amount_ceiling_thb text,
    min_co_signers text,
    co_signer_min_position_level_code text,
    description_th text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.dim_vendor (
    vendor_id text,
    name_th text,
    name_en text,
    category text,
    role text,
    payment_terms text,
    invoice_cadence text,
    is_partner_brand text,
    is_component_supplier text,
    start_date text,
    end_date text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.dim_vendor_contract_version (
    contract_version_id text,
    vendor_id text,
    version_number text,
    effective_date text,
    end_date text,
    contract_pdf_filename text,
    amendment_summary text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.fact_bank_transaction (
    bank_txn_id text,
    business_event_date text,
    posting_date text,
    effective_date text,
    as_of_date text,
    account_id text,
    transaction_type text,
    counterparty text,
    related_entity_id text,
    related_entity_table text,
    amount_thb text,
    balance_after_thb text,
    description text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.fact_cs_interaction (
    cs_interaction_id text,
    business_event_date text,
    posting_date text,
    effective_date text,
    as_of_date text,
    customer_id text,
    employee_id text,
    branch_code text,
    channel text,
    interaction_type text,
    resolution_type text,
    related_refund_id text,
    related_warranty_claim_id text,
    chat_session_id text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.fact_inventory_monthly_snapshot (
    snapshot_id text,
    business_event_date text,
    posting_date text,
    effective_date text,
    as_of_date text,
    month_end_date text,
    sku_id text,
    branch_code text,
    closing_units text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.fact_inventory_movement (
    movement_id text,
    business_event_date text,
    posting_date text,
    effective_date text,
    as_of_date text,
    sku_id text,
    branch_code text,
    movement_type text,
    quantity text,
    related_txn_id text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.fact_loyalty_ledger (
    ledger_id text,
    business_event_date text,
    posting_date text,
    effective_date text,
    as_of_date text,
    customer_id text,
    txn_id text,
    event_type text,
    points_delta text,
    resulting_balance_points text,
    resulting_tier text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.fact_payroll (
    payroll_id text,
    business_event_date text,
    posting_date text,
    effective_date text,
    as_of_date text,
    employee_id text,
    pay_period_start text,
    pay_period_end text,
    gross_pay_thb text,
    tax_deduction_thb text,
    social_security_thb text,
    net_pay_thb text,
    bank_txn_id text,
    employment_status_at_period_end text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.fact_promo_redemption (
    redemption_id text,
    business_event_date text,
    posting_date text,
    effective_date text,
    as_of_date text,
    txn_id text,
    customer_id text,
    campaign_id text,
    discount_applied_thb text,
    channel text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.fact_refund_paid (
    refund_id text,
    business_event_date text,
    posting_date text,
    effective_date text,
    as_of_date text,
    return_id text,
    cs_interaction_id text,
    customer_id text,
    refund_amount_thb text,
    request_date text,
    approver_employee_id text,
    cosig_employee_id text,
    bank_txn_id text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.fact_return (
    return_id text,
    business_event_date text,
    posting_date text,
    effective_date text,
    as_of_date text,
    original_txn_id text,
    line_item_id text,
    sku_id text,
    branch_code text,
    customer_id text,
    return_reason text,
    approved_by_employee_id text,
    days_since_purchase text,
    return_amount_thb text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.fact_sales (
    txn_id text,
    business_event_date text,
    posting_date text,
    effective_date text,
    as_of_date text,
    branch_code text,
    customer_id text,
    employee_id text,
    channel text,
    basket_total_thb text,
    discount_total_thb text,
    net_total_thb text,
    shipping_charge_thb text,
    shipping_method text,
    promo_campaign_id text,
    payment_method text,
    payment_status text,
    payment_due_date text,
    payment_received_date text,
    settlement_bank_txn_id text,
    web_log_line_id text,
    schema_version text,
    is_b2b text,
    retry_idempotency_marker text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.fact_sales_line_item (
    line_item_id text,
    business_event_date text,
    posting_date text,
    effective_date text,
    as_of_date text,
    txn_id text,
    sku_id text,
    quantity text,
    unit_price_thb text,
    line_discount_thb text,
    line_total_thb text,
    is_care_plus text,
    pos_log_line_id text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.fact_shipping (
    shipping_id text,
    business_event_date text,
    posting_date text,
    effective_date text,
    as_of_date text,
    txn_id text,
    vendor_id text,
    tracking_number text,
    origin_branch_code text,
    destination_province text,
    confirmation_status text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.fact_vendor_payment (
    payment_id text,
    business_event_date text,
    posting_date text,
    effective_date text,
    as_of_date text,
    vendor_id text,
    vendor_invoice_id text,
    invoice_period_start text,
    invoice_period_end text,
    paid_amount_thb text,
    vendor_contract_version_id text,
    request_date text,
    signing_employee_id text,
    cosig_employee_id text,
    bank_txn_id text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.fact_warranty_claim (
    claim_id text,
    business_event_date text,
    posting_date text,
    effective_date text,
    as_of_date text,
    customer_id text,
    sku_id text,
    original_txn_id text,
    claim_reason text,
    claim_amount_thb text,
    routing_destination text,
    resolution_type text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_raw.t2_doc_inventory (
    doc_id text,
    doc_kind text,
    template_name text,
    body_source text,
    issue_date text,
    source_table text,
    source_pk text
);

-- ---------------------------------------------------------------------------
-- Core typed official tables
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.dim_branch (
    branch_code text PRIMARY KEY,
    name_th text,
    name_en text,
    branch_type text,
    is_service_center boolean,
    retail_floor_coefficient numeric(18,6),
    traffic_share_pct numeric(18,6),
    employee_headcount_share_pct numeric(18,6)
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.dim_department (
    dept_code text PRIMARY KEY,
    dept_name_th text,
    dept_name_en text,
    dept_type text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.dim_position_level (
    position_level_code text PRIMARY KEY,
    rank integer,
    default_signing_authority_thb numeric(18,2)
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.dim_date (
    date_iso date PRIMARY KEY,
    date_be_string text,
    day_of_week integer,
    is_thai_public_holiday boolean,
    holiday_name text,
    fiscal_year integer,
    fiscal_quarter integer
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.dim_vendor (
    vendor_id text PRIMARY KEY,
    name_th text,
    name_en text,
    category text,
    role text,
    payment_terms text,
    invoice_cadence text,
    is_partner_brand boolean,
    is_component_supplier boolean,
    start_date date,
    end_date date
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.dim_bank_account (
    account_id text PRIMARY KEY,
    bank text,
    account_number text,
    account_role text,
    associated_branch_code text REFERENCES fah_sai_lpk_core.dim_branch(branch_code) DEFERRABLE INITIALLY DEFERRED,
    currency text,
    opening_balance_thb numeric(18,2),
    statement_cadence text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.dim_employee (
    employee_id text PRIMARY KEY,
    first_name_th text,
    last_name_th text,
    first_name_en text,
    last_name_en text,
    email text,
    phone text,
    branch_code text REFERENCES fah_sai_lpk_core.dim_branch(branch_code) DEFERRABLE INITIALLY DEFERRED,
    dept_code text REFERENCES fah_sai_lpk_core.dim_department(dept_code) DEFERRABLE INITIALLY DEFERRED,
    section text,
    unit text,
    position_title text,
    position_level text REFERENCES fah_sai_lpk_core.dim_position_level(position_level_code) DEFERRABLE INITIALLY DEFERRED,
    reports_to_employee_id text REFERENCES fah_sai_lpk_core.dim_employee(employee_id) DEFERRABLE INITIALLY DEFERRED,
    hire_date date,
    termination_date date,
    termination_reason text,
    status text,
    employment_type text,
    is_canon_leader boolean,
    canon_role_label text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.dim_customer (
    customer_id text PRIMARY KEY,
    first_name_th text,
    last_name_th text,
    first_name_en text,
    last_name_en text,
    email text,
    phone text,
    province text,
    region text,
    age integer,
    gender text,
    signup_date date,
    customer_type text,
    b2b_subtype text,
    account_manager_id text REFERENCES fah_sai_lpk_core.dim_employee(employee_id) DEFERRABLE INITIALLY DEFERRED,
    payment_terms text,
    loyalty_tier text,
    channel_pref text,
    uses_line_oa boolean
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.dim_policy_version (
    policy_version_id text PRIMARY KEY,
    policy_class text,
    policy_variable text,
    scope_filter text,
    value_numeric numeric(18,4),
    value_text text,
    policy_value_table_ref text,
    effective_date date,
    end_date date,
    policy_doc_filename text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.dim_product (
    sku_id text PRIMARY KEY,
    brand_family text,
    dept_code text REFERENCES fah_sai_lpk_core.dim_department(dept_code) DEFERRABLE INITIALLY DEFERRED,
    category text,
    subcategory text,
    msrp_thb numeric(18,2),
    msrp_tier text,
    is_third_party boolean,
    vendor_id text REFERENCES fah_sai_lpk_core.dim_vendor(vendor_id) DEFERRABLE INITIALLY DEFERRED,
    launch_date date,
    end_of_life_date date,
    warranty_months integer,
    care_plus_eligible boolean
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.dim_promo_campaign (
    campaign_id text PRIMARY KEY,
    start_timestamp timestamptz,
    end_timestamp timestamptz,
    scope_filter text,
    description_th text,
    description_en text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.dim_vendor_contract_version (
    contract_version_id text PRIMARY KEY,
    vendor_id text REFERENCES fah_sai_lpk_core.dim_vendor(vendor_id) DEFERRABLE INITIALLY DEFERRED,
    version_number integer,
    effective_date date,
    end_date date,
    contract_pdf_filename text,
    amendment_summary text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.dim_care_plus_sku_tier (
    tier_row_id text PRIMARY KEY,
    policy_version_id text REFERENCES fah_sai_lpk_core.dim_policy_version(policy_version_id) DEFERRABLE INITIALLY DEFERRED,
    sku_id text REFERENCES fah_sai_lpk_core.dim_product(sku_id) DEFERRABLE INITIALLY DEFERRED,
    sku_category text,
    care_plus_price_thb numeric(18,2),
    coverage_months integer,
    description_th text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.dim_product_recall_history (
    history_id text PRIMARY KEY,
    sku_id text REFERENCES fah_sai_lpk_core.dim_product(sku_id) DEFERRABLE INITIALLY DEFERRED,
    status text,
    transition_date date
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.dim_promo_mechanic (
    promo_mechanic_id text PRIMARY KEY,
    campaign_id text REFERENCES fah_sai_lpk_core.dim_promo_campaign(campaign_id) DEFERRABLE INITIALLY DEFERRED,
    discount_type text,
    discount_value numeric(18,4),
    point_multiplier numeric(18,4),
    min_basket_thb numeric(18,2),
    description_th text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.dim_signing_authority_ladder (
    ladder_row_id text PRIMARY KEY,
    policy_version_id text REFERENCES fah_sai_lpk_core.dim_policy_version(policy_version_id) DEFERRABLE INITIALLY DEFERRED,
    position_level_code text REFERENCES fah_sai_lpk_core.dim_position_level(position_level_code) DEFERRABLE INITIALLY DEFERRED,
    dept_code text REFERENCES fah_sai_lpk_core.dim_department(dept_code) DEFERRABLE INITIALLY DEFERRED,
    amount_ceiling_thb numeric(18,2),
    min_co_signers integer,
    co_signer_min_position_level_code text REFERENCES fah_sai_lpk_core.dim_position_level(position_level_code) DEFERRABLE INITIALLY DEFERRED,
    description_th text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.fact_bank_transaction (
    bank_txn_id text PRIMARY KEY,
    business_event_date date,
    posting_date date,
    effective_date date,
    as_of_date date,
    account_id text REFERENCES fah_sai_lpk_core.dim_bank_account(account_id) DEFERRABLE INITIALLY DEFERRED,
    transaction_type text,
    counterparty text,
    related_entity_id text,
    related_entity_table text,
    amount_thb numeric(18,2),
    balance_after_thb numeric(18,2),
    description text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.fact_sales (
    txn_id text PRIMARY KEY,
    business_event_date date,
    posting_date date,
    effective_date date,
    as_of_date date,
    branch_code text REFERENCES fah_sai_lpk_core.dim_branch(branch_code) DEFERRABLE INITIALLY DEFERRED,
    customer_id text REFERENCES fah_sai_lpk_core.dim_customer(customer_id) DEFERRABLE INITIALLY DEFERRED,
    employee_id text REFERENCES fah_sai_lpk_core.dim_employee(employee_id) DEFERRABLE INITIALLY DEFERRED,
    channel text,
    basket_total_thb numeric(18,2),
    discount_total_thb numeric(18,2),
    net_total_thb numeric(18,2),
    shipping_charge_thb numeric(18,2),
    shipping_method text,
    promo_campaign_id text REFERENCES fah_sai_lpk_core.dim_promo_campaign(campaign_id) DEFERRABLE INITIALLY DEFERRED,
    payment_method text,
    payment_status text,
    payment_due_date date,
    payment_received_date date,
    settlement_bank_txn_id text REFERENCES fah_sai_lpk_core.fact_bank_transaction(bank_txn_id) DEFERRABLE INITIALLY DEFERRED,
    web_log_line_id text,
    schema_version text,
    is_b2b boolean,
    retry_idempotency_marker text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.fact_sales_line_item (
    line_item_id text PRIMARY KEY,
    business_event_date date,
    posting_date date,
    effective_date date,
    as_of_date date,
    txn_id text REFERENCES fah_sai_lpk_core.fact_sales(txn_id) DEFERRABLE INITIALLY DEFERRED,
    sku_id text REFERENCES fah_sai_lpk_core.dim_product(sku_id) DEFERRABLE INITIALLY DEFERRED,
    quantity integer,
    unit_price_thb numeric(18,2),
    line_discount_thb numeric(18,2),
    line_total_thb numeric(18,2),
    is_care_plus boolean,
    pos_log_line_id text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.fact_payroll (
    payroll_id text PRIMARY KEY,
    business_event_date date,
    posting_date date,
    effective_date date,
    as_of_date date,
    employee_id text REFERENCES fah_sai_lpk_core.dim_employee(employee_id) DEFERRABLE INITIALLY DEFERRED,
    pay_period_start date,
    pay_period_end date,
    gross_pay_thb numeric(18,2),
    tax_deduction_thb numeric(18,2),
    social_security_thb numeric(18,2),
    net_pay_thb numeric(18,2),
    bank_txn_id text REFERENCES fah_sai_lpk_core.fact_bank_transaction(bank_txn_id) DEFERRABLE INITIALLY DEFERRED,
    employment_status_at_period_end text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.fact_loyalty_ledger (
    ledger_id text PRIMARY KEY,
    business_event_date date,
    posting_date date,
    effective_date date,
    as_of_date date,
    customer_id text REFERENCES fah_sai_lpk_core.dim_customer(customer_id) DEFERRABLE INITIALLY DEFERRED,
    txn_id text REFERENCES fah_sai_lpk_core.fact_sales(txn_id) DEFERRABLE INITIALLY DEFERRED,
    event_type text,
    points_delta integer,
    resulting_balance_points integer,
    resulting_tier text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.fact_promo_redemption (
    redemption_id text PRIMARY KEY,
    business_event_date date,
    posting_date date,
    effective_date date,
    as_of_date date,
    txn_id text REFERENCES fah_sai_lpk_core.fact_sales(txn_id) DEFERRABLE INITIALLY DEFERRED,
    customer_id text REFERENCES fah_sai_lpk_core.dim_customer(customer_id) DEFERRABLE INITIALLY DEFERRED,
    campaign_id text REFERENCES fah_sai_lpk_core.dim_promo_campaign(campaign_id) DEFERRABLE INITIALLY DEFERRED,
    discount_applied_thb numeric(18,2),
    channel text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.fact_shipping (
    shipping_id text PRIMARY KEY,
    business_event_date date,
    posting_date date,
    effective_date date,
    as_of_date date,
    txn_id text REFERENCES fah_sai_lpk_core.fact_sales(txn_id) DEFERRABLE INITIALLY DEFERRED,
    vendor_id text REFERENCES fah_sai_lpk_core.dim_vendor(vendor_id) DEFERRABLE INITIALLY DEFERRED,
    tracking_number text,
    origin_branch_code text REFERENCES fah_sai_lpk_core.dim_branch(branch_code) DEFERRABLE INITIALLY DEFERRED,
    destination_province text,
    confirmation_status text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.fact_inventory_monthly_snapshot (
    snapshot_id text PRIMARY KEY,
    business_event_date date,
    posting_date date,
    effective_date date,
    as_of_date date,
    month_end_date date,
    sku_id text REFERENCES fah_sai_lpk_core.dim_product(sku_id) DEFERRABLE INITIALLY DEFERRED,
    branch_code text REFERENCES fah_sai_lpk_core.dim_branch(branch_code) DEFERRABLE INITIALLY DEFERRED,
    closing_units integer
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.fact_inventory_movement (
    movement_id text PRIMARY KEY,
    business_event_date date,
    posting_date date,
    effective_date date,
    as_of_date date,
    sku_id text REFERENCES fah_sai_lpk_core.dim_product(sku_id) DEFERRABLE INITIALLY DEFERRED,
    branch_code text REFERENCES fah_sai_lpk_core.dim_branch(branch_code) DEFERRABLE INITIALLY DEFERRED,
    movement_type text,
    quantity integer,
    related_txn_id text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.fact_warranty_claim (
    claim_id text PRIMARY KEY,
    business_event_date date,
    posting_date date,
    effective_date date,
    as_of_date date,
    customer_id text REFERENCES fah_sai_lpk_core.dim_customer(customer_id) DEFERRABLE INITIALLY DEFERRED,
    sku_id text REFERENCES fah_sai_lpk_core.dim_product(sku_id) DEFERRABLE INITIALLY DEFERRED,
    original_txn_id text REFERENCES fah_sai_lpk_core.fact_sales(txn_id) DEFERRABLE INITIALLY DEFERRED,
    claim_reason text,
    claim_amount_thb numeric(18,2),
    routing_destination text,
    resolution_type text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.fact_return (
    return_id text PRIMARY KEY,
    business_event_date date,
    posting_date date,
    effective_date date,
    as_of_date date,
    original_txn_id text REFERENCES fah_sai_lpk_core.fact_sales(txn_id) DEFERRABLE INITIALLY DEFERRED,
    line_item_id text REFERENCES fah_sai_lpk_core.fact_sales_line_item(line_item_id) DEFERRABLE INITIALLY DEFERRED,
    sku_id text REFERENCES fah_sai_lpk_core.dim_product(sku_id) DEFERRABLE INITIALLY DEFERRED,
    branch_code text REFERENCES fah_sai_lpk_core.dim_branch(branch_code) DEFERRABLE INITIALLY DEFERRED,
    customer_id text REFERENCES fah_sai_lpk_core.dim_customer(customer_id) DEFERRABLE INITIALLY DEFERRED,
    return_reason text,
    approved_by_employee_id text REFERENCES fah_sai_lpk_core.dim_employee(employee_id) DEFERRABLE INITIALLY DEFERRED,
    days_since_purchase integer,
    return_amount_thb numeric(18,2)
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.fact_cs_interaction (
    cs_interaction_id text PRIMARY KEY,
    business_event_date date,
    posting_date date,
    effective_date date,
    as_of_date date,
    customer_id text REFERENCES fah_sai_lpk_core.dim_customer(customer_id) DEFERRABLE INITIALLY DEFERRED,
    employee_id text REFERENCES fah_sai_lpk_core.dim_employee(employee_id) DEFERRABLE INITIALLY DEFERRED,
    branch_code text REFERENCES fah_sai_lpk_core.dim_branch(branch_code) DEFERRABLE INITIALLY DEFERRED,
    channel text,
    interaction_type text,
    resolution_type text,
    related_refund_id text,
    related_warranty_claim_id text REFERENCES fah_sai_lpk_core.fact_warranty_claim(claim_id) DEFERRABLE INITIALLY DEFERRED,
    chat_session_id text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.fact_refund_paid (
    refund_id text PRIMARY KEY,
    business_event_date date,
    posting_date date,
    effective_date date,
    as_of_date date,
    return_id text REFERENCES fah_sai_lpk_core.fact_return(return_id) DEFERRABLE INITIALLY DEFERRED,
    cs_interaction_id text REFERENCES fah_sai_lpk_core.fact_cs_interaction(cs_interaction_id) DEFERRABLE INITIALLY DEFERRED,
    customer_id text REFERENCES fah_sai_lpk_core.dim_customer(customer_id) DEFERRABLE INITIALLY DEFERRED,
    refund_amount_thb numeric(18,2),
    request_date date,
    approver_employee_id text REFERENCES fah_sai_lpk_core.dim_employee(employee_id) DEFERRABLE INITIALLY DEFERRED,
    cosig_employee_id text REFERENCES fah_sai_lpk_core.dim_employee(employee_id) DEFERRABLE INITIALLY DEFERRED,
    bank_txn_id text REFERENCES fah_sai_lpk_core.fact_bank_transaction(bank_txn_id) DEFERRABLE INITIALLY DEFERRED
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fact_cs_interaction_related_refund_fk'
          AND conrelid = 'fah_sai_lpk_core.fact_cs_interaction'::regclass
    ) THEN
        ALTER TABLE fah_sai_lpk_core.fact_cs_interaction
            ADD CONSTRAINT fact_cs_interaction_related_refund_fk
            FOREIGN KEY (related_refund_id)
            REFERENCES fah_sai_lpk_core.fact_refund_paid(refund_id)
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.fact_vendor_payment (
    payment_id text PRIMARY KEY,
    business_event_date date,
    posting_date date,
    effective_date date,
    as_of_date date,
    vendor_id text REFERENCES fah_sai_lpk_core.dim_vendor(vendor_id) DEFERRABLE INITIALLY DEFERRED,
    vendor_invoice_id text,
    invoice_period_start date,
    invoice_period_end date,
    paid_amount_thb numeric(18,2),
    vendor_contract_version_id text REFERENCES fah_sai_lpk_core.dim_vendor_contract_version(contract_version_id) DEFERRABLE INITIALLY DEFERRED,
    request_date date,
    signing_employee_id text REFERENCES fah_sai_lpk_core.dim_employee(employee_id) DEFERRABLE INITIALLY DEFERRED,
    cosig_employee_id text REFERENCES fah_sai_lpk_core.dim_employee(employee_id) DEFERRABLE INITIALLY DEFERRED,
    bank_txn_id text REFERENCES fah_sai_lpk_core.fact_bank_transaction(bank_txn_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_core.t2_doc_inventory (
    doc_id text PRIMARY KEY,
    doc_kind text,
    template_name text,
    body_source text,
    issue_date date,
    source_table text,
    source_pk text
);

COMMENT ON COLUMN fah_sai_lpk_core.fact_bank_transaction.related_entity_table IS
    'Polymorphic source discriminator. FACT_SALES_DEPOSIT_BATCH is intentionally virtual, not an official core table.';
COMMENT ON COLUMN fah_sai_lpk_core.fact_inventory_movement.related_txn_id IS
    'Polymorphic id: TXN-* can point to sales; XFER-* is an internal transfer id.';
COMMENT ON TABLE fah_sai_lpk_core.t2_doc_inventory IS
    'Official document inventory. source_table/source_pk are lineage hints, not normal flattening FKs.';

-- ---------------------------------------------------------------------------
-- RAG schema
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fah_sai_lpk_rag.source_documents (
    source_document_id text PRIMARY KEY,
    source_path text NOT NULL UNIQUE,
    source_kind text NOT NULL,
    artifact_id text,
    doc_id text,
    source_table text,
    source_pk text,
    issue_date date,
    is_public_safe boolean NOT NULL DEFAULT true,
    safety_tier text NOT NULL DEFAULT 'official',
    content_sha256 text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_rag.document_chunks (
    chunk_id text PRIMARY KEY,
    source_document_id text NOT NULL REFERENCES fah_sai_lpk_rag.source_documents(source_document_id) ON DELETE CASCADE,
    chunk_index integer NOT NULL,
    chunk_text text NOT NULL,
    token_count integer,
    char_start integer,
    char_end integer,
    language_hint text,
    is_public_safe boolean NOT NULL DEFAULT true,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(chunk_text, ''))) STORED,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_rag.chunk_embeddings (
    chunk_id text PRIMARY KEY REFERENCES fah_sai_lpk_rag.document_chunks(chunk_id) ON DELETE CASCADE,
    embedding_model text NOT NULL DEFAULT 'Qwen/Qwen3-Embedding-8B',
    embedding vector(4096) NOT NULL,
    embedding_created_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_rag.entity_links (
    entity_link_id bigserial PRIMARY KEY,
    source_document_id text REFERENCES fah_sai_lpk_rag.source_documents(source_document_id) ON DELETE CASCADE,
    chunk_id text REFERENCES fah_sai_lpk_rag.document_chunks(chunk_id) ON DELETE CASCADE,
    artifact_id text,
    source_path text,
    source_type text,
    entity_type text NOT NULL,
    entity_id text NOT NULL,
    linked_table text NOT NULL,
    linked_column text NOT NULL,
    link_method text NOT NULL,
    confidence numeric(5,4) NOT NULL DEFAULT 1.0,
    is_public_safe boolean NOT NULL DEFAULT true,
    notes text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE fah_sai_lpk_rag.entity_links IS
    'Public-safe links from text/artifacts/chunks to official core entities. Do not load audit-only provenance here unless data governance explicitly approves it.';

-- ---------------------------------------------------------------------------
-- Audit/provenance schema
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fah_sai_lpk_audit.ingestion_runs (
    ingestion_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_bundle_path text NOT NULL,
    ingestion_kind text NOT NULL,
    status text NOT NULL DEFAULT 'running',
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    row_counts jsonb NOT NULL DEFAULT '{}'::jsonb,
    notes text
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_audit.source_safety_flags (
    safety_flag_id bigserial PRIMARY KEY,
    source_path text NOT NULL,
    source_type text,
    is_public_safe boolean NOT NULL,
    reason text NOT NULL,
    decided_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_audit.provenance_entity_links (
    provenance_link_id bigserial PRIMARY KEY,
    artifact_id text,
    source_path text NOT NULL,
    source_type text,
    entity_type text,
    entity_id text,
    linked_table text,
    linked_column text,
    link_method text,
    confidence numeric(5,4),
    is_public_safe boolean NOT NULL DEFAULT false,
    notes text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_audit.retrieval_traces (
    retrieval_trace_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id text,
    query_text text NOT NULL,
    retriever_version text,
    top_k integer,
    result_chunk_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
    used_public_safe_only boolean NOT NULL DEFAULT true,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS dim_bank_account_branch_idx ON fah_sai_lpk_core.dim_bank_account (associated_branch_code);
CREATE INDEX IF NOT EXISTS dim_employee_branch_idx ON fah_sai_lpk_core.dim_employee (branch_code);
CREATE INDEX IF NOT EXISTS dim_employee_dept_idx ON fah_sai_lpk_core.dim_employee (dept_code);
CREATE INDEX IF NOT EXISTS dim_customer_account_manager_idx ON fah_sai_lpk_core.dim_customer (account_manager_id);
CREATE INDEX IF NOT EXISTS dim_product_vendor_idx ON fah_sai_lpk_core.dim_product (vendor_id);
CREATE INDEX IF NOT EXISTS dim_product_dept_idx ON fah_sai_lpk_core.dim_product (dept_code);
CREATE INDEX IF NOT EXISTS dim_vendor_contract_vendor_date_idx ON fah_sai_lpk_core.dim_vendor_contract_version (vendor_id, effective_date, end_date);
CREATE INDEX IF NOT EXISTS dim_policy_version_class_date_idx ON fah_sai_lpk_core.dim_policy_version (policy_class, policy_variable, effective_date, end_date);

CREATE INDEX IF NOT EXISTS fact_bank_transaction_account_date_idx ON fah_sai_lpk_core.fact_bank_transaction (account_id, business_event_date);
CREATE INDEX IF NOT EXISTS fact_bank_transaction_related_idx ON fah_sai_lpk_core.fact_bank_transaction (related_entity_table, related_entity_id);
CREATE INDEX IF NOT EXISTS fact_sales_date_branch_idx ON fah_sai_lpk_core.fact_sales (business_event_date, branch_code);
CREATE INDEX IF NOT EXISTS fact_sales_customer_idx ON fah_sai_lpk_core.fact_sales (customer_id);
CREATE INDEX IF NOT EXISTS fact_sales_payment_method_idx ON fah_sai_lpk_core.fact_sales (payment_method);
CREATE INDEX IF NOT EXISTS fact_sales_settlement_bank_txn_idx ON fah_sai_lpk_core.fact_sales (settlement_bank_txn_id);
CREATE INDEX IF NOT EXISTS fact_sales_line_txn_idx ON fah_sai_lpk_core.fact_sales_line_item (txn_id);
CREATE INDEX IF NOT EXISTS fact_sales_line_sku_idx ON fah_sai_lpk_core.fact_sales_line_item (sku_id);
CREATE INDEX IF NOT EXISTS fact_return_original_txn_idx ON fah_sai_lpk_core.fact_return (original_txn_id);
CREATE INDEX IF NOT EXISTS fact_refund_return_idx ON fah_sai_lpk_core.fact_refund_paid (return_id);
CREATE INDEX IF NOT EXISTS fact_vendor_payment_vendor_idx ON fah_sai_lpk_core.fact_vendor_payment (vendor_id);
CREATE INDEX IF NOT EXISTS fact_vendor_payment_contract_idx ON fah_sai_lpk_core.fact_vendor_payment (vendor_contract_version_id);
CREATE INDEX IF NOT EXISTS fact_inventory_movement_related_txn_idx ON fah_sai_lpk_core.fact_inventory_movement (related_txn_id);
CREATE INDEX IF NOT EXISTS fact_loyalty_ledger_txn_idx ON fah_sai_lpk_core.fact_loyalty_ledger (txn_id);
CREATE INDEX IF NOT EXISTS fact_promo_redemption_txn_idx ON fah_sai_lpk_core.fact_promo_redemption (txn_id);

CREATE INDEX IF NOT EXISTS source_documents_public_safe_idx ON fah_sai_lpk_rag.source_documents (is_public_safe, source_kind);
CREATE INDEX IF NOT EXISTS document_chunks_source_idx ON fah_sai_lpk_rag.document_chunks (source_document_id, chunk_index);
CREATE INDEX IF NOT EXISTS document_chunks_public_safe_idx ON fah_sai_lpk_rag.document_chunks (is_public_safe);
CREATE INDEX IF NOT EXISTS document_chunks_search_tsv_idx ON fah_sai_lpk_rag.document_chunks USING gin (search_tsv);
DO $$
BEGIN
    BEGIN
        CREATE INDEX IF NOT EXISTS chunk_embeddings_embedding_hnsw_idx
            ON fah_sai_lpk_rag.chunk_embeddings USING hnsw (embedding vector_cosine_ops);
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'skipping chunk_embeddings_embedding_hnsw_idx: %', SQLERRM;
    END;
END
$$;
CREATE INDEX IF NOT EXISTS entity_links_entity_idx ON fah_sai_lpk_rag.entity_links (linked_table, linked_column, entity_id);
CREATE INDEX IF NOT EXISTS entity_links_public_safe_idx ON fah_sai_lpk_rag.entity_links (is_public_safe, source_type);
CREATE INDEX IF NOT EXISTS provenance_entity_links_public_safe_idx ON fah_sai_lpk_audit.provenance_entity_links (is_public_safe, source_type);

-- ---------------------------------------------------------------------------
-- Public-safe retrieval and model marts
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW fah_sai_lpk_rag.v_public_retrievable_chunks AS
SELECT
    c.chunk_id,
    c.source_document_id,
    d.source_path,
    d.source_kind,
    d.artifact_id,
    d.doc_id,
    d.source_table,
    d.source_pk,
    c.chunk_index,
    c.chunk_text,
    c.token_count,
    c.search_tsv,
    e.embedding_model,
    e.embedding,
    c.metadata AS chunk_metadata,
    d.metadata AS source_metadata
FROM fah_sai_lpk_rag.document_chunks c
JOIN fah_sai_lpk_rag.source_documents d
  ON d.source_document_id = c.source_document_id
LEFT JOIN fah_sai_lpk_rag.chunk_embeddings e
  ON e.chunk_id = c.chunk_id
WHERE c.is_public_safe = true
  AND d.is_public_safe = true;

CREATE OR REPLACE VIEW fah_sai_lpk_mart.v_sales_order AS
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
LEFT JOIN fah_sai_lpk_core.fact_bank_transaction bt ON bt.bank_txn_id = s.settlement_bank_txn_id;

CREATE OR REPLACE VIEW fah_sai_lpk_mart.v_sales_line AS
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
LEFT JOIN fah_sai_lpk_core.dim_department d ON d.dept_code = p.dept_code;

CREATE OR REPLACE VIEW fah_sai_lpk_mart.v_sales_deposit_batch_reconciliation AS
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
    SELECT
        bank_txn_id,
        related_entity_id,
        business_event_date,
        account_id,
        amount_thb
    FROM fah_sai_lpk_core.fact_bank_transaction
    WHERE related_entity_table = 'FACT_SALES_DEPOSIT_BATCH'
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
  ON bb.related_entity_id = sb.sales_deposit_batch_id;

COMMENT ON VIEW fah_sai_lpk_mart.v_sales_deposit_batch_reconciliation IS
    'Virtual QA/reconciliation view only. Does not recreate FACT_SALES_DEPOSIT_BATCH as an official table.';

CREATE OR REPLACE VIEW fah_sai_lpk_mart.v_bank_reconciliation AS
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
LEFT JOIN fah_sai_lpk_mart.v_sales_deposit_batch_reconciliation db
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
 AND bt.related_entity_id = fvp.payment_id;

CREATE OR REPLACE VIEW fah_sai_lpk_mart.v_vendor_payment AS
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
LEFT JOIN fah_sai_lpk_core.fact_bank_transaction bt ON bt.bank_txn_id = vp.bank_txn_id;
