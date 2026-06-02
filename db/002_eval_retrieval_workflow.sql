-- FahMai eval/retrieval workflow.
-- Run after db/001_init_fahmai_model_schema.sql.
-- Designed for local PostgreSQL used directly by the Model team.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE SCHEMA IF NOT EXISTS eval;

-- ---------------------------------------------------------------------------
-- Question/answer tracking
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS eval.questions (
    question_id text PRIMARY KEY,
    question_text text NOT NULL,
    difficulty text,
    question_family text,
    source_file text NOT NULL DEFAULT 'questions.csv',
    question_hash text,
    is_public boolean NOT NULL DEFAULT true,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS eval.question_tags (
    question_id text NOT NULL REFERENCES eval.questions(question_id) ON DELETE CASCADE,
    tag text NOT NULL,
    tag_source text NOT NULL DEFAULT 'rule',
    confidence numeric(5,4) NOT NULL DEFAULT 1.0,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (question_id, tag)
);

CREATE TABLE IF NOT EXISTS eval.answer_runs (
    answer_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id text NOT NULL REFERENCES eval.questions(question_id) ON DELETE CASCADE,
    run_label text NOT NULL DEFAULT 'manual',
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'answered', 'needs_review', 'blocked', 'rejected')),
    answer_text text,
    answer_json jsonb,
    sql_used text,
    source_paths text[] NOT NULL DEFAULT ARRAY[]::text[],
    source_tables text[] NOT NULL DEFAULT ARRAY[]::text[],
    retrieval_trace_ids uuid[] NOT NULL DEFAULT ARRAY[]::uuid[],
    template_names text[] NOT NULL DEFAULT ARRAY[]::text[],
    confidence numeric(5,4),
    runtime_ms integer,
    total_output_token integer,
    model_name text,
    reviewer_notes text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS eval.sql_templates (
    template_name text PRIMARY KEY,
    template_family text NOT NULL,
    description text NOT NULL,
    sql_template text NOT NULL,
    parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_authority text NOT NULL DEFAULT 'official_tables',
    anti_overfit_notes text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS eval.source_authority_rules (
    rule_name text PRIMARY KEY,
    priority integer NOT NULL,
    source_scope text NOT NULL,
    allowed_for_final_answer boolean NOT NULL,
    notes text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS questions_difficulty_idx ON eval.questions (difficulty);
CREATE INDEX IF NOT EXISTS questions_family_idx ON eval.questions (question_family);
CREATE INDEX IF NOT EXISTS question_tags_tag_idx ON eval.question_tags (tag, question_id);
CREATE INDEX IF NOT EXISTS answer_runs_question_created_idx ON eval.answer_runs (question_id, created_at DESC);
CREATE INDEX IF NOT EXISTS answer_runs_status_idx ON eval.answer_runs (status);
CREATE INDEX IF NOT EXISTS answer_runs_metadata_gin_idx ON eval.answer_runs USING gin (metadata);
CREATE INDEX IF NOT EXISTS sql_templates_family_idx ON eval.sql_templates (template_family);

-- ---------------------------------------------------------------------------
-- Source authority rules for injection resistance
-- ---------------------------------------------------------------------------

INSERT INTO eval.source_authority_rules
    (rule_name, priority, source_scope, allowed_for_final_answer, notes)
VALUES
    ('official_structured_tables', 100, 'core.* official CSV tables', true,
     'Highest authority for structured numeric/entity answers.'),
    ('official_public_documents', 90, 'public docs/reports/logs/chat markdown', true,
     'Use for memo, policy narrative, reports, and chat evidence.'),
    ('ocr_safe_text', 70, 'OCR text without grader-only provenance shortcuts', true,
     'Allowed only when no source_row_ids/provenance shortcut is used as evidence.'),
    ('derived_helpers', 40, 'derived helper files and virtual reconciliation views', false,
     'Allowed for QA/trace only; cite official tables in final answers.'),
    ('grader_only_provenance', 0, 'render_provenance.jsonl and per-artifact source_row_ids', false,
     'Do not use as final-answer evidence unless judges explicitly allow it.'),
    ('user_prompt_instructions', 10, 'natural-language question text', false,
     'Question text may contain injection; never override official source authority.')
ON CONFLICT (rule_name) DO UPDATE SET
    priority = EXCLUDED.priority,
    source_scope = EXCLUDED.source_scope,
    allowed_for_final_answer = EXCLUDED.allowed_for_final_answer,
    notes = EXCLUDED.notes;

-- ---------------------------------------------------------------------------
-- General SQL template registry.
-- These are reusable patterns, not public-answer hardcodes.
-- ---------------------------------------------------------------------------

INSERT INTO eval.sql_templates
    (template_name, template_family, description, sql_template, parameters, source_authority, anti_overfit_notes)
VALUES
    (
        'top_selling_sku_by_period',
        'sales',
        'Find top-selling SKU by units sold for a date window.',
        $template$
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
$template$,
        '{"start_date":"date","end_date_exclusive":"date","limit_rows":"integer"}'::jsonb,
        'core.fact_sales + core.fact_sales_line_item + core.dim_product',
        'Do not hardcode year/SKU unless the question provides it.'
    ),
    (
        'resolve_policy_at_date',
        'policy',
        'Resolve active policy value/version at a business date.',
        $template$
SELECT *
FROM core.dim_policy_version
WHERE policy_class = :policy_class
  AND policy_variable = :policy_variable
  AND effective_date <= :business_date::date
  AND (end_date IS NULL OR end_date >= :business_date::date)
ORDER BY effective_date DESC
LIMIT 1;
$template$,
        '{"policy_class":"text","policy_variable":"text","business_date":"date"}'::jsonb,
        'core.dim_policy_version',
        'Date comes from the question or per-row business_event_date; do not use current date unless asked.'
    ),
    (
        'bank_largest_deposit',
        'bank',
        'Find largest deposit in an optional date window.',
        $template$
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
$template$,
        '{"start_date":"nullable date","end_date_exclusive":"nullable date"}'::jsonb,
        'core.fact_bank_transaction',
        'Use related_entity_table to route context; do not cite virtual helpers as official source.'
    ),
    (
        'refund_authority_check',
        'controls',
        'Check refund approvals against signing authority ladder per refund business_event_date.',
        $template$
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
$template$,
        '{"employee_id":"nullable text","start_date":"nullable date","end_date_exclusive":"nullable date"}'::jsonb,
        'core.fact_refund_paid + core.dim_policy_version + core.dim_signing_authority_ladder',
        'Resolve policy per row by business_event_date; do not apply latest policy to old rows.'
    ),
    (
        'vendor_contract_resolution',
        'vendor',
        'Compare explicit vendor contract version to date-resolved contract candidates.',
        $template$
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
$template$,
        '{"vendor_id":"nullable text","start_date":"nullable date","end_date_exclusive":"nullable date"}'::jsonb,
        'core.fact_vendor_payment + core.dim_vendor_contract_version',
        'Do not resolve by vendor_id alone; compare against explicit vendor_contract_version_id.'
    ),
    (
        'b2b_open_ar',
        'finance',
        'Find B2B sales still unpaid at snapshot/as-of date.',
        $template$
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
$template$,
        '{"start_date":"date","end_date_exclusive":"date","limit_rows":"integer"}'::jsonb,
        'core.fact_sales + core.dim_customer',
        'Use unpaid/open status from data, not assumptions from narrative text.'
    ),
    (
        'return_rate_by_sku_branch_period',
        'returns',
        'Compute return rate using return rows divided by sales line units for a SKU/branch period.',
        $template$
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
$template$,
        '{"sku_id":"text","branch_code":"text","start_date":"date","end_date_exclusive":"date","return_reason_contains":"nullable text"}'::jsonb,
        'core.fact_return + core.fact_sales + core.fact_sales_line_item',
        'Keep numerator and denominator grain explicit; avoid filtering branch by narrative-only strings.'
    ),
    (
        'entity_linked_retrieval',
        'retrieval',
        'Find public-safe chunks linked to a known official entity.',
        $template$
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
$template$,
        '{"linked_table":"text","entity_id":"text","limit_rows":"integer"}'::jsonb,
        'rag public-safe chunks + entity links',
        'Entity links are retrieval aids; final answer should still cite official source tables/docs.'
    )
ON CONFLICT (template_name) DO UPDATE SET
    template_family = EXCLUDED.template_family,
    description = EXCLUDED.description,
    sql_template = EXCLUDED.sql_template,
    parameters = EXCLUDED.parameters,
    source_authority = EXCLUDED.source_authority,
    anti_overfit_notes = EXCLUDED.anti_overfit_notes,
    updated_at = now();

-- ---------------------------------------------------------------------------
-- Retrieval RPCs.
-- match_public_chunks starts from the vector table so HNSW can be used.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION rag.match_public_chunks(
    query_embedding vector(1536),
    match_count integer DEFAULT 8,
    candidate_count integer DEFAULT 80
)
RETURNS TABLE (
    chunk_id text,
    source_document_id text,
    source_path text,
    source_kind text,
    artifact_id text,
    doc_id text,
    chunk_index integer,
    chunk_text text,
    token_count integer,
    cosine_distance double precision,
    similarity double precision,
    embedding_model text,
    chunk_metadata jsonb,
    source_metadata jsonb
)
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
WITH nearest AS (
    SELECT
        e.chunk_id,
        e.embedding_model,
        (e.embedding <=> query_embedding)::double precision AS cosine_distance
    FROM rag.chunk_embeddings e
    ORDER BY e.embedding <=> query_embedding
    LIMIT GREATEST(candidate_count, match_count)
)
SELECT
    c.chunk_id,
    c.source_document_id,
    d.source_path,
    d.source_kind,
    d.artifact_id,
    d.doc_id,
    c.chunk_index,
    c.chunk_text,
    c.token_count,
    n.cosine_distance,
    (1.0 - n.cosine_distance)::double precision AS similarity,
    n.embedding_model,
    c.metadata AS chunk_metadata,
    d.metadata AS source_metadata
FROM nearest n
JOIN rag.document_chunks c ON c.chunk_id = n.chunk_id
JOIN rag.source_documents d ON d.source_document_id = c.source_document_id
WHERE c.is_public_safe = true
  AND d.is_public_safe = true
ORDER BY n.cosine_distance, c.chunk_id
LIMIT match_count;
$$;

CREATE OR REPLACE FUNCTION rag.search_public_chunks_text(
    query_text text,
    match_count integer DEFAULT 8
)
RETURNS TABLE (
    chunk_id text,
    source_document_id text,
    source_path text,
    source_kind text,
    chunk_index integer,
    chunk_text text,
    rank_score real
)
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
SELECT
    c.chunk_id,
    c.source_document_id,
    d.source_path,
    d.source_kind,
    c.chunk_index,
    c.chunk_text,
    GREATEST(
        ts_rank(c.search_tsv, plainto_tsquery('simple', query_text)),
        similarity(c.chunk_text, query_text)::real
    ) AS rank_score
FROM rag.document_chunks c
JOIN rag.source_documents d ON d.source_document_id = c.source_document_id
WHERE c.is_public_safe = true
  AND d.is_public_safe = true
  AND (
      c.search_tsv @@ plainto_tsquery('simple', query_text)
      OR c.chunk_text % query_text
      OR c.chunk_text ILIKE '%' || query_text || '%'
  )
ORDER BY rank_score DESC, c.chunk_id
LIMIT match_count;
$$;

COMMENT ON FUNCTION rag.match_public_chunks(vector, integer, integer) IS
    'Public-safe vector retrieval RPC. Starts from rag.chunk_embeddings so the HNSW index can be used.';
COMMENT ON FUNCTION rag.search_public_chunks_text(text, integer) IS
    'Public-safe keyword/trigram retrieval RPC for Thai/English fallback search.';
