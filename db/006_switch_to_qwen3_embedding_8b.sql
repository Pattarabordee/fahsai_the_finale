-- Switch FahMai RAG embeddings from 1536-dim OpenAI vectors to
-- Qwen/Qwen3-Embedding-8B 4096-dim vectors.
--
-- Existing embeddings are intentionally cleared because 1536-dim vectors cannot
-- be reused for 4096-dim Qwen retrieval. Re-run scripts/embed_chunks_openai.py
-- after this migration, then run db/005_rag_hnsw_and_public_chunks_mv.sql to
-- recreate the materialized retrieval cache and HNSW indexes.

CREATE EXTENSION IF NOT EXISTS vector;

DROP MATERIALIZED VIEW IF EXISTS rag.mv_public_retrievable_chunks;
DROP FUNCTION IF EXISTS rag.match_public_chunks(vector, integer, integer);
DROP INDEX IF EXISTS rag.chunk_embeddings_embedding_hnsw_idx;

TRUNCATE TABLE rag.chunk_embeddings;

ALTER TABLE rag.chunk_embeddings
    ALTER COLUMN embedding_model SET DEFAULT 'Qwen/Qwen3-Embedding-8B',
    ALTER COLUMN embedding TYPE vector(4096);

COMMENT ON COLUMN rag.chunk_embeddings.embedding IS
    'Qwen/Qwen3-Embedding-8B embedding vector. Uses the full 4096 output dimensions.';
