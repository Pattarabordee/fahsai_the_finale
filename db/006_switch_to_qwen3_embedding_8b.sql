-- Switch FahMai RAG embeddings from 1536-dim OpenAI vectors to
-- Qwen/Qwen3-Embedding-8B 4096-dim vectors.
--
-- Existing embeddings are intentionally cleared because 1536-dim vectors cannot
-- be reused for 4096-dim Qwen retrieval. Re-run scripts/embed_chunks_openai.py
-- after this migration, then run db/005_rag_hnsw_and_public_chunks_mv.sql to
-- recreate the materialized retrieval cache and HNSW indexes.

CREATE EXTENSION IF NOT EXISTS vector;

DROP MATERIALIZED VIEW IF EXISTS fah_sai_lpk_rag.mv_public_retrievable_chunks;
DROP FUNCTION IF EXISTS fah_sai_lpk_rag.match_public_chunks(vector, integer, integer);
DROP VIEW IF EXISTS fah_sai_lpk_rag.v_public_retrievable_chunks;
DROP INDEX IF EXISTS fah_sai_lpk_rag.chunk_embeddings_embedding_hnsw_idx;

TRUNCATE TABLE fah_sai_lpk_rag.chunk_embeddings;

ALTER TABLE fah_sai_lpk_rag.chunk_embeddings
    ALTER COLUMN embedding_model SET DEFAULT 'Qwen/Qwen3-Embedding-8B',
    ALTER COLUMN embedding TYPE vector(4096);

COMMENT ON COLUMN fah_sai_lpk_rag.chunk_embeddings.embedding IS
    'Qwen/Qwen3-Embedding-8B embedding vector. Uses the full 4096 output dimensions.';

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
