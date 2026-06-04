-- Store generated M-Schema prompt artifacts in the remote DB for model-team handoff.
-- Keep this outside fah_sai_lpk_model so the LLM-facing schema still has exactly 8 views.

CREATE SCHEMA IF NOT EXISTS fah_sai_lpk_meta;

CREATE TABLE IF NOT EXISTS fah_sai_lpk_meta.mschema_artifacts (
    artifact_name text NOT NULL,
    schema_mode text NOT NULL,
    artifact_format text NOT NULL,
    content text NOT NULL,
    content_sha256 text NOT NULL,
    relation_count integer NOT NULL,
    retrieval_profile text,
    generated_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (artifact_name, schema_mode, artifact_format)
);

CREATE OR REPLACE VIEW fah_sai_lpk_meta.v_current_mschema_artifacts AS
SELECT
    artifact_name,
    schema_mode,
    artifact_format,
    content,
    content_sha256,
    relation_count,
    retrieval_profile,
    generated_at,
    metadata
FROM fah_sai_lpk_meta.mschema_artifacts
WHERE artifact_name = 'fahmai_model_mschema'
  AND schema_mode = 'model';

COMMENT ON SCHEMA fah_sai_lpk_meta IS
    'Metadata handoff schema for generated prompts/artifacts. Not part of the 8-view LLM-facing model schema.';
COMMENT ON TABLE fah_sai_lpk_meta.mschema_artifacts IS
    'Generated M-Schema artifacts stored for model-team/API handoff.';
COMMENT ON VIEW fah_sai_lpk_meta.v_current_mschema_artifacts IS
    'Current FahMai model-mode M-Schema artifacts in text/json formats.';
