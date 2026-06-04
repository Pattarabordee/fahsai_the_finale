-- FahMai BGE-M3 HNSW index and retrieval stats.
-- Space-aware design: index the embedding table directly and do not copy vectors into a MV.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE INDEX IF NOT EXISTS child_chunk_embeddings_bge_m3_embedding_hnsw_idx
    ON fah_sai_lpk_rag.child_chunk_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 128);

SELECT fah_sai_lpk_rag.refresh_public_retrievable_child_chunks_bge_m3(false);

COMMENT ON INDEX fah_sai_lpk_rag.child_chunk_embeddings_bge_m3_embedding_hnsw_idx IS
    'HNSW cosine index for BGE-M3 1024-dimensional child embeddings.';
