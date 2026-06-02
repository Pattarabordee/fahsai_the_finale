-- FahMai RAG materialized retrieval cache and HNSW tuning.
-- Run after embeddings have been generated for public-safe chunks.

CREATE EXTENSION IF NOT EXISTS vector;

DROP FUNCTION IF EXISTS rag.match_public_chunks(vector, integer, integer);

DROP INDEX IF EXISTS rag.chunk_embeddings_embedding_hnsw_idx;

CREATE INDEX IF NOT EXISTS chunk_embeddings_embedding_hnsw_idx
    ON rag.chunk_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 128);

DROP MATERIALIZED VIEW IF EXISTS rag.mv_public_retrievable_chunks;

CREATE MATERIALIZED VIEW rag.mv_public_retrievable_chunks AS
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
    e.embedding_created_at,
    c.metadata AS chunk_metadata,
    d.metadata AS source_metadata
FROM rag.document_chunks c
JOIN rag.source_documents d
  ON d.source_document_id = c.source_document_id
JOIN rag.chunk_embeddings e
  ON e.chunk_id = c.chunk_id
WHERE c.is_public_safe = true
  AND d.is_public_safe = true
WITH NO DATA;

CREATE UNIQUE INDEX mv_public_retrievable_chunks_chunk_id_uidx
    ON rag.mv_public_retrievable_chunks (chunk_id);
CREATE INDEX mv_public_retrievable_chunks_embedding_hnsw_idx
    ON rag.mv_public_retrievable_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 128);
CREATE INDEX mv_public_retrievable_chunks_tsv_idx
    ON rag.mv_public_retrievable_chunks USING gin (search_tsv);
CREATE INDEX mv_public_retrievable_chunks_source_kind_idx
    ON rag.mv_public_retrievable_chunks (source_kind);
CREATE INDEX mv_public_retrievable_chunks_source_path_idx
    ON rag.mv_public_retrievable_chunks (source_path);

COMMENT ON MATERIALIZED VIEW rag.mv_public_retrievable_chunks IS
    'Public-safe embedded chunks only. Use for vector retrieval; keep rag.v_public_retrievable_chunks for inspection and non-embedded fallback paths.';

CREATE OR REPLACE FUNCTION rag.refresh_public_retrievable_chunks(use_concurrently boolean DEFAULT false)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    refresh_prefix text := CASE
        WHEN use_concurrently THEN 'REFRESH MATERIALIZED VIEW CONCURRENTLY '
        ELSE 'REFRESH MATERIALIZED VIEW '
    END;
BEGIN
    EXECUTE refresh_prefix || 'rag.mv_public_retrievable_chunks';
    EXECUTE 'ANALYZE rag.mv_public_retrievable_chunks';
END;
$$;

COMMENT ON FUNCTION rag.refresh_public_retrievable_chunks(boolean) IS
    'Refresh the public-safe embedded chunk retrieval cache. Use false for first load; true only after the materialized view is already populated.';

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
        m.chunk_id,
        m.source_document_id,
        m.source_path,
        m.source_kind,
        m.artifact_id,
        m.doc_id,
        m.chunk_index,
        m.chunk_text,
        m.token_count,
        m.embedding_model,
        m.chunk_metadata,
        m.source_metadata,
        (m.embedding <=> query_embedding)::double precision AS cosine_distance
    FROM rag.mv_public_retrievable_chunks m
    ORDER BY m.embedding <=> query_embedding
    LIMIT GREATEST(candidate_count, match_count)
)
SELECT
    n.chunk_id,
    n.source_document_id,
    n.source_path,
    n.source_kind,
    n.artifact_id,
    n.doc_id,
    n.chunk_index,
    n.chunk_text,
    n.token_count,
    n.cosine_distance,
    (1.0 - n.cosine_distance)::double precision AS similarity,
    n.embedding_model,
    n.chunk_metadata,
    n.source_metadata
FROM nearest n
ORDER BY n.cosine_distance, n.chunk_id
LIMIT match_count;
$$;

COMMENT ON FUNCTION rag.match_public_chunks(vector, integer, integer) IS
    'Public-safe vector retrieval RPC backed by rag.mv_public_retrievable_chunks so retrieval avoids the repeated chunk/document/embedding join.';

CREATE OR REPLACE FUNCTION mart.refresh_all_materialized_views(use_concurrently boolean DEFAULT false)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    refresh_prefix text := CASE
        WHEN use_concurrently THEN 'REFRESH MATERIALIZED VIEW CONCURRENTLY '
        ELSE 'REFRESH MATERIALIZED VIEW '
    END;
BEGIN
    PERFORM rag.refresh_public_retrievable_chunks(use_concurrently);

    EXECUTE refresh_prefix || 'mart.mv_sales_deposit_batch_reconciliation';
    EXECUTE refresh_prefix || 'mart.mv_sales_order';
    EXECUTE refresh_prefix || 'mart.mv_sales_line';
    EXECUTE refresh_prefix || 'mart.mv_bank_reconciliation';
    EXECUTE refresh_prefix || 'mart.mv_vendor_payment';

    EXECUTE 'ANALYZE mart.mv_sales_deposit_batch_reconciliation';
    EXECUTE 'ANALYZE mart.mv_sales_order';
    EXECUTE 'ANALYZE mart.mv_sales_line';
    EXECUTE 'ANALYZE mart.mv_bank_reconciliation';
    EXECUTE 'ANALYZE mart.mv_vendor_payment';
END;
$$;

COMMENT ON FUNCTION mart.refresh_all_materialized_views(boolean) IS
    'Refresh RAG and mart materialized caches. Use false for first load; true only after all materialized views are already populated.';
