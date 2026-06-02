#!/usr/bin/env python
"""Load the FahMai public bundle into the local PostgreSQL model schema.

Prerequisites:
  pip install psycopg[binary]

Usage:
  $env:DATABASE_URL = "postgresql://user:pass@localhost:5432/fahmai"
  python scripts/ingest_fahmai_to_postgres.py --truncate
  python scripts/ingest_fahmai_to_postgres.py --truncate --refresh-materialized

This script loads:
  - official CSVs into raw.* and core.*
  - questions.csv into eval.questions/eval.question_tags
  - public markdown docs/reports/logs into rag.source_documents/document_chunks
  - derived public-safe entity links into rag.entity_links
  - unsafe provenance links into audit.provenance_entity_links

It does not generate embeddings. Run scripts/embed_chunks_openai.py after this.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Iterable

try:
    import psycopg
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit("Missing dependency: pip install psycopg[binary]") from exc


ROOT = Path(__file__).resolve().parents[1]
TABLES_DIR = ROOT / "super-ai-engineer-season-6-fah-mai-the-finale" / "tables"
PUBLIC_BUNDLE_DIR = ROOT / "super-ai-engineer-season-6-fah-mai-the-finale"
QUESTIONS_CSV = ROOT / "questions.csv"
DERIVED_DIR = ROOT / "derived"

OFFICIAL_TABLES = [
    "DIM_BANK_ACCOUNT",
    "DIM_BRANCH",
    "dim_care_plus_sku_tier",
    "DIM_CUSTOMER",
    "DIM_DATE",
    "DIM_DEPARTMENT",
    "DIM_EMPLOYEE",
    "DIM_POLICY_VERSION",
    "DIM_POSITION_LEVEL",
    "DIM_PRODUCT",
    "dim_product_recall_history",
    "DIM_PROMO_CAMPAIGN",
    "dim_promo_mechanic",
    "dim_signing_authority_ladder",
    "DIM_VENDOR",
    "DIM_VENDOR_CONTRACT_VERSION",
    "FACT_BANK_TRANSACTION",
    "FACT_CS_INTERACTION",
    "FACT_INVENTORY_MONTHLY_SNAPSHOT",
    "FACT_INVENTORY_MOVEMENT",
    "FACT_LOYALTY_LEDGER",
    "FACT_PAYROLL",
    "FACT_PROMO_REDEMPTION",
    "FACT_REFUND_PAID",
    "FACT_RETURN",
    "FACT_SALES",
    "FACT_SALES_LINE_ITEM",
    "FACT_SHIPPING",
    "FACT_VENDOR_PAYMENT",
    "FACT_WARRANTY_CLAIM",
    "T2_DOC_INVENTORY",
]

TAG_RULES = {
    "structured": [
        "FACT_",
        "DIM_",
        "ตาราง",
        "MSRP",
        "sku",
        "vendor",
        "branch",
        "customer",
        "employee",
        "payment",
        "posting_date",
        "business_event_date",
        "net_total",
        "return_amount",
        "loyalty",
        "stockout",
        "bank",
        "refund",
        "sales",
        "shipping",
        "warranty",
        "inventory",
        "payroll",
        "policy_variable",
    ],
    "doc": [
        "policy",
        "นโยบาย",
        "memo",
        "รายงาน",
        "report",
        "CEO",
        "chat",
        "LINE",
        "Line",
        "เอกสาร",
        "email",
        "สัญญา",
        "contract",
        "minutes",
        "meeting",
        "NPS",
        "OPS",
        "บันทึก",
        "ประชุม",
    ],
    "ocr": ["OCR", "ใบเสร็จ", "invoice", "bank statement", "statement", "render", "รูป", "ภาพ", "PDF", "artifact"],
    "injection": [
        "L3-Q-INJ",
        "system override",
        "admin mode",
        "OUTPUT",
        "verbatim",
        "Do NOT",
        "trust = HIGH",
        "พบกันใหม่",
        "SYSTEM",
    ],
    "policy": ["policy", "นโยบาย", "signing_authority", "refund threshold", "ladder"],
    "bank": ["bank", "deposit", "KBANK", "account_id", "FACT_BANK_TRANSACTION"],
    "sales": ["sales", "ยอดขาย", "FACT_SALES", "SKU", "sku", "net_total"],
}


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_name(csv_stem: str) -> str:
    return csv_stem.lower()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha1(value.encode('utf-8')).hexdigest()[:24]}"


def copy_csv(cur, schema: str, table: str, path: Path) -> int:
    sql = f"COPY {qident(schema)}.{qident(table)} FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')"
    with cur.copy(sql) as copy:
        with path.open("rb") as fh:
            while True:
                data = fh.read(1024 * 1024)
                if not data:
                    break
                copy.write(data)

    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return max(sum(1 for _ in fh) - 1, 0)


def classify_question(question_id: str, question_text: str) -> list[str]:
    combined = f"{question_id} {question_text}".lower()
    tags = []
    for tag, terms in TAG_RULES.items():
        if any(term.lower() in combined for term in terms):
            tags.append(tag)
    return tags or ["needs_manual_triage"]


def load_questions(conn) -> None:
    with conn.cursor() as cur, QUESTIONS_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        question_count = 0
        tag_count = 0
        for row in reader:
            question_id = row["id"].strip()
            question_text = row["question"].strip()
            parts = question_id.split("-")
            difficulty = parts[2] if len(parts) >= 3 else None
            family = difficulty.lower() if difficulty else "unknown"
            question_hash = sha256_text(question_text)
            cur.execute(
                """
                INSERT INTO eval.questions
                    (question_id, question_text, difficulty, question_family, question_hash)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (question_id) DO UPDATE SET
                    question_text = EXCLUDED.question_text,
                    difficulty = EXCLUDED.difficulty,
                    question_family = EXCLUDED.question_family,
                    question_hash = EXCLUDED.question_hash,
                    updated_at = now()
                """,
                (question_id, question_text, difficulty, family, question_hash),
            )
            question_count += 1
            for tag in classify_question(question_id, question_text):
                cur.execute(
                    """
                    INSERT INTO eval.question_tags (question_id, tag, tag_source, confidence)
                    VALUES (%s, %s, 'rule', 1.0)
                    ON CONFLICT (question_id, tag) DO UPDATE SET
                        tag_source = EXCLUDED.tag_source,
                        confidence = EXCLUDED.confidence
                    """,
                    (question_id, tag),
                )
                tag_count += 1
        print(f"loaded questions: {question_count}, tags: {tag_count}")


def markdown_paths() -> Iterable[Path]:
    for subdir in ["docs", "reports", "logs"]:
        base = PUBLIC_BUNDLE_DIR / subdir
        if base.exists():
            yield from sorted(base.rglob("*.md"))


def source_kind_for(path: Path) -> str:
    rel = path.relative_to(ROOT)
    parts = rel.parts
    if "reports" in parts:
        return "report_md"
    if "logs" in parts:
        return "log_md"
    if "docs" in parts:
        docs_idx = parts.index("docs")
        if len(parts) > docs_idx + 1:
            return f"doc_{parts[docs_idx + 1]}"
    return "markdown"


def chunk_text(text: str, chunk_chars: int, overlap_chars: int) -> list[tuple[int, int, str]]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    chunks = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_chars, len(normalized))
        if end < len(normalized):
            newline = normalized.rfind("\n", start, end)
            if newline > start + int(chunk_chars * 0.5):
                end = newline
        piece = normalized[start:end].strip()
        if piece:
            chunks.append((start, end, piece))
        if end >= len(normalized):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def load_markdown_documents(conn, chunk_chars: int, overlap_chars: int) -> None:
    document_count = 0
    chunk_count = 0
    with conn.cursor() as cur:
        for path in markdown_paths():
            rel_path = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            source_document_id = stable_id("doc", rel_path)
            content_sha = sha256_text(text)
            source_kind = source_kind_for(path)

            cur.execute(
                """
                INSERT INTO rag.source_documents
                    (source_document_id, source_path, source_kind, is_public_safe, safety_tier, content_sha256)
                VALUES (%s, %s, %s, true, 'official', %s)
                ON CONFLICT (source_path) DO UPDATE SET
                    source_kind = EXCLUDED.source_kind,
                    is_public_safe = true,
                    safety_tier = 'official',
                    content_sha256 = EXCLUDED.content_sha256,
                    updated_at = now()
                RETURNING source_document_id
                """,
                (source_document_id, rel_path, source_kind, content_sha),
            )
            actual_source_document_id = cur.fetchone()[0]
            cur.execute("DELETE FROM rag.document_chunks WHERE source_document_id = %s", (actual_source_document_id,))

            for idx, (start, end, piece) in enumerate(chunk_text(text, chunk_chars, overlap_chars)):
                chunk_id = stable_id("chunk", f"{rel_path}:{idx}:{sha256_text(piece)}")
                token_estimate = max(1, len(piece) // 4)
                cur.execute(
                    """
                    INSERT INTO rag.document_chunks
                        (chunk_id, source_document_id, chunk_index, chunk_text, token_count,
                         char_start, char_end, language_hint, is_public_safe)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'th-en', true)
                    """,
                    (chunk_id, actual_source_document_id, idx, piece, token_estimate, start, end),
                )
                chunk_count += 1
            document_count += 1
    print(f"loaded markdown documents: {document_count}, chunks: {chunk_count}")


def parse_bool(value: str | None) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def load_entity_links(conn) -> None:
    link_files = [DERIVED_DIR / "DOC_ENTITY_LINKS.csv", DERIVED_DIR / "ARTIFACT_ENTITY_LINKS.csv"]
    public_count = 0
    unsafe_count = 0
    with conn.cursor() as cur:
        cur.execute("SELECT source_path, source_document_id FROM rag.source_documents")
        source_id_by_path = {row[0]: row[1] for row in cur.fetchall()}

        for path in link_files:
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    source_path = (row.get("source_path") or "").strip()
                    source_document_id = source_id_by_path.get(source_path)
                    artifact_id = (row.get("artifact_id") or row.get("source_doc_id") or "").strip() or None
                    is_public_safe = parse_bool(row.get("is_public_safe"))
                    if is_public_safe:
                        cur.execute(
                            """
                            INSERT INTO rag.entity_links
                                (source_document_id, artifact_id, source_path, source_type, entity_type,
                                 entity_id, linked_table, linked_column, link_method, confidence,
                                 is_public_safe, notes)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s)
                            """,
                            (
                                source_document_id,
                                artifact_id,
                                source_path,
                                row.get("source_type"),
                                row.get("entity_type"),
                                row.get("entity_id"),
                                row.get("linked_table"),
                                row.get("linked_column"),
                                row.get("link_method"),
                                row.get("confidence") or "1.0",
                                row.get("notes"),
                            ),
                        )
                        public_count += 1
                    else:
                        cur.execute(
                            """
                            INSERT INTO audit.provenance_entity_links
                                (artifact_id, source_path, source_type, entity_type, entity_id,
                                 linked_table, linked_column, link_method, confidence,
                                 is_public_safe, notes)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, false, %s)
                            """,
                            (
                                artifact_id,
                                source_path,
                                row.get("source_type"),
                                row.get("entity_type"),
                                row.get("entity_id"),
                                row.get("linked_table"),
                                row.get("linked_column"),
                                row.get("link_method"),
                                row.get("confidence") or None,
                                row.get("notes"),
                            ),
                        )
                        unsafe_count += 1
    print(f"loaded entity links: public_safe={public_count}, unsafe_audit={unsafe_count}")


def truncate_loaded_tables(conn) -> None:
    raw_tables = ", ".join(f"raw.{qident(table_name(t))}" for t in OFFICIAL_TABLES)
    core_tables = ", ".join(f"core.{qident(table_name(t))}" for t in OFFICIAL_TABLES)
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {raw_tables} RESTART IDENTITY")
        cur.execute(f"TRUNCATE {core_tables} RESTART IDENTITY CASCADE")
        cur.execute(
            """
            TRUNCATE
                rag.entity_links,
                rag.chunk_embeddings,
                rag.document_chunks,
                rag.source_documents,
                audit.provenance_entity_links,
                eval.question_tags,
                eval.answer_runs,
                eval.questions
            RESTART IDENTITY CASCADE
            """
        )


def load_official_csvs(conn, load_raw: bool, load_core: bool) -> None:
    with conn.cursor() as cur:
        cur.execute("SET CONSTRAINTS ALL DEFERRED")
        for csv_stem in OFFICIAL_TABLES:
            path = TABLES_DIR / f"{csv_stem}.csv"
            if not path.exists():
                raise FileNotFoundError(path)
            table = table_name(csv_stem)
            if load_raw:
                rows = copy_csv(cur, "raw", table, path)
                print(f"loaded raw.{table}: {rows}")
            if load_core:
                rows = copy_csv(cur, "core", table, path)
                print(f"loaded core.{table}: {rows}")


def refresh_materialized_views(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regprocedure('mart.refresh_all_materialized_views(boolean)')")
        if cur.fetchone()[0]:
            cur.execute("SELECT mart.refresh_all_materialized_views(false)")
            print("refreshed materialized views: non-concurrent first-load mode")
        else:
            print("skipped materialized refresh; run db/004_materialized_marts.sql first")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="Postgres connection URL")
    parser.add_argument("--truncate", action="store_true", help="Truncate loaded schemas before inserting")
    parser.add_argument("--skip-raw", action="store_true", help="Do not load raw.* CSV tables")
    parser.add_argument("--skip-core", action="store_true", help="Do not load core.* CSV tables")
    parser.add_argument("--skip-rag", action="store_true", help="Do not load markdown chunks/entity links")
    parser.add_argument("--skip-eval", action="store_true", help="Do not load questions.csv")
    parser.add_argument(
        "--refresh-materialized",
        action="store_true",
        help="Refresh mart/RAG materialized views after loading, if the refresh function exists",
    )
    parser.add_argument("--chunk-chars", type=int, default=4500)
    parser.add_argument("--chunk-overlap-chars", type=int, default=500)
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("Set DATABASE_URL or pass --database-url")
    if args.chunk_overlap_chars >= args.chunk_chars:
        raise SystemExit("--chunk-overlap-chars must be smaller than --chunk-chars")

    with psycopg.connect(args.database_url) as conn:
        with conn.transaction():
            if args.truncate:
                truncate_loaded_tables(conn)
            load_official_csvs(conn, load_raw=not args.skip_raw, load_core=not args.skip_core)
            if not args.skip_eval:
                load_questions(conn)
            if not args.skip_rag:
                load_markdown_documents(conn, args.chunk_chars, args.chunk_overlap_chars)
                load_entity_links(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT to_regprocedure('audit.analyze_fahmai_model_tables()')")
            if cur.fetchone()[0]:
                cur.execute("SELECT audit.analyze_fahmai_model_tables()")
            else:
                print("skipped ANALYZE helper; run db/003_performance_indexes.sql, then call audit.analyze_fahmai_model_tables()")
            if args.refresh_materialized:
                refresh_materialized_views(conn)

    return 0


if __name__ == "__main__":
    sys.exit(main())
