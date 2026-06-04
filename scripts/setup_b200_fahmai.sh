#!/usr/bin/env bash
# Bootstrap FahMai PostgreSQL + BGE-M3 embeddings on a Linux B200 VM.
#
# Required:
#   export FAHMAI_DB_PASSWORD='...'
#
# Common usage:
#   bash scripts/setup_b200_fahmai.sh
#   LOAD_DATA=1 bash scripts/setup_b200_fahmai.sh
#   LOAD_DATA=1 GENERATE_EMBEDDINGS=1 bash scripts/setup_b200_fahmai.sh

set -Eeuo pipefail

DB_NAME="${DB_NAME:-fahmai}"
DB_USER="${DB_USER:-fahmai_app}"
DB_PORT="${DB_PORT:-5432}"
PGDATA_DIR="${PGDATA_DIR:-$HOME/fahmai/pgdata}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-fahmai-postgres}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-pgvector/pgvector:pg16}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

START_EMBEDDING="${START_EMBEDDING:-1}"
EMBED_CONTAINER="${EMBED_CONTAINER:-fahmai-bge-m3-embed}"
EMBED_IMAGE="${EMBED_IMAGE:-ghcr.io/huggingface/text-embeddings-inference:1.7.2}"
EMBED_PORT="${EMBED_PORT:-8080}"
EMBED_MODEL_ID="${EMBED_MODEL_ID:-BAAI/bge-m3}"
EMBED_DTYPE="${EMBED_DTYPE:-float16}"
EMBED_BATCH_SIZE="${EMBED_BATCH_SIZE:-64}"
EMBED_EXPECTED_DIMENSION="${EMBED_EXPECTED_DIMENSION:-1024}"

LOAD_DATA="${LOAD_DATA:-0}"
GENERATE_EMBEDDINGS="${GENERATE_EMBEDDINGS:-0}"
UPLOAD_MSCHEMA="${UPLOAD_MSCHEMA:-1}"
RUN_SMOKE="${RUN_SMOKE:-1}"
RECREATE_CONTAINERS="${RECREATE_CONTAINERS:-0}"
TRUNCATE_BEFORE_LOAD="${TRUNCATE_BEFORE_LOAD:-0}"
RAG_CHUNK_CHARS="${RAG_CHUNK_CHARS:-2000}"
RAG_CHUNK_OVERLAP_CHARS="${RAG_CHUNK_OVERLAP_CHARS:-200}"
RAG_COMMIT_DOCS="${RAG_COMMIT_DOCS:-1000}"
RETRIEVAL_PROFILE="${RETRIEVAL_PROFILE:-bge_m3_v1}"
BGE_CHILD_CHARS="${BGE_CHILD_CHARS:-1600}"
BGE_CHILD_OVERLAP_CHARS="${BGE_CHILD_OVERLAP_CHARS:-40}"
BGE_CHILD_BATCH_SIZE="${BGE_CHILD_BATCH_SIZE:-2000}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

run_sql() {
  local sql="$1"
  docker exec -i "${POSTGRES_CONTAINER}" \
    psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 -c "${sql}"
}

run_migrations() {
  local migrations="$1"
  "${PYTHON_BIN}" scripts/apply_db_migrations.py --migrations "${migrations}" --verify
}

wait_for_postgres() {
  echo "Waiting for PostgreSQL"
  for _ in $(seq 1 90); do
    if docker exec "${POSTGRES_CONTAINER}" pg_isready -U "${DB_USER}" -d "${DB_NAME}" >/dev/null 2>&1; then
      echo "PostgreSQL is ready"
      return 0
    fi
    sleep 2
  done
  echo "PostgreSQL did not become ready in time" >&2
  exit 1
}

wait_for_embedding() {
  echo "Waiting for embedding endpoint"
  for _ in $(seq 1 180); do
    if EMBED_PORT="${EMBED_PORT}" EMBED_EXPECTED_DIMENSION="${EMBED_EXPECTED_DIMENSION}" "${PYTHON_BIN}" - <<'PY' >/dev/null 2>&1
import json
import os
import urllib.request

req = urllib.request.Request(
    f"http://localhost:{os.environ['EMBED_PORT']}/embed",
    data=json.dumps({"inputs": ["FahMai retrieval smoke test"]}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=10) as response:
    payload = json.loads(response.read().decode("utf-8"))
embedding = payload[0]["embedding"] if isinstance(payload[0], dict) else payload[0]
raise SystemExit(0 if len(embedding) == int(os.environ["EMBED_EXPECTED_DIMENSION"]) else 1)
PY
    then
      echo "Embedding endpoint is ready with ${EMBED_EXPECTED_DIMENSION} dimensions"
      return 0
    fi
    sleep 5
  done
  echo "Embedding endpoint did not become ready in time" >&2
  exit 1
}

main() {
  require_command docker
  require_command "${PYTHON_BIN}"

  if [[ -z "${FAHMAI_DB_PASSWORD:-}" ]]; then
    echo "Set FAHMAI_DB_PASSWORD before running this script" >&2
    exit 1
  fi
  if [[ "${RETRIEVAL_PROFILE}" != "bge_m3_v1" ]]; then
    echo "setup_b200_fahmai.sh supports RETRIEVAL_PROFILE=bge_m3_v1 only; use the embedding scripts directly for legacy profiles" >&2
    exit 1
  fi

  if [[ "${RECREATE_CONTAINERS}" == "1" ]]; then
    docker rm -f "${POSTGRES_CONTAINER}" >/dev/null 2>&1 || true
    docker rm -f "${EMBED_CONTAINER}" >/dev/null 2>&1 || true
  fi

  mkdir -p "${PGDATA_DIR}"

  if ! docker ps -a --format '{{.Names}}' | grep -qx "${POSTGRES_CONTAINER}"; then
    echo "Starting PostgreSQL container ${POSTGRES_CONTAINER}"
    docker run -d --name "${POSTGRES_CONTAINER}" \
      --restart unless-stopped \
      -e POSTGRES_DB="${DB_NAME}" \
      -e POSTGRES_USER="${DB_USER}" \
      -e POSTGRES_PASSWORD="${FAHMAI_DB_PASSWORD}" \
      -p "${DB_PORT}:5432" \
      -v "${PGDATA_DIR}:/var/lib/postgresql/data" \
      "${POSTGRES_IMAGE}"
  else
    echo "PostgreSQL container already exists"
    docker start "${POSTGRES_CONTAINER}" >/dev/null
  fi

  wait_for_postgres

  if [[ "${START_EMBEDDING}" == "1" ]]; then
    if ! docker ps -a --format '{{.Names}}' | grep -qx "${EMBED_CONTAINER}"; then
      echo "Starting embedding container ${EMBED_CONTAINER}"
      docker run -d --name "${EMBED_CONTAINER}" \
        --restart unless-stopped \
        --gpus all \
        -p "${EMBED_PORT}:80" \
        -v hf_cache:/data \
        "${EMBED_IMAGE}" \
        --model-id "${EMBED_MODEL_ID}" \
        --dtype "${EMBED_DTYPE}"
    else
      echo "Embedding container already exists"
      docker start "${EMBED_CONTAINER}" >/dev/null
    fi
    wait_for_embedding
  fi

  DB_PASSWORD_ENCODED="$("${PYTHON_BIN}" -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["FAHMAI_DB_PASSWORD"], safe=""))')"
  export DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD_ENCODED}@localhost:${DB_PORT}/${DB_NAME}"
  export RETRIEVAL_PROFILE
  export EMBEDDING_PROVIDER="tei"
  export EMBEDDING_ENDPOINT="http://localhost:${EMBED_PORT}/embed"
  export BGE_EMBEDDING_PROVIDER="tei"
  export BGE_EMBEDDING_REQUEST_MODEL="${BGE_EMBEDDING_REQUEST_MODEL:-baai/bge-m3}"
  export BGE_EMBEDDING_STORED_MODEL="${BGE_EMBEDDING_STORED_MODEL:-BAAI/bge-m3}"
  export BGE_EMBEDDING_DIMENSION="${BGE_EMBEDDING_DIMENSION:-${EMBED_EXPECTED_DIMENSION}}"

  "${PYTHON_BIN}" -m pip install -r requirements.txt
  run_migrations "schema"

  if [[ "${UPLOAD_MSCHEMA}" == "1" ]]; then
    "${PYTHON_BIN}" scripts/generate_fahmai_mschema.py --schema-mode model --strict-live
    "${PYTHON_BIN}" scripts/upload_mschema_artifacts.py --retrieval-profile "${RETRIEVAL_PROFILE}"
  fi

  if [[ "${LOAD_DATA}" == "1" ]]; then
    ingest_args=(--skip-rag)
    if [[ "${TRUNCATE_BEFORE_LOAD}" == "1" ]]; then
      ingest_args+=(--truncate)
    fi
    "${PYTHON_BIN}" scripts/ingest_fahmai_to_postgres.py "${ingest_args[@]}"
    "${PYTHON_BIN}" scripts/ingest_rag_batches.py \
      --chunk-chars "${RAG_CHUNK_CHARS}" \
      --chunk-overlap-chars "${RAG_CHUNK_OVERLAP_CHARS}" \
      --commit-docs "${RAG_COMMIT_DOCS}" \
      --load-entity-links
    "${PYTHON_BIN}" scripts/build_bge_parent_child_chunks.py \
      --profile "${RETRIEVAL_PROFILE}" \
      --replace-profile \
      --child-chars "${BGE_CHILD_CHARS}" \
      --child-overlap-chars "${BGE_CHILD_OVERLAP_CHARS}" \
      --batch-size "${BGE_CHILD_BATCH_SIZE}"
    run_migrations "003,004"
    run_sql "SELECT fah_sai_lpk_mart.refresh_all_materialized_views(false);"
  fi

  if [[ "${GENERATE_EMBEDDINGS}" == "1" ]]; then
    "${PYTHON_BIN}" scripts/embed_chunks_openai.py \
      --retrieval-profile "${RETRIEVAL_PROFILE}" \
      --provider tei \
      --endpoint "${EMBEDDING_ENDPOINT}" \
      --batch-size "${EMBED_BATCH_SIZE}" \
      --timeout-seconds 600 \
      --refresh-materialized
    run_migrations "011"
    run_sql "SELECT fah_sai_lpk_mart.refresh_all_materialized_views(false);"
    run_sql "SELECT fah_sai_lpk_audit.analyze_fahmai_model_tables();"
    if [[ "${RUN_SMOKE}" == "1" ]]; then
      "${PYTHON_BIN}" scripts/run_question.py \
        --retrieval-profile "${RETRIEVAL_PROFILE}" \
        --provider tei \
        --endpoint "${EMBEDDING_ENDPOINT}" \
        --question-id FAHMAI-Q-L1-001 \
        --run-label production-smoke-bge
    fi
  fi

  run_sql "SELECT to_regclass('fah_sai_lpk_core.fact_sales') AS core_fact_sales, to_regclass('fah_sai_lpk_rag.child_chunks') AS bge_child_chunks, to_regclass('fah_sai_lpk_rag.child_chunk_embeddings') AS bge_child_embeddings, to_regclass('fah_sai_lpk_eval.questions') AS eval_questions, to_regclass('fah_sai_lpk_model.sales_order_360') AS model_sales_order, to_regclass('fah_sai_lpk_meta.mschema_artifacts') AS mschema_artifacts;"
  run_sql "SELECT count(*) AS model_surface_count FROM information_schema.views WHERE table_schema = 'fah_sai_lpk_model';"
  run_sql "SELECT count(*) AS bge_child_chunks FROM fah_sai_lpk_rag.child_chunks WHERE retrieval_profile = '${RETRIEVAL_PROFILE}';"
  run_sql "SELECT count(*) AS bge_child_embeddings FROM fah_sai_lpk_rag.child_chunk_embeddings WHERE retrieval_profile = '${RETRIEVAL_PROFILE}';"
  run_sql "SELECT count(*) AS bad_bge_embedding_dims FROM fah_sai_lpk_rag.child_chunk_embeddings WHERE retrieval_profile = '${RETRIEVAL_PROFILE}' AND vector_dims(embedding) <> ${EMBED_EXPECTED_DIMENSION};"
  run_sql "SELECT artifact_format, relation_count, retrieval_profile FROM fah_sai_lpk_meta.mschema_artifacts WHERE artifact_name = 'fahmai_model_mschema' ORDER BY artifact_format;"
  run_sql "SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector','pgcrypto','pg_trgm') ORDER BY extname;"
  echo "FahMai B200 setup complete"
}

main "$@"
