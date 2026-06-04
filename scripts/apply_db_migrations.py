#!/usr/bin/env python
"""Apply approved FahMai database migrations to a remote PostgreSQL database.

This is the safe "API" for remote table creation in this repository: it uses
the PostgreSQL protocol through psycopg and only runs versioned SQL files from
the allowlist below. It intentionally does not accept raw SQL input.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

MIGRATIONS: dict[str, Path] = {
    "001": ROOT / "db" / "001_init_fahmai_model_schema.sql",
    "002": ROOT / "db" / "002_eval_retrieval_workflow.sql",
    "003": ROOT / "db" / "003_performance_indexes.sql",
    "004": ROOT / "db" / "004_materialized_marts.sql",
    "005": ROOT / "db" / "005_rag_hnsw_and_public_chunks_mv.sql",
    "006": ROOT / "db" / "006_switch_to_qwen3_embedding_8b.sql",
    "007": ROOT / "db" / "007_fact_date_convention.sql",
    "008": ROOT / "db" / "008_model_facing_schema.sql",
    "009": ROOT / "db" / "009_ocr_artifact_schema.sql",
    "010": ROOT / "db" / "010_rag_bge_m3_parent_child.sql",
    "011": ROOT / "db" / "011_rag_bge_m3_hnsw.sql",
    "012": ROOT / "db" / "012_rag_bge_m3_compact_child_spans.sql",
    "013": ROOT / "db" / "013_model_schema_prompt_hygiene.sql",
    "014": ROOT / "db" / "014_mschema_artifacts.sql",
}

DEFAULT_SCHEMA_MIGRATIONS = ["001", "002", "007", "008", "009", "010", "012", "013", "014"]
DEFAULT_FULL_MIGRATIONS = [
    "001",
    "002",
    "007",
    "003",
    "004",
    "005",
    "008",
    "009",
    "010",
    "012",
    "013",
    "014",
    "011",
]


def import_psycopg():
    try:
        import psycopg

        return psycopg
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise SystemExit("Missing dependency: pip install psycopg[binary]") from exc


def parse_migration_selection(selection: str) -> list[str]:
    if selection == "schema":
        return DEFAULT_SCHEMA_MIGRATIONS
    if selection == "full":
        return DEFAULT_FULL_MIGRATIONS

    selected = [item.strip() for item in selection.split(",") if item.strip()]
    unknown = [item for item in selected if item not in MIGRATIONS]
    if unknown:
        allowed = ", ".join(MIGRATIONS)
        raise SystemExit(f"Unknown migration(s): {', '.join(unknown)}. Allowed: {allowed}, schema, full")
    return selected


def read_migration_sql(key: str) -> str:
    path = MIGRATIONS[key]
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def planned_migrations(selected: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "migration": key,
            "path": MIGRATIONS[key].relative_to(ROOT).as_posix(),
            "status": "planned",
        }
        for key in selected
    ]


def apply_migrations(conn, selected: list[str], verbose: bool = True) -> list[dict[str, Any]]:
    results = []
    for key in selected:
        path = MIGRATIONS[key]
        entry: dict[str, Any] = {
            "migration": key,
            "path": path.relative_to(ROOT).as_posix(),
            "status": "running",
        }
        with conn.transaction():
            with conn.cursor() as cur:
                if verbose:
                    print(f"applying {entry['path']}", flush=True)
                cur.execute(read_migration_sql(key))
                entry["status"] = "applied"
        if verbose:
            print(f"applied {entry['path']}", flush=True)
        results.append(entry)
    return results


def verify_database(conn) -> dict[str, Any]:
    from psycopg.rows import dict_row

    checks = {
        "core_fact_sales": "SELECT to_regclass('fah_sai_lpk_core.fact_sales')::text AS value",
        "rag_chunk_embeddings": "SELECT to_regclass('fah_sai_lpk_rag.chunk_embeddings')::text AS value",
        "eval_questions": "SELECT to_regclass('fah_sai_lpk_eval.questions')::text AS value",
        "rag_public_view": "SELECT to_regclass('fah_sai_lpk_rag.v_public_retrievable_chunks')::text AS value",
        "rag_public_mv": "SELECT to_regclass('fah_sai_lpk_rag.mv_public_retrievable_chunks')::text AS value",
        "model_sales_order": "SELECT to_regclass('fah_sai_lpk_model.sales_order_360')::text AS value",
        "model_document_evidence": "SELECT to_regclass('fah_sai_lpk_model.document_evidence')::text AS value",
        "ocr_artifact_predictions": "SELECT to_regclass('fah_sai_lpk_ocr.artifact_predictions')::text AS value",
        "ocr_summary_view": "SELECT to_regclass('fah_sai_lpk_ocr.v_ocr_artifact_summary')::text AS value",
        "bge_child_chunks": "SELECT to_regclass('fah_sai_lpk_rag.child_chunks')::text AS value",
        "bge_child_embeddings": "SELECT to_regclass('fah_sai_lpk_rag.child_chunk_embeddings')::text AS value",
        "bge_public_view": "SELECT to_regclass('fah_sai_lpk_rag.v_public_retrievable_child_chunks_bge_m3')::text AS value",
        "bge_match_function": "SELECT to_regprocedure('fah_sai_lpk_rag.match_public_chunks_bge_m3(vector,integer,integer)')::text AS value",
        "bge_hnsw_index": "SELECT to_regclass('fah_sai_lpk_rag.child_chunk_embeddings_bge_m3_embedding_hnsw_idx')::text AS value",
        "mschema_artifacts": "SELECT to_regclass('fah_sai_lpk_meta.mschema_artifacts')::text AS value",
        "mschema_current_view": "SELECT to_regclass('fah_sai_lpk_meta.v_current_mschema_artifacts')::text AS value",
        "model_surface_count": (
            "SELECT count(*)::text AS value "
            "FROM information_schema.views "
            "WHERE table_schema = 'fah_sai_lpk_model'"
        ),
        "vector_extension": "SELECT extversion AS value FROM pg_extension WHERE extname = 'vector'",
        "pgcrypto_extension": "SELECT extversion AS value FROM pg_extension WHERE extname = 'pgcrypto'",
        "pg_trgm_extension": "SELECT extversion AS value FROM pg_extension WHERE extname = 'pg_trgm'",
    }
    output: dict[str, Any] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for name, sql in checks.items():
            try:
                cur.execute(sql)
                row = cur.fetchone()
                output[name] = row["value"] if row else None
            except Exception as exc:
                conn.rollback()
                output[name] = {"error": f"{type(exc).__name__}: {exc}"}
    return output


def run_migration_batch(
    database_url: str | None,
    selection: str,
    dry_run: bool = False,
    verify: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    selected = parse_migration_selection(selection)
    result: dict[str, Any] = {"selected_migrations": selected}

    if dry_run:
        result["migrations"] = planned_migrations(selected)
        return result

    if not database_url:
        raise SystemExit("Set DATABASE_URL or pass --database-url")

    psycopg = import_psycopg()
    with psycopg.connect(database_url) as conn:
        result["migrations"] = apply_migrations(conn, selected, verbose=verbose)
        if verify:
            result["verification"] = verify_database(conn)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="PostgreSQL connection URL")
    parser.add_argument(
        "--migrations",
        default="schema",
        help="schema, full, or comma-separated migration ids such as 001,002,003",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show migrations that would be applied")
    parser.add_argument("--verify", action="store_true", help="Run schema/extension verification after apply")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON result")
    args = parser.parse_args()

    result = run_migration_batch(
        database_url=args.database_url,
        selection=args.migrations,
        dry_run=args.dry_run,
        verify=args.verify,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.dry_run:
        for entry in result["migrations"]:
            print(f"would apply {entry['path']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
