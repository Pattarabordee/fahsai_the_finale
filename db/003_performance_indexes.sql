-- FahMai performance indexes and post-load analyze helper.
-- Run after loading raw/core/rag data. For a live production DB, consider
-- CREATE INDEX CONCURRENTLY variants; this local hackathon DB is expected to
-- be loaded offline.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------------------
-- FK/lookup indexes missing from the initial schema.
-- PostgreSQL does not automatically index foreign-key columns.
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS dim_employee_position_level_idx
    ON core.dim_employee (position_level);
CREATE INDEX IF NOT EXISTS dim_employee_reports_to_idx
    ON core.dim_employee (reports_to_employee_id);
CREATE INDEX IF NOT EXISTS dim_customer_type_tier_idx
    ON core.dim_customer (customer_type, loyalty_tier);
CREATE INDEX IF NOT EXISTS dim_customer_loyalty_tier_idx
    ON core.dim_customer (loyalty_tier);
CREATE INDEX IF NOT EXISTS dim_product_category_idx
    ON core.dim_product (category, subcategory);
CREATE INDEX IF NOT EXISTS dim_product_brand_idx
    ON core.dim_product (brand_family);

CREATE INDEX IF NOT EXISTS dim_care_plus_policy_idx
    ON core.dim_care_plus_sku_tier (policy_version_id);
CREATE INDEX IF NOT EXISTS dim_care_plus_sku_idx
    ON core.dim_care_plus_sku_tier (sku_id);
CREATE INDEX IF NOT EXISTS dim_product_recall_sku_date_idx
    ON core.dim_product_recall_history (sku_id, transition_date);
CREATE INDEX IF NOT EXISTS dim_promo_mechanic_campaign_idx
    ON core.dim_promo_mechanic (campaign_id);
CREATE INDEX IF NOT EXISTS dim_signing_ladder_policy_idx
    ON core.dim_signing_authority_ladder (policy_version_id, position_level_code, dept_code);
CREATE INDEX IF NOT EXISTS dim_signing_ladder_cosigner_idx
    ON core.dim_signing_authority_ladder (co_signer_min_position_level_code);

CREATE INDEX IF NOT EXISTS fact_sales_branch_date_idx
    ON core.fact_sales (branch_code, business_event_date);
CREATE INDEX IF NOT EXISTS fact_sales_employee_date_idx
    ON core.fact_sales (employee_id, business_event_date);
CREATE INDEX IF NOT EXISTS fact_sales_promo_date_idx
    ON core.fact_sales (promo_campaign_id, business_event_date);
CREATE INDEX IF NOT EXISTS fact_sales_payment_status_date_idx
    ON core.fact_sales (payment_status, business_event_date);
CREATE INDEX IF NOT EXISTS fact_sales_b2b_open_ar_idx
    ON core.fact_sales (business_event_date, customer_id, net_total_thb DESC)
    WHERE is_b2b = true AND payment_received_date IS NULL;

CREATE INDEX IF NOT EXISTS fact_sales_line_txn_sku_idx
    ON core.fact_sales_line_item (txn_id, sku_id);
CREATE INDEX IF NOT EXISTS fact_sales_line_sku_date_idx
    ON core.fact_sales_line_item (sku_id, business_event_date);
CREATE INDEX IF NOT EXISTS fact_sales_line_care_plus_idx
    ON core.fact_sales_line_item (is_care_plus, sku_id)
    WHERE is_care_plus = true;

CREATE INDEX IF NOT EXISTS fact_bank_transaction_deposit_idx
    ON core.fact_bank_transaction (amount_thb DESC, business_event_date, account_id)
    WHERE amount_thb > 0;
CREATE INDEX IF NOT EXISTS fact_bank_transaction_posting_idx
    ON core.fact_bank_transaction (posting_date);

CREATE INDEX IF NOT EXISTS fact_payroll_employee_period_idx
    ON core.fact_payroll (employee_id, pay_period_start, pay_period_end);
CREATE INDEX IF NOT EXISTS fact_payroll_bank_txn_idx
    ON core.fact_payroll (bank_txn_id);

CREATE INDEX IF NOT EXISTS fact_loyalty_ledger_customer_date_idx
    ON core.fact_loyalty_ledger (customer_id, business_event_date);
CREATE INDEX IF NOT EXISTS fact_loyalty_ledger_event_date_idx
    ON core.fact_loyalty_ledger (event_type, business_event_date);
CREATE INDEX IF NOT EXISTS fact_loyalty_ledger_customer_balance_idx
    ON core.fact_loyalty_ledger (customer_id, business_event_date DESC)
    INCLUDE (resulting_balance_points, resulting_tier);

CREATE INDEX IF NOT EXISTS fact_promo_redemption_customer_idx
    ON core.fact_promo_redemption (customer_id);
CREATE INDEX IF NOT EXISTS fact_promo_redemption_campaign_idx
    ON core.fact_promo_redemption (campaign_id);
CREATE INDEX IF NOT EXISTS fact_promo_redemption_txn_channel_idx
    ON core.fact_promo_redemption (txn_id, channel);

CREATE INDEX IF NOT EXISTS fact_shipping_txn_idx
    ON core.fact_shipping (txn_id);
CREATE INDEX IF NOT EXISTS fact_shipping_vendor_idx
    ON core.fact_shipping (vendor_id);
CREATE INDEX IF NOT EXISTS fact_shipping_origin_branch_idx
    ON core.fact_shipping (origin_branch_code);

CREATE INDEX IF NOT EXISTS fact_inventory_snapshot_sku_branch_month_idx
    ON core.fact_inventory_monthly_snapshot (sku_id, branch_code, month_end_date);
CREATE INDEX IF NOT EXISTS fact_inventory_snapshot_branch_month_idx
    ON core.fact_inventory_monthly_snapshot (branch_code, month_end_date);

CREATE INDEX IF NOT EXISTS fact_inventory_movement_sku_branch_date_idx
    ON core.fact_inventory_movement (sku_id, branch_code, business_event_date);
CREATE INDEX IF NOT EXISTS fact_inventory_movement_branch_date_idx
    ON core.fact_inventory_movement (branch_code, business_event_date);
CREATE INDEX IF NOT EXISTS fact_inventory_movement_type_date_idx
    ON core.fact_inventory_movement (movement_type, business_event_date);

CREATE INDEX IF NOT EXISTS fact_warranty_claim_customer_date_idx
    ON core.fact_warranty_claim (customer_id, business_event_date);
CREATE INDEX IF NOT EXISTS fact_warranty_claim_sku_date_idx
    ON core.fact_warranty_claim (sku_id, business_event_date);
CREATE INDEX IF NOT EXISTS fact_warranty_claim_original_txn_idx
    ON core.fact_warranty_claim (original_txn_id);
CREATE INDEX IF NOT EXISTS fact_warranty_claim_reason_trgm_idx
    ON core.fact_warranty_claim USING gin (claim_reason gin_trgm_ops);

CREATE INDEX IF NOT EXISTS fact_return_customer_date_idx
    ON core.fact_return (customer_id, business_event_date);
CREATE INDEX IF NOT EXISTS fact_return_sku_branch_date_idx
    ON core.fact_return (sku_id, branch_code, business_event_date);
CREATE INDEX IF NOT EXISTS fact_return_line_item_idx
    ON core.fact_return (line_item_id);
CREATE INDEX IF NOT EXISTS fact_return_approved_by_idx
    ON core.fact_return (approved_by_employee_id);
CREATE INDEX IF NOT EXISTS fact_return_reason_trgm_idx
    ON core.fact_return USING gin (return_reason gin_trgm_ops);

CREATE INDEX IF NOT EXISTS fact_cs_interaction_customer_date_idx
    ON core.fact_cs_interaction (customer_id, business_event_date);
CREATE INDEX IF NOT EXISTS fact_cs_interaction_employee_date_idx
    ON core.fact_cs_interaction (employee_id, business_event_date);
CREATE INDEX IF NOT EXISTS fact_cs_interaction_branch_date_idx
    ON core.fact_cs_interaction (branch_code, business_event_date);
CREATE INDEX IF NOT EXISTS fact_cs_interaction_refund_idx
    ON core.fact_cs_interaction (related_refund_id);
CREATE INDEX IF NOT EXISTS fact_cs_interaction_warranty_idx
    ON core.fact_cs_interaction (related_warranty_claim_id);
CREATE INDEX IF NOT EXISTS fact_cs_interaction_chat_session_idx
    ON core.fact_cs_interaction (chat_session_id);

CREATE INDEX IF NOT EXISTS fact_refund_paid_cs_idx
    ON core.fact_refund_paid (cs_interaction_id);
CREATE INDEX IF NOT EXISTS fact_refund_paid_customer_date_idx
    ON core.fact_refund_paid (customer_id, business_event_date);
CREATE INDEX IF NOT EXISTS fact_refund_paid_approver_date_idx
    ON core.fact_refund_paid (approver_employee_id, business_event_date);
CREATE INDEX IF NOT EXISTS fact_refund_paid_cosig_idx
    ON core.fact_refund_paid (cosig_employee_id);
CREATE INDEX IF NOT EXISTS fact_refund_paid_bank_txn_idx
    ON core.fact_refund_paid (bank_txn_id);
CREATE INDEX IF NOT EXISTS fact_refund_paid_no_cosig_idx
    ON core.fact_refund_paid (approver_employee_id, business_event_date, refund_amount_thb)
    WHERE cosig_employee_id IS NULL;

CREATE INDEX IF NOT EXISTS fact_vendor_payment_signing_idx
    ON core.fact_vendor_payment (signing_employee_id);
CREATE INDEX IF NOT EXISTS fact_vendor_payment_cosig_idx
    ON core.fact_vendor_payment (cosig_employee_id);
CREATE INDEX IF NOT EXISTS fact_vendor_payment_bank_txn_idx
    ON core.fact_vendor_payment (bank_txn_id);
CREATE INDEX IF NOT EXISTS fact_vendor_payment_vendor_date_idx
    ON core.fact_vendor_payment (vendor_id, business_event_date);
CREATE INDEX IF NOT EXISTS fact_vendor_payment_invoice_idx
    ON core.fact_vendor_payment (vendor_invoice_id);

-- ---------------------------------------------------------------------------
-- RAG/retrieval indexes.
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS source_documents_doc_idx
    ON rag.source_documents (doc_id);
CREATE INDEX IF NOT EXISTS source_documents_table_pk_idx
    ON rag.source_documents (source_table, source_pk);
CREATE INDEX IF NOT EXISTS source_documents_sha_idx
    ON rag.source_documents (content_sha256);
CREATE INDEX IF NOT EXISTS document_chunks_text_trgm_idx
    ON rag.document_chunks USING gin (chunk_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS entity_links_source_document_idx
    ON rag.entity_links (source_document_id);
CREATE INDEX IF NOT EXISTS entity_links_chunk_idx
    ON rag.entity_links (chunk_id);
CREATE INDEX IF NOT EXISTS entity_links_entity_type_idx
    ON rag.entity_links (entity_type, entity_id);

-- ---------------------------------------------------------------------------
-- Post-load ANALYZE helper.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION audit.analyze_fahmai_model_tables()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    EXECUTE 'ANALYZE core.dim_bank_account';
    EXECUTE 'ANALYZE core.dim_branch';
    EXECUTE 'ANALYZE core.dim_customer';
    EXECUTE 'ANALYZE core.dim_date';
    EXECUTE 'ANALYZE core.dim_department';
    EXECUTE 'ANALYZE core.dim_employee';
    EXECUTE 'ANALYZE core.dim_policy_version';
    EXECUTE 'ANALYZE core.dim_position_level';
    EXECUTE 'ANALYZE core.dim_product';
    EXECUTE 'ANALYZE core.dim_promo_campaign';
    EXECUTE 'ANALYZE core.dim_vendor';
    EXECUTE 'ANALYZE core.dim_vendor_contract_version';
    EXECUTE 'ANALYZE core.fact_bank_transaction';
    EXECUTE 'ANALYZE core.fact_cs_interaction';
    EXECUTE 'ANALYZE core.fact_inventory_monthly_snapshot';
    EXECUTE 'ANALYZE core.fact_inventory_movement';
    EXECUTE 'ANALYZE core.fact_loyalty_ledger';
    EXECUTE 'ANALYZE core.fact_payroll';
    EXECUTE 'ANALYZE core.fact_promo_redemption';
    EXECUTE 'ANALYZE core.fact_refund_paid';
    EXECUTE 'ANALYZE core.fact_return';
    EXECUTE 'ANALYZE core.fact_sales';
    EXECUTE 'ANALYZE core.fact_sales_line_item';
    EXECUTE 'ANALYZE core.fact_shipping';
    EXECUTE 'ANALYZE core.fact_vendor_payment';
    EXECUTE 'ANALYZE core.fact_warranty_claim';
    EXECUTE 'ANALYZE core.t2_doc_inventory';
    EXECUTE 'ANALYZE rag.source_documents';
    EXECUTE 'ANALYZE rag.document_chunks';
    EXECUTE 'ANALYZE rag.chunk_embeddings';
    EXECUTE 'ANALYZE rag.entity_links';
    EXECUTE 'ANALYZE eval.questions';
    EXECUTE 'ANALYZE eval.question_tags';
    EXECUTE 'ANALYZE eval.answer_runs';
END;
$$;

COMMENT ON FUNCTION audit.analyze_fahmai_model_tables() IS
    'Run after bulk loading FahMai core/rag/eval data so the planner has fresh statistics.';
