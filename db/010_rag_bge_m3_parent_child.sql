-- FahMai BGE-M3 parent-child RAG v2 schema.
-- Space-aware design: reuse legacy fah_sai_lpk_rag.document_chunks as parents,
-- store only BGE child chunks and BGE 1024 embeddings, and avoid vector-copy MVs.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS fah_sai_lpk_rag.child_chunks (
    child_chunk_id text PRIMARY KEY,
    parent_chunk_id text NOT NULL REFERENCES fah_sai_lpk_rag.document_chunks(chunk_id) ON DELETE CASCADE,
    retrieval_profile text NOT NULL DEFAULT 'bge_m3_v1',
    source_document_id text NOT NULL REFERENCES fah_sai_lpk_rag.source_documents(source_document_id) ON DELETE CASCADE,
    child_index integer NOT NULL,
    child_index_in_parent integer NOT NULL,
    child_text text,
    child_start_in_parent integer NOT NULL DEFAULT 0,
    child_end_in_parent integer NOT NULL DEFAULT 0,
    token_count integer,
    char_start integer,
    char_end integer,
    language_hint text,
    is_public_safe boolean NOT NULL DEFAULT true,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (child_end_in_parent >= child_start_in_parent),
    UNIQUE (retrieval_profile, source_document_id, child_index),
    UNIQUE (retrieval_profile, parent_chunk_id, child_index_in_parent)
);

CREATE TABLE IF NOT EXISTS fah_sai_lpk_rag.child_chunk_embeddings (
    child_chunk_id text PRIMARY KEY REFERENCES fah_sai_lpk_rag.child_chunks(child_chunk_id) ON DELETE CASCADE,
    retrieval_profile text NOT NULL DEFAULT 'bge_m3_v1',
    embedding_model text NOT NULL DEFAULT 'BAAI/bge-m3',
    embedding vector(1024) NOT NULL,
    embedding_created_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS child_chunks_profile_source_idx
    ON fah_sai_lpk_rag.child_chunks (retrieval_profile, source_document_id, child_index);
CREATE INDEX IF NOT EXISTS child_chunks_parent_idx
    ON fah_sai_lpk_rag.child_chunks (parent_chunk_id, child_index_in_parent);
CREATE INDEX IF NOT EXISTS child_chunks_public_safe_idx
    ON fah_sai_lpk_rag.child_chunks (retrieval_profile, is_public_safe);
CREATE INDEX IF NOT EXISTS child_chunk_embeddings_profile_model_idx
    ON fah_sai_lpk_rag.child_chunk_embeddings (retrieval_profile, embedding_model);

COMMENT ON TABLE fah_sai_lpk_rag.child_chunks IS
    'Space-aware embedding-grain child chunks for profile-aware RAG. parent_chunk_id points to existing document_chunks for hydrated context.';
COMMENT ON TABLE fah_sai_lpk_rag.child_chunk_embeddings IS
    'BGE-M3 1024-dimensional child embeddings stored separately from legacy Qwen 4096 embeddings.';

DROP FUNCTION IF EXISTS fah_sai_lpk_rag.match_public_chunks_bge_m3(vector, integer, integer);
DROP FUNCTION IF EXISTS fah_sai_lpk_rag.search_public_child_chunks_text(text, integer);
DROP FUNCTION IF EXISTS fah_sai_lpk_rag.refresh_public_retrievable_child_chunks_bge_m3(boolean);
DROP VIEW IF EXISTS fah_sai_lpk_model.document_evidence;
DROP VIEW IF EXISTS fah_sai_lpk_rag.v_public_retrievable_child_chunks_bge_m3;

CREATE OR REPLACE VIEW fah_sai_lpk_rag.v_public_retrievable_child_chunks_bge_m3 AS
SELECT
    cc.child_chunk_id,
    cc.child_chunk_id AS chunk_id,
    cc.parent_chunk_id,
    cc.retrieval_profile,
    cc.source_document_id,
    d.source_path,
    d.source_kind,
    d.artifact_id,
    d.doc_id,
    d.source_table,
    d.source_pk,
    cc.child_index AS chunk_index,
    cc.child_index,
    cc.child_index_in_parent,
    substring(
        pc.chunk_text
        FROM cc.child_start_in_parent + 1
        FOR GREATEST(0, cc.child_end_in_parent - cc.child_start_in_parent)
    ) AS chunk_text,
    substring(
        pc.chunk_text
        FROM cc.child_start_in_parent + 1
        FOR GREATEST(0, cc.child_end_in_parent - cc.child_start_in_parent)
    ) AS child_text,
    pc.chunk_index AS parent_index,
    pc.chunk_text AS parent_text,
    cc.token_count,
    to_tsvector(
        'simple',
        substring(
            pc.chunk_text
            FROM cc.child_start_in_parent + 1
            FOR GREATEST(0, cc.child_end_in_parent - cc.child_start_in_parent)
        )
    ) AS search_tsv,
    e.embedding_model,
    e.embedding,
    cc.metadata AS chunk_metadata,
    pc.metadata AS parent_metadata,
    d.metadata AS source_metadata
FROM fah_sai_lpk_rag.child_chunks cc
JOIN fah_sai_lpk_rag.document_chunks pc
  ON pc.chunk_id = cc.parent_chunk_id
JOIN fah_sai_lpk_rag.source_documents d
  ON d.source_document_id = cc.source_document_id
LEFT JOIN fah_sai_lpk_rag.child_chunk_embeddings e
  ON e.child_chunk_id = cc.child_chunk_id
WHERE cc.retrieval_profile = 'bge_m3_v1'
  AND cc.is_public_safe = true
  AND pc.is_public_safe = true
  AND d.is_public_safe = true;

CREATE OR REPLACE FUNCTION fah_sai_lpk_rag.refresh_public_retrievable_child_chunks_bge_m3(
    use_concurrently boolean DEFAULT false
)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    EXECUTE 'ANALYZE fah_sai_lpk_rag.child_chunks';
    EXECUTE 'ANALYZE fah_sai_lpk_rag.child_chunk_embeddings';
END;
$$;

CREATE OR REPLACE FUNCTION fah_sai_lpk_rag.match_public_chunks_bge_m3(
    query_embedding vector(1024),
    match_count integer DEFAULT 8,
    candidate_count integer DEFAULT 80
)
RETURNS TABLE (
    chunk_id text,
    child_chunk_id text,
    parent_chunk_id text,
    source_document_id text,
    source_path text,
    source_kind text,
    artifact_id text,
    doc_id text,
    source_table text,
    source_pk text,
    chunk_index integer,
    child_index integer,
    parent_index integer,
    chunk_text text,
    parent_text text,
    token_count integer,
    cosine_distance double precision,
    similarity double precision,
    embedding_model text,
    chunk_metadata jsonb,
    parent_metadata jsonb,
    source_metadata jsonb
)
LANGUAGE sql
STABLE
AS $$
WITH nearest AS MATERIALIZED (
    SELECT
        e.child_chunk_id,
        (e.embedding <=> query_embedding)::double precision AS cosine_distance,
        e.embedding_model
    FROM fah_sai_lpk_rag.child_chunk_embeddings e
    WHERE e.retrieval_profile = 'bge_m3_v1'
    ORDER BY e.embedding <=> query_embedding
    LIMIT GREATEST(match_count, candidate_count)
)
SELECT
    c.chunk_id,
    c.child_chunk_id,
    c.parent_chunk_id,
    c.source_document_id,
    c.source_path,
    c.source_kind,
    c.artifact_id,
    c.doc_id,
    c.source_table,
    c.source_pk,
    c.chunk_index,
    c.child_index,
    c.parent_index,
    c.chunk_text,
    c.parent_text,
    c.token_count,
    n.cosine_distance,
    (1.0 - n.cosine_distance)::double precision AS similarity,
    n.embedding_model,
    c.chunk_metadata,
    c.parent_metadata,
    c.source_metadata
FROM nearest n
JOIN fah_sai_lpk_rag.v_public_retrievable_child_chunks_bge_m3 c
  ON c.child_chunk_id = n.child_chunk_id
ORDER BY n.cosine_distance, n.child_chunk_id
LIMIT match_count;
$$;

CREATE OR REPLACE FUNCTION fah_sai_lpk_rag.search_public_child_chunks_text(
    query_text text,
    match_count integer DEFAULT 8
)
RETURNS TABLE (
    chunk_id text,
    child_chunk_id text,
    parent_chunk_id text,
    source_document_id text,
    source_path text,
    source_kind text,
    chunk_index integer,
    chunk_text text,
    parent_text text,
    rank_score real
)
LANGUAGE sql
STABLE
AS $$
WITH q AS (
    SELECT plainto_tsquery('simple', query_text) AS query
)
SELECT
    c.child_chunk_id AS chunk_id,
    c.child_chunk_id,
    c.parent_chunk_id,
    c.source_document_id,
    c.source_path,
    c.source_kind,
    c.child_index AS chunk_index,
    c.child_text AS chunk_text,
    c.parent_text,
    ts_rank_cd(c.search_tsv, q.query) AS rank_score
FROM fah_sai_lpk_rag.v_public_retrievable_child_chunks_bge_m3 c, q
WHERE c.search_tsv @@ q.query
ORDER BY rank_score DESC, c.child_chunk_id
LIMIT match_count;
$$;

COMMENT ON FUNCTION fah_sai_lpk_rag.match_public_chunks_bge_m3(vector, integer, integer) IS
    'Public-safe BGE-M3 vector retrieval RPC over compact child chunks, returning existing document_chunks parent context.';
COMMENT ON FUNCTION fah_sai_lpk_rag.search_public_child_chunks_text(text, integer) IS
    'Public-safe text fallback over BGE-M3 parent-child child chunks.';

CREATE OR REPLACE VIEW fah_sai_lpk_model.document_evidence AS
SELECT
    CASE
        WHEN el.entity_link_id IS NULL THEN c.child_chunk_id
        ELSE c.child_chunk_id || ':' || el.entity_link_id::text
    END AS evidence_row_id,
    coalesce(el.linked_table, c.source_table) AS source_table,
    coalesce(el.entity_id, c.source_pk) AS source_pk,
    ARRAY[
        'fah_sai_lpk_rag.source_documents',
        'fah_sai_lpk_rag.document_chunks',
        'fah_sai_lpk_rag.child_chunks',
        'fah_sai_lpk_rag.child_chunk_embeddings',
        'fah_sai_lpk_rag.entity_links',
        'T2_DOC_INVENTORY'
    ]::text[] AS source_aliases,
    c.retrieval_profile,
    c.child_chunk_id AS chunk_id,
    c.child_chunk_id,
    c.parent_chunk_id,
    c.source_document_id,
    c.source_path,
    c.source_kind,
    c.artifact_id,
    c.doc_id,
    c.child_index AS chunk_index,
    c.child_text AS chunk_text,
    c.parent_text,
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
    c.parent_metadata,
    c.source_metadata
FROM fah_sai_lpk_rag.v_public_retrievable_child_chunks_bge_m3 c
LEFT JOIN LATERAL (
    SELECT el.*
    FROM fah_sai_lpk_rag.entity_links el
    WHERE el.source_document_id = c.source_document_id
      AND el.is_public_safe = true
      AND (
          position(el.entity_id in c.child_text) > 0
          OR position(el.entity_id in c.parent_text) > 0
      )
    ORDER BY
        (position(el.entity_id in c.child_text) > 0) DESC,
        el.confidence DESC,
        el.entity_link_id
    LIMIT 1
) el ON true;

COMMENT ON VIEW fah_sai_lpk_model.document_evidence IS
    'Model-facing public-safe document evidence surface over compact BGE-M3 parent-child RAG chunks and entity links. Use child chunk text for matching and parent_text for hydrated context.';
COMMENT ON COLUMN fah_sai_lpk_model.document_evidence.retrieval_profile IS
    'Retrieval profile for embedded evidence. Default production profile is bge_m3_v1.';
COMMENT ON COLUMN fah_sai_lpk_model.document_evidence.parent_chunk_id IS
    'Parent context row used to hydrate this embedded child chunk.';
COMMENT ON COLUMN fah_sai_lpk_model.document_evidence.has_embedding IS
    'True when this public-safe BGE-M3 child chunk has a 1024-dimensional embedding available through match_public_chunks_bge_m3.';
