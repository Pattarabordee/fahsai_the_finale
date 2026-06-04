-- Keep the model-facing schema comments prompt-safe by avoiding backend schema names.

COMMENT ON COLUMN fah_sai_lpk_model.document_evidence.parent_chunk_id IS
    'Parent context row used to hydrate this embedded child chunk.';
