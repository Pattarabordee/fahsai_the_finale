#!/usr/bin/env python
"""Audit and optionally repair an existing FahMai DB for RAG handoff.

The default mode is read-only. It never truncates data and never runs migration
006. Mutating operations require explicit flags.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.apply_db_migrations import run_migration_batch, verify_database
from scripts.evaluate_product_readiness import (
    evaluate_gates,
    fetch_answer_status_counts,
    fetch_runtime_metrics,
    fetch_scalar_metrics,
)

SAFE_FULL_MIGRATIONS = ["001", "002", "003", "004", "005"]

EXPECTED_CORE_TABLES = [
    "dim_branch",
    "dim_department",
    "dim_position_level",
    "dim_date",
    "dim_vendor",
    "dim_bank_account",
    "dim_employee",
    "dim_customer",
    "dim_policy_version",
    "dim_product",
    "dim_promo_campaign",
    "dim_vendor_contract_version",
    "dim_care_plus_sku_tier",
    "dim_product_recall_history",
    "dim_promo_mechanic",
    "dim_signing_authority_ladder",
    "fact_bank_transaction",
    "fact_sales",
    "fact_sales_line_item",
    "fact_payroll",
    "fact_loyalty_ledger",
    "fact_promo_redemption",
    "fact_shipping",
    "fact_inventory_monthly_snapshot",
    "fact_inventory_movement",
    "fact_warranty_claim",
    "fact_return",
    "fact_cs_interaction",
    "fact_refund_paid",
    "fact_vendor_payment",
    "t2_doc_inventory",
]


def import_psycopg():
    try:
        import psycopg
        from psycopg.rows import dict_row

        return psycopg, dict_row
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise SystemExit("Missing dependency: pip install psycopg[binary]") from exc


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def run_command(args: list[str], env: dict[str, str] | None = None, timeout: int | None = None) -> dict[str, Any]:
    started_args = " ".join(args)
    try:
        completed = subprocess.run(
            args,
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "command": started_args,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
            "ok": completed.returncode == 0,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": started_args,
            "returncode": None,
            "stdout": (exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
            "stderr": "command timed out",
            "ok": False,
        }


def scalar(conn, sql: str, params: tuple[Any, ...] = ()) -> Any:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None


def check_core_tables(conn) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    missing: list[str] = []
    empty: list[str] = []
    for table in EXPECTED_CORE_TABLES:
        qualified = f"fah_sai_lpk_core.{table}"
        exists = scalar(conn, "SELECT to_regclass(%s)::text", (qualified,))
        if not exists:
            missing.append(qualified)
            tables[qualified] = {"exists": False, "rows": None}
            continue
        count = scalar(conn, f"SELECT count(*) FROM {qualified}")
        if count == 0:
            empty.append(qualified)
        tables[qualified] = {"exists": True, "rows": count}

    return {
        "expected_count": len(EXPECTED_CORE_TABLES),
        "missing": missing,
        "empty": empty,
        "tables": tables,
        "ok": not missing and not empty,
    }


def check_mart_grains(conn) -> dict[str, Any]:
    comparisons = {
        "sales_order": ("fah_sai_lpk_mart.v_sales_order", "fah_sai_lpk_core.fact_sales"),
        "sales_line": ("fah_sai_lpk_mart.v_sales_line", "fah_sai_lpk_core.fact_sales_line_item"),
        "bank_reconciliation": ("fah_sai_lpk_mart.v_bank_reconciliation", "fah_sai_lpk_core.fact_bank_transaction"),
    }
    results: dict[str, Any] = {}
    for name, (mart_view, core_table) in comparisons.items():
        try:
            mart_count = scalar(conn, f"SELECT count(*) FROM {mart_view}")
            core_count = scalar(conn, f"SELECT count(*) FROM {core_table}")
            results[name] = {
                "mart": mart_view,
                "mart_rows": mart_count,
                "core": core_table,
                "core_rows": core_count,
                "ok": mart_count == core_count,
            }
        except Exception as exc:
            conn.rollback()
            results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return results


def check_retrieval(conn) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    queries = {
        "public_view_rows": "SELECT count(*) FROM fah_sai_lpk_rag.v_public_retrievable_chunks",
        "public_mv_rows": "SELECT count(*) FROM fah_sai_lpk_rag.mv_public_retrievable_chunks",
        "unsafe_public_view_rows": """
            SELECT count(*)
            FROM fah_sai_lpk_rag.v_public_retrievable_chunks v
            JOIN fah_sai_lpk_rag.document_chunks c ON c.chunk_id = v.chunk_id
            JOIN fah_sai_lpk_rag.source_documents d ON d.source_document_id = c.source_document_id
            WHERE c.is_public_safe IS DISTINCT FROM true
               OR d.is_public_safe IS DISTINCT FROM true
        """,
        "text_search_rows": "SELECT count(*) FROM fah_sai_lpk_rag.search_public_chunks_text('FahMai', 3)",
        "vector_match_rows": """
            WITH q AS (
                SELECT embedding
                FROM fah_sai_lpk_rag.chunk_embeddings
                LIMIT 1
            )
            SELECT count(*)
            FROM q, LATERAL fah_sai_lpk_rag.match_public_chunks(q.embedding, 3, 20)
        """,
    }
    for name, sql in queries.items():
        try:
            checks[name] = {"value": scalar(conn, sql), "ok": True}
        except Exception as exc:
            conn.rollback()
            checks[name] = {"value": None, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

    checks["retrieval_ok"] = {
        "ok": (
            checks.get("public_view_rows", {}).get("value", 0) > 0
            and checks.get("public_mv_rows", {}).get("value", 0) > 0
            and checks.get("unsafe_public_view_rows", {}).get("value") == 0
            and checks.get("text_search_rows", {}).get("value", 0) > 0
            and checks.get("vector_match_rows", {}).get("value", 0) > 0
        )
    }
    return checks


def refresh_materialized(conn) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        scalar(conn, "SELECT fah_sai_lpk_mart.refresh_all_materialized_views(false)")
        conn.commit()
        result["refresh_all_materialized_views"] = {"ok": True}
    except Exception as exc:
        conn.rollback()
        result["refresh_all_materialized_views"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    try:
        scalar(conn, "SELECT fah_sai_lpk_audit.analyze_fahmai_model_tables()")
        conn.commit()
        result["analyze_fahmai_model_tables"] = {"ok": True}
    except Exception as exc:
        conn.rollback()
        result["analyze_fahmai_model_tables"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return result


def schema_missing(verification: dict[str, Any]) -> bool:
    required = [
        "core_fact_sales",
        "rag_chunk_embeddings",
        "eval_questions",
        "rag_public_view",
        "rag_public_mv",
        "vector_extension",
        "pgcrypto_extension",
        "pg_trgm_extension",
    ]
    return any(not verification.get(key) or isinstance(verification.get(key), dict) for key in required)


def run_embedding_dry_run(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    return run_command(
        [
            sys.executable,
            "scripts/embed_chunks_openai.py",
            "--provider",
            args.embedding_provider,
            "--endpoint",
            args.embedding_endpoint,
            "--batch-size",
            str(args.embedding_batch_size),
            "--dry-run",
        ],
        env=env,
        timeout=args.command_timeout_seconds,
    )


def run_embedding(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    return run_command(
        [
            sys.executable,
            "scripts/embed_chunks_openai.py",
            "--provider",
            args.embedding_provider,
            "--endpoint",
            args.embedding_endpoint,
            "--batch-size",
            str(args.embedding_batch_size),
        ],
        env=env,
        timeout=args.command_timeout_seconds,
    )


def run_harness(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    base = [
        sys.executable,
        "scripts/run_question.py",
        "--provider",
        args.embedding_provider,
        "--endpoint",
        args.embedding_endpoint,
        "--match-count",
        str(args.match_count),
    ]
    result["smoke"] = run_command(
        base
        + [
            "--question-id",
            args.smoke_question_id,
            "--run-label",
            f"{args.run_label_prefix}-smoke",
            "--json",
        ],
        env=env,
        timeout=args.command_timeout_seconds,
    )
    if args.full_harness:
        result["full"] = run_command(
            base
            + [
                "--all",
                "--limit",
                str(args.harness_limit),
                "--run-label",
                f"{args.run_label_prefix}-full",
                "--json",
            ],
            env=env,
            timeout=args.command_timeout_seconds,
        )
    return result


def fetch_harness_counts(conn, run_label_prefix: str) -> dict[str, Any]:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    run_label,
                    count(*) AS run_count,
                    count(*) FILTER (WHERE cardinality(source_paths) > 0) AS runs_with_sources,
                    count(*) FILTER (WHERE cardinality(template_names) > 0) AS runs_with_templates,
                    min(created_at) AS first_run_at,
                    max(created_at) AS last_run_at
                FROM fah_sai_lpk_eval.answer_runs
                WHERE run_label IN (%s, %s)
                GROUP BY run_label
                ORDER BY run_label
                """,
                (f"{run_label_prefix}-smoke", f"{run_label_prefix}-full"),
            )
            columns = [desc.name for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        return {"ok": True, "rows": json_safe(rows)}
    except Exception as exc:
        conn.rollback()
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def score_report(report: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []

    if report.get("schema_missing_after_repair"):
        blockers.append("Required schema objects/extensions are missing.")
    if not report.get("core_tables", {}).get("ok"):
        blockers.append("Not all expected core tables exist and contain rows.")

    metrics = report.get("readiness", {}).get("metrics", {})
    gates = report.get("readiness", {}).get("gates", {})
    if not gates.get("has_100_questions"):
        blockers.append("fah_sai_lpk_eval.questions does not contain exactly 100 questions.")
    if not gates.get("has_embeddings"):
        blockers.append("fah_sai_lpk_rag.chunk_embeddings is empty.")
    if not gates.get("embedding_dims_clean"):
        blockers.append("Some embeddings are not 4096-dimensional.")

    mart_grains = report.get("mart_grains", {})
    if any(not item.get("ok") for item in mart_grains.values()):
        blockers.append("One or more mart views do not preserve expected grain counts.")

    retrieval_ok = report.get("retrieval", {}).get("retrieval_ok", {}).get("ok")
    if not retrieval_ok:
        blockers.append("Retrieval views/functions are not fully usable.")

    if isinstance(metrics.get("answers_without_sources"), int) and metrics["answers_without_sources"] > 0:
        warnings.append("Some fah_sai_lpk_eval.answer_runs have no source paths.")

    harness_rows = report.get("harness_counts", {}).get("rows", [])
    full_rows = [row for row in harness_rows if row.get("run_label", "").endswith("-full")]
    if report.get("harness_requested") and (not full_rows or full_rows[0].get("run_count", 0) < report.get("harness_limit", 100)):
        blockers.append("Full harness run did not persist the requested number of answer runs.")

    if blockers:
        score = 69 if len(blockers) <= 2 else 49
        band = "blocked" if score < 50 else "risky"
    elif warnings:
        score = 90
        band = "strong with caveats"
    else:
        score = 100
        band = "handoff ready"

    return {"score": score, "band": band, "blockers": blockers, "warnings": warnings}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="Existing PostgreSQL DATABASE_URL")
    parser.add_argument("--dry-run", action="store_true", help="Show safe migration plan and exit without connecting")
    parser.add_argument("--repair-schema", action="store_true", help="Apply allowlisted migrations 001-005 if schema objects are missing")
    parser.add_argument("--refresh-materialized", action="store_true", help="Refresh materialized views and analyze model tables")
    parser.add_argument("--embed-missing", action="store_true", help="Run embedding dry-run, then embed missing chunks")
    parser.add_argument("--run-harness", action="store_true", help="Run smoke harness and optionally the full harness")
    parser.add_argument("--full-harness", action="store_true", help="With --run-harness, run --all using --harness-limit")
    parser.add_argument("--harness-limit", type=int, default=100)
    parser.add_argument("--run-label-prefix", default="existing-db")
    parser.add_argument("--smoke-question-id", default="FAHMAI-Q-L1-001")
    parser.add_argument("--embedding-provider", default=os.getenv("EMBEDDING_PROVIDER", "tei"), choices=["tei", "openai-compatible"])
    parser.add_argument("--embedding-endpoint", default=os.getenv("EMBEDDING_ENDPOINT", "http://localhost:8080/embed"))
    parser.add_argument("--embedding-batch-size", type=int, default=64)
    parser.add_argument("--match-count", type=int, default=8)
    parser.add_argument("--command-timeout-seconds", type=int, default=3600)
    parser.add_argument("--report-path", help="Optional JSON report path")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    args = parser.parse_args()

    if args.full_harness and not args.run_harness:
        raise SystemExit("--full-harness requires --run-harness")
    if args.harness_limit < 1:
        raise SystemExit("--harness-limit must be >= 1")
    if args.embedding_batch_size < 1:
        raise SystemExit("--embedding-batch-size must be >= 1")
    if args.command_timeout_seconds < 1:
        raise SystemExit("--command-timeout-seconds must be >= 1")
    return args


def main() -> int:
    args = parse_args()
    plan = run_migration_batch(None, "full", dry_run=True, verbose=False)
    planned = plan["selected_migrations"]
    if planned != SAFE_FULL_MIGRATIONS:
        raise SystemExit(f"Unsafe migration plan: expected {SAFE_FULL_MIGRATIONS}, got {planned}")

    report: dict[str, Any] = {
        "mode": "existing-db-rag-handoff",
        "safe_migrations": planned,
        "dry_run_plan": plan,
        "mutations_requested": {
            "repair_schema": args.repair_schema,
            "refresh_materialized": args.refresh_materialized,
            "embed_missing": args.embed_missing,
            "run_harness": args.run_harness,
            "full_harness": args.full_harness,
        },
        "harness_requested": args.run_harness,
        "harness_limit": args.harness_limit,
    }

    if args.dry_run:
        report["score"] = {"score": None, "band": "dry-run", "blockers": [], "warnings": []}
        print(json.dumps(json_safe(report), ensure_ascii=False, indent=2))
        return 0

    if not args.database_url:
        raise SystemExit("Set DATABASE_URL or pass --database-url")

    env = os.environ.copy()
    env["DATABASE_URL"] = args.database_url

    psycopg, dict_row = import_psycopg()
    with psycopg.connect(args.database_url) as conn:
        report["verification_before"] = verify_database(conn)
        missing_before = schema_missing(report["verification_before"])
        report["schema_missing_before_repair"] = missing_before

        if missing_before and args.repair_schema:
            report["schema_repair"] = run_migration_batch(
                args.database_url,
                "full",
                dry_run=False,
                verify=True,
                verbose=True,
            )
            report["verification_after_repair"] = verify_database(conn)
        else:
            report["verification_after_repair"] = report["verification_before"]

        report["schema_missing_after_repair"] = schema_missing(report["verification_after_repair"])

        if args.refresh_materialized:
            report["refresh"] = refresh_materialized(conn)

        report["readiness"] = {
            "metrics": fetch_scalar_metrics(conn),
            "answer_status_counts": fetch_answer_status_counts(conn),
            "runtime": fetch_runtime_metrics(conn),
        }
        report["readiness"]["gates"] = evaluate_gates(report["readiness"]["metrics"])
        report["core_tables"] = check_core_tables(conn)
        report["mart_grains"] = check_mart_grains(conn)
        report["retrieval"] = check_retrieval(conn)

    if args.embed_missing:
        report["embedding_dry_run"] = run_embedding_dry_run(args, env)
        if report["embedding_dry_run"]["ok"]:
            report["embedding_run"] = run_embedding(args, env)

    if args.run_harness:
        report["harness_run"] = run_harness(args, env)
        with psycopg.connect(args.database_url) as conn:
            report["harness_counts"] = fetch_harness_counts(conn, args.run_label_prefix)
    else:
        with psycopg.connect(args.database_url) as conn:
            report["harness_counts"] = fetch_harness_counts(conn, args.run_label_prefix)

    report["score"] = score_report(report)

    if args.report_path:
        report_path = Path(args.report_path)
        if not report_path.is_absolute():
            report_path = ROOT / report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(json_safe(report), ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(report_path)

    if args.json:
        print(json.dumps(json_safe(report), ensure_ascii=False, indent=2))
    else:
        score = report["score"]
        print(f"RAG handoff audit: {score['score']}/100, {score['band']}")
        for blocker in score["blockers"]:
            print(f"BLOCKER: {blocker}")
        for warning in score["warnings"]:
            print(f"WARNING: {warning}")
        if args.report_path:
            print(f"Report: {report['report_path']}")

    return 0 if report["score"]["score"] == 100 else 1


if __name__ == "__main__":
    sys.exit(main())
