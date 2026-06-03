#!/usr/bin/env bash
# Bootstrap FahMai PostgreSQL + Qwen embeddings on a Linux B200 VM.
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
EMBED_CONTAINER="${EMBED_CONTAINER:-fahmai-qwen-embed}"
EMBED_IMAGE="${EMBED_IMAGE:-ghcr.io/huggingface/text-embeddings-inference:1.7.2}"
EMBED_PORT="${EMBED_PORT:-8080}"
EMBED_MODEL_ID="${EMBED_MODEL_ID:-Qwen/Qwen3-Embedding-8B}"
EMBED_DTYPE="${EMBED_DTYPE:-float16}"
EMBED_BATCH_SIZE="${EMBED_BATCH_SIZE:-512}"

LOAD_DATA="${LOAD_DATA:-0}"
GENERATE_EMBEDDINGS="${GENERATE_EMBEDDINGS:-0}"
RECREATE_CONTAINERS="${RECREATE_CONTAINERS:-0}"
TRUNCATE_BEFORE_LOAD="${TRUNCATE_BEFORE_LOAD:-0}"
RAG_CHUNK_CHARS="${RAG_CHUNK_CHARS:-2000}"
RAG_CHUNK_OVERLAP_CHARS="${RAG_CHUNK_OVERLAP_CHARS:-200}"
RAG_COMMIT_DOCS="${RAG_COMMIT_DOCS:-1000}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

run_sql_file() {
  local file="$1"
  echo "Applying ${file}"
  docker exec -i "${POSTGRES_CONTAINER}" \
    psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 < "${file}"
}

run_sql() {
  local sql="$1"
  docker exec -i "${POSTGRES_CONTAINER}" \
    psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 -c "${sql}"
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
    if EMBED_PORT="${EMBED_PORT}" "${PYTHON_BIN}" - <<'PY' >/dev/null 2>&1
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
raise SystemExit(0 if len(embedding) == 4096 else 1)
PY
    then
      echo "Embedding endpoint is ready with 4096 dimensions"
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

  run_sql_file "db/001_init_fahmai_model_schema.sql"
  run_sql_file "db/002_eval_retrieval_workflow.sql"
  run_sql_file "db/007_fact_date_convention.sql"
  run_sql_file "db/008_model_facing_schema.sql"

  DB_PASSWORD_ENCODED="$("${PYTHON_BIN}" -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["FAHMAI_DB_PASSWORD"], safe=""))')"
  export DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD_ENCODED}@localhost:${DB_PORT}/${DB_NAME}"
  export EMBEDDING_PROVIDER="tei"
  export EMBEDDING_ENDPOINT="http://localhost:${EMBED_PORT}/embed"

  "${PYTHON_BIN}" -m pip install -r requirements.txt

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
    run_sql_file "db/003_performance_indexes.sql"
    run_sql_file "db/004_materialized_marts.sql"
    run_sql "SELECT fah_sai_lpk_mart.refresh_all_materialized_views(false);"
  fi

  if [[ "${GENERATE_EMBEDDINGS}" == "1" ]]; then
    "${PYTHON_BIN}" scripts/embed_chunks_openai.py \
      --provider tei \
      --endpoint "${EMBEDDING_ENDPOINT}" \
      --batch-size "${EMBED_BATCH_SIZE}" \
      --timeout-seconds 600
    run_sql_file "db/005_rag_hnsw_and_public_chunks_mv.sql"
    run_sql "SELECT fah_sai_lpk_mart.refresh_all_materialized_views(false);"
    run_sql "SELECT fah_sai_lpk_audit.analyze_fahmai_model_tables();"
  fi

  run_sql "SELECT to_regclass('fah_sai_lpk_core.fact_sales') AS core_fact_sales, to_regclass('fah_sai_lpk_rag.chunk_embeddings') AS rag_chunk_embeddings, to_regclass('fah_sai_lpk_eval.questions') AS eval_questions, to_regclass('fah_sai_lpk_model.sales_order_360') AS model_sales_order;"
  run_sql "SELECT count(*) AS model_surface_count FROM information_schema.views WHERE table_schema = 'fah_sai_lpk_model';"
  run_sql "SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector','pgcrypto','pg_trgm') ORDER BY extname;"
  echo "FahMai B200 setup complete"
}

main "$@"
