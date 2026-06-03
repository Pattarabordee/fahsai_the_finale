#!/usr/bin/env python
"""Evaluate FahMai enterprise product readiness gates.

The script reads the current PostgreSQL database and prints JSON metrics that
can be used in deployment checks, demos, and product reviews.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit("Missing dependency: pip install psycopg[binary]") from exc


CHECKS = {
    "eval_questions": "SELECT count(*) AS value FROM fah_sai_lpk_eval.questions",
    "core_fact_sales": "SELECT count(*) AS value FROM fah_sai_lpk_core.fact_sales",
    "core_fact_sales_line_item": "SELECT count(*) AS value FROM fah_sai_lpk_core.fact_sales_line_item",
    "core_fact_bank_transaction": "SELECT count(*) AS value FROM fah_sai_lpk_core.fact_bank_transaction",
    "source_documents": "SELECT count(*) AS value FROM fah_sai_lpk_rag.source_documents",
    "document_chunks": "SELECT count(*) AS value FROM fah_sai_lpk_rag.document_chunks",
    "chunk_embeddings": "SELECT count(*) AS value FROM fah_sai_lpk_rag.chunk_embeddings",
    "bad_embedding_dims": "SELECT count(*) AS value FROM fah_sai_lpk_rag.chunk_embeddings WHERE vector_dims(embedding) <> 4096",
    "public_retrievable_chunks": "SELECT count(*) AS value FROM fah_sai_lpk_rag.v_public_retrievable_chunks",
    "model_surface_count": """
        SELECT count(*) AS value
        FROM information_schema.views
        WHERE table_schema = 'fah_sai_lpk_model'
    """,
    "model_sales_order": "SELECT count(*) AS value FROM fah_sai_lpk_model.sales_order_360",
    "model_sales_line": "SELECT count(*) AS value FROM fah_sai_lpk_model.sales_line_360",
    "model_finance_bank_events": """
        SELECT count(*) AS value
        FROM fah_sai_lpk_model.finance_event
        WHERE source_table = 'FACT_BANK_TRANSACTION'
    """,
    "model_document_distinct_chunks": "SELECT count(DISTINCT chunk_id) AS value FROM fah_sai_lpk_model.document_evidence",
    "answers_without_sources": """
        SELECT count(*) AS value
        FROM fah_sai_lpk_eval.answer_runs
        WHERE cardinality(source_paths) = 0
    """,
    "answer_runs": "SELECT count(*) AS value FROM fah_sai_lpk_eval.answer_runs",
}


def fetch_scalar_metrics(conn) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for name, sql in CHECKS.items():
            try:
                cur.execute(sql)
                metrics[name] = cur.fetchone()["value"]
            except Exception as exc:
                conn.rollback()
                metrics[name] = {"error": f"{type(exc).__name__}: {exc}"}
    return metrics


def fetch_answer_status_counts(conn) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        try:
            cur.execute(
                """
                SELECT status, count(*) AS count
                FROM fah_sai_lpk_eval.answer_runs
                GROUP BY status
                ORDER BY status
                """
            )
            return [dict(row) for row in cur.fetchall()]
        except Exception:
            conn.rollback()
            return []


def fetch_runtime_metrics(conn) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        try:
            cur.execute(
                """
                SELECT
                    avg(runtime_ms)::numeric(18,2) AS avg_runtime_ms,
                    percentile_cont(0.95) WITHIN GROUP (ORDER BY runtime_ms) AS p95_runtime_ms
                FROM fah_sai_lpk_eval.answer_runs
                WHERE runtime_ms IS NOT NULL
                """
            )
            row = cur.fetchone()
            return {key: float(value) if value is not None else None for key, value in row.items()}
        except Exception:
            conn.rollback()
            return {"avg_runtime_ms": None, "p95_runtime_ms": None}


def evaluate_gates(metrics: dict[str, Any]) -> dict[str, bool]:
    def numeric(name: str) -> int:
        value = metrics.get(name)
        return value if isinstance(value, int) else -1

    return {
        "has_100_questions": numeric("eval_questions") == 100,
        "has_core_sales": numeric("core_fact_sales") > 0,
        "has_public_chunks": numeric("document_chunks") > 0,
        "has_embeddings": numeric("chunk_embeddings") > 0,
        "embedding_dims_clean": numeric("bad_embedding_dims") == 0,
        "retrieval_view_populated_or_inspectable": numeric("public_retrievable_chunks") > 0,
        "model_surface_has_8_views": numeric("model_surface_count") == 8,
        "model_sales_order_matches_core": numeric("model_sales_order") == numeric("core_fact_sales"),
        "model_sales_line_matches_core": numeric("model_sales_line") == numeric("core_fact_sales_line_item"),
        "model_finance_bank_matches_core": numeric("model_finance_bank_events") == numeric("core_fact_bank_transaction"),
        "model_document_chunks_match_public_view": (
            numeric("model_document_distinct_chunks") == numeric("public_retrievable_chunks")
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("Set DATABASE_URL or pass --database-url")

    with psycopg.connect(args.database_url) as conn:
        metrics = fetch_scalar_metrics(conn)
        result = {
            "metrics": metrics,
            "answer_status_counts": fetch_answer_status_counts(conn),
            "runtime": fetch_runtime_metrics(conn),
            "gates": evaluate_gates(metrics),
        }

    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
