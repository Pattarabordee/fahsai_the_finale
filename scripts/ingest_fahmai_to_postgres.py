#!/usr/bin/env python
"""Load the FahMai public bundle into the local PostgreSQL model schema.

Prerequisites:
  pip install psycopg[binary]

Usage:
  $env:DATABASE_URL = "postgresql://fahmai_app:<password>@0.tcp.ap.ngrok.io:26551/fahmai?sslmode=disable"
  python scripts/ingest_fahmai_to_postgres.py --truncate
  python scripts/ingest_fahmai_to_postgres.py --truncate --refresh-materialized

This script loads:
  - official CSVs into fah_sai_lpk_raw.* and fah_sai_lpk_core.*
  - questions.csv into fah_sai_lpk_eval.questions/fah_sai_lpk_eval.question_tags
  - public markdown docs/reports/logs into fah_sai_lpk_rag.source_documents/document_chunks
  - derived public-safe entity links into fah_sai_lpk_rag.entity_links
  - unsafe provenance links into fah_sai_lpk_audit.provenance_entity_links

It does not generate embeddings. Run scripts/embed_chunks_openai.py after this.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit("Missing dependency: pip install psycopg[binary]") from exc


ROOT = Path(__file__).resolve().parents[1]
TABLES_DIR = ROOT / "super-ai-engineer-season-6-fah-mai-the-finale" / "tables"
PUBLIC_BUNDLE_DIR = ROOT / "super-ai-engineer-season-6-fah-mai-the-finale"
QUESTIONS_CSV = ROOT / "questions.csv"
DERIVED_DIR = ROOT / "derived"
DEFAULT_CHUNK_CHARS = 2000
DEFAULT_CHUNK_OVERLAP_CHARS = 200
CHUNK_SPLITTER_VERSION = "section-aware-recursive-v2"
MAX_CONTEXT_PREFIX_CHARS = 420
MAX_ENTITY_TOKENS = 12

HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+(.+?)\s*$")
DATE_RE = re.compile(r"(?:20\d{2}|25[6-9]\d)[-/](?:0[1-9]|1[0-2])(?:[-/](?:0[1-9]|[12]\d|3[01]))?")
ISO_DATE_RE = re.compile(r"(?<!\d)((?:20\d{2}|25[6-9]\d)[-/]\d{2}[-/]\d{2})(?!\d)")
COMPACT_DATE_RE = re.compile(r"(?<!\d)(20\d{6})(?!\d)")
MONTH_PERIOD_RE = re.compile(r"(?<!\d)(20\d{2})[-/](\d{2})(?![-/\d])")
QUARTER_PERIOD_RE = re.compile(r"(?<!\d)(20\d{2})-Q([1-4])(?!\w)")
ENTITY_TOKEN_RE = re.compile(
    r"\b(?:"
    r"FACT_[A-Z0-9_]+|DIM_[A-Z0-9_]+|"
    r"CUST-[A-Z0-9-]+|BT-\d{6}-\d+|"
    r"[A-Z]{1,6}(?:-[A-Z0-9]+){1,}|"
    r"V-\d{3}|L3-Q-[A-Z0-9-]+"
    r")\b"
)
SKU_RE = re.compile(r"\b(?:SKU-[A-Z0-9-]+|[A-Z]{2}-[A-Z]{2}-\d{3})\b")
BRANCH_CODE_RE = re.compile(r"\b(?:(?:BKK|CNX|HKT|KKC|UDN|PTY)-[A-Z0-9]{2,6}|REMOTE)\b")
TXN_ID_RE = re.compile(r"\bTXN-[A-Z0-9-]+\b")
MESSAGE_ID_RE = re.compile(r"\bM-\d{3,}\b")
MONEY_RE = re.compile(r"(?:THB|฿)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:THB|บาท)")

THAI_MONTHS = {
    "มกราคม": 1,
    "กุมภาพันธ์": 2,
    "มีนาคม": 3,
    "เมษายน": 4,
    "พฤษภาคม": 5,
    "มิถุนายน": 6,
    "กรกฎาคม": 7,
    "สิงหาคม": 8,
    "กันยายน": 9,
    "ตุลาคม": 10,
    "พฤศจิกายน": 11,
    "ธันวาคม": 12,
}

OPS_METRIC_GROUPS = {
    "revenue summary": "revenue_summary",
    "top-10 skus by revenue": "top_skus_by_revenue",
    "top 10 skus by revenue": "top_skus_by_revenue",
    "per-branch performance": "per_branch_performance",
    "per branch performance": "per_branch_performance",
    "returns & warranty": "returns_warranty",
    "returns warranty": "returns_warranty",
    "cs interaction volume": "cs_interaction_volume",
    "inventory health": "inventory_health",
}

FIN_METRIC_GROUPS = {
    "revenue b2c / b2b split": "revenue_split",
    "revenue b2c b2b split": "revenue_split",
    "cogs & gross margin": "cogs_gross_margin",
    "cogs gross margin": "cogs_gross_margin",
    "operating expense breakdown": "operating_expense",
    "cash flow summary": "cash_flow",
    "ar aging snapshot": "ar_aging",
}


@dataclass(frozen=True)
class ChunkPiece:
    char_start: int
    char_end: int
    chunk_text: str
    metadata: dict[str, Any]

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
                INSERT INTO fah_sai_lpk_eval.questions
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
                    INSERT INTO fah_sai_lpk_eval.question_tags (question_id, tag, tag_source, confidence)
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


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def progress_message(label: str, current: int, total: int, start_time: float) -> str:
    elapsed = time.monotonic() - start_time
    percent = (current / total * 100) if total else 100.0
    rate = current / elapsed if elapsed > 0 else 0.0
    eta = (total - current) / rate if rate > 0 else 0.0
    return (
        f"{label}: {current}/{total} "
        f"({percent:.1f}%) elapsed={format_duration(elapsed)} eta={format_duration(eta)}"
    )


def source_kind_for(path: Path) -> str:
    rel = path.relative_to(ROOT)
    parts = rel.parts
    if "reports" in parts:
        return "report_md"
    if "logs" in parts:
        return "log_md"
    if "docs" in parts:
        docs_idx = parts.index("docs")
        if len(parts) > docs_idx + 2:
            return f"doc_{parts[docs_idx + 1]}"
        return "doc_markdown"
    return "markdown"


def compact_text(value: str, max_chars: int = 180) -> str:
    compacted = re.sub(r"\s+", " ", value).strip()
    if len(compacted) <= max_chars:
        return compacted
    return compacted[: max_chars - 3].rstrip() + "..."


def unique_preserve_order(values: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    result: list[Any] = []
    for value in values:
        if value in (None, "") or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def prune_empty_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: cleaned
            for key, item in value.items()
            if (cleaned := prune_empty_values(item)) not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [cleaned for item in value if (cleaned := prune_empty_values(item)) not in (None, "", [], {})]
    return value


def normalize_year(year: int) -> int:
    return year - 543 if year >= 2500 else year


def normalize_date_value(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().replace("/", "-")
    if re.fullmatch(r"20\d{6}", cleaned):
        return f"{cleaned[:4]}-{cleaned[4:6]}-{cleaned[6:8]}"
    match = re.fullmatch(r"(20\d{2}|25[6-9]\d)-(\d{2})(?:-(\d{2}))?", cleaned)
    if not match:
        return None
    year = normalize_year(int(match.group(1)))
    month = int(match.group(2))
    day = match.group(3)
    if day:
        return f"{year:04d}-{month:02d}-{int(day):02d}"
    return f"{year:04d}-{month:02d}"


def extract_thai_buddhist_date(text: str | None) -> str | None:
    if not text:
        return None
    month_names = "|".join(re.escape(name) for name in THAI_MONTHS)
    match = re.search(rf"(\d{{1,2}})\s*({month_names})\s*(25\d{{2}})", text)
    if not match:
        return None
    day = int(match.group(1))
    month = THAI_MONTHS[match.group(2)]
    year = int(match.group(3)) - 543
    return f"{year:04d}-{month:02d}-{day:02d}"


def first_normalized_date(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        match = ISO_DATE_RE.search(value)
        if match and (normalized := normalize_date_value(match.group(1))):
            return normalized
        compact_match = COMPACT_DATE_RE.search(value)
        if compact_match and (normalized := normalize_date_value(compact_match.group(1))):
            return normalized
        thai_date = extract_thai_buddhist_date(value)
        if thai_date:
            return thai_date
    return None


def first_report_period(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        quarter_match = QUARTER_PERIOD_RE.search(value)
        if quarter_match:
            return f"{quarter_match.group(1)}-Q{quarter_match.group(2)}"
        month_match = MONTH_PERIOD_RE.search(value)
        if month_match:
            return f"{month_match.group(1)}-{month_match.group(2)}"
    return None


def period_parts(period: str | None) -> dict[str, Any]:
    if not period:
        return {}
    if re.fullmatch(r"20\d{2}-Q[1-4]", period):
        return {
            "period": period,
            "report_period": period,
            "period_type": "quarter",
            "quarter": period.split("-")[-1],
            "year": int(period[:4]),
        }
    if re.fullmatch(r"20\d{2}-\d{2}", period):
        return {
            "period": period,
            "report_period": period,
            "period_type": "month",
            "year": int(period[:4]),
            "month": int(period[5:7]),
        }
    return {"period": period, "report_period": period}


def date_parts(date_value: str | None) -> dict[str, int]:
    if not date_value or not re.match(r"20\d{2}-\d{2}", date_value):
        return {}
    parts = {"year": int(date_value[:4]), "month": int(date_value[5:7])}
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", date_value):
        parts["day"] = int(date_value[8:10])
    return parts


def extract_source_title(text: str, source_path: str | None) -> str:
    heading = HEADING_RE.search(text)
    if heading:
        return compact_text(heading.group(2))
    for line in text.splitlines():
        if line.strip():
            return compact_text(line)
    return Path(source_path or "document").stem


def extract_source_date(text: str, source_path: str | None) -> str | None:
    return first_normalized_date(source_path or "", text[:2000]) or first_report_period(source_path or "", text[:2000])


def source_family_for(source_kind: str | None, source_path: str | None) -> str:
    if source_kind == "report_md":
        return "report"
    if source_kind == "log_md":
        return "log"
    if source_kind and source_kind.startswith("doc_"):
        return source_kind.removeprefix("doc_")
    parts = Path(source_path or "").parts
    if "docs" in parts:
        docs_idx = parts.index("docs")
        if len(parts) > docs_idx + 1:
            return parts[docs_idx + 1]
    return source_kind or "markdown"


def source_type_for(source_family: str, source_path: str | None) -> str:
    stem = Path(source_path or "").stem
    if source_family == "report":
        if stem.startswith("OPS_REPORT_"):
            return "ops_monthly_report"
        if stem.startswith("FIN_CLOSE_"):
            return "fin_quarterly_close"
    if source_family in {"chat_line_oa", "chat_line_works", "email", "l1_kb", "memo", "minutes"}:
        return source_family
    return source_family or "markdown"


def parse_prefixed_header(text: str, labels: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for label in labels:
        match = re.search(
            rf"^\s*(?:\*\*)?{re.escape(label)}\s*:\s*(?:\*\*)?\s*(.+?)\s*$",
            text,
            re.MULTILINE,
        )
        if match:
            result[label] = match.group(1).strip()
    return result


def parse_json_object_stream(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    index = 0
    objects: list[dict[str, Any]] = []
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        try:
            item, next_index = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            index += 1
            continue
        if isinstance(item, dict):
            objects.append(item)
        index = next_index
    return objects


def parse_money(value: str | None) -> float | None:
    if not value:
        return None
    match = MONEY_RE.search(value)
    raw_value = next((group for group in match.groups() if group), None) if match else value
    normalized = re.sub(r"[^\d.]", "", raw_value or "")
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def normalize_report_heading(section_heading: str | None) -> str:
    if not section_heading:
        return ""
    without_number = re.sub(r"^\s*\d+\.\s*", "", section_heading)
    normalized = without_number.lower().replace("—", "-").replace("–", "-")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def slugify_metric_group(value: str) -> str:
    value = value.replace("&", " ")
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return value or "section"


def metric_group_for_report(report_family: str | None, section_heading: str | None) -> str | None:
    normalized = normalize_report_heading(section_heading)
    if not normalized:
        return None
    if report_family == "ops":
        return OPS_METRIC_GROUPS.get(normalized, slugify_metric_group(normalized))
    if report_family == "fin":
        return FIN_METRIC_GROUPS.get(normalized, slugify_metric_group(normalized))
    return slugify_metric_group(normalized)


def parse_report_metadata(source_path: str | None, source_title: str) -> dict[str, Any]:
    stem = Path(source_path or "").stem
    ops_match = re.fullmatch(r"OPS_REPORT_(20\d{2}-\d{2})", stem)
    fin_match = re.fullmatch(r"FIN_CLOSE_(20\d{2}-Q([1-4]))", stem)
    if ops_match:
        return {
            "document_title": f"FahMai OPS Monthly Report | {ops_match.group(1)}",
            "report_family": "ops",
            **period_parts(ops_match.group(1)),
        }
    if fin_match:
        return {
            "document_title": f"FahMai FIN Quarterly Close | {fin_match.group(1)}",
            "report_family": "fin",
            **period_parts(fin_match.group(1)),
        }
    if period := first_report_period(source_path or "", source_title):
        return period_parts(period)
    return {}


def parse_participants(header_text: str) -> list[str]:
    match = re.search(
        r"ผู้เข้าร่วมประชุม\s*:\s*(.+?)(?:\n\s*ประธาน\s*:|\n\s*ผู้จดบันทึก\s*:|$)",
        header_text,
        flags=re.DOTALL,
    )
    if not match:
        return []
    participants: list[str] = []
    for line in match.group(1).splitlines():
        cleaned = line.strip(" -\t")
        if cleaned:
            participants.append(cleaned)
    return participants


def metadata_from_source(
    text: str,
    *,
    source_path: str | None,
    source_kind: str | None,
    source_title: str,
) -> dict[str, Any]:
    source_family = source_family_for(source_kind, source_path)
    source_type = source_type_for(source_family, source_path)
    source_date = extract_source_date(text, source_path)
    report_period = first_report_period(source_path or "", text[:2000])
    source_file = Path(source_path or "").name if source_path else None
    source_id = Path(source_path or "").stem if source_path else None
    metadata: dict[str, Any] = {
        "source_path": source_path,
        "source_kind": source_kind,
        "source_family": source_family,
        "source_type": source_type,
        "document_title": source_title,
        "source_title": source_title,
        "source_file": source_file,
        "source_id": source_id,
        "source_date": source_date,
        "report_period": report_period,
    }

    if report_period:
        metadata.update(period_parts(report_period))
    if source_date and not report_period:
        metadata.update(date_parts(source_date))

    if source_family == "report":
        metadata.update(parse_report_metadata(source_path, source_title))
    elif source_family == "email":
        header = parse_prefixed_header(text[:1200], ["Subject", "From", "To", "Date"])
        subject = header.get("Subject") or source_title
        metadata.update(
            {
                "document_title": f"Email | {subject}",
                "subject": subject,
                "from_person": header.get("From"),
                "to": header.get("To"),
                "event_date": first_normalized_date(header.get("Date"), text[:2000]) or source_date,
            }
        )
    elif source_family == "memo":
        header = parse_prefixed_header(text[:1600], ["ที่", "วันที่", "ถึง", "จาก", "เรื่อง"])
        event_date = extract_thai_buddhist_date(header.get("วันที่")) or first_normalized_date(source_path or "", text[:2000])
        subject = header.get("เรื่อง") or source_title
        metadata.update(
            {
                "document_title": f"Memo | {header.get('ที่') or source_id} | {subject}",
                "memo_no": header.get("ที่"),
                "event_date": event_date or source_date,
                "to": header.get("ถึง"),
                "from_person": header.get("จาก"),
                "subject": subject,
                "record_id": header.get("ที่") or source_id,
            }
        )
    elif source_family == "minutes":
        header_text = text.split("\n#", 1)[0]
        header = parse_prefixed_header(header_text, ["ครั้งที่", "วันที่", "เวลา", "สถานที่", "ประธาน", "ผู้จดบันทึก"])
        event_date = extract_thai_buddhist_date(header.get("วันที่")) or first_normalized_date(source_path or "", header_text)
        meeting_no = header.get("ครั้งที่")
        metadata.update(
            {
                "document_title": f"Minutes | {meeting_no or source_id} | {event_date or source_date or 'unknown-date'}",
                "meeting_no": meeting_no,
                "event_date": event_date or source_date,
                "time": header.get("เวลา"),
                "location": header.get("สถานที่"),
                "chair": header.get("ประธาน"),
                "note_taker": header.get("ผู้จดบันทึก"),
                "participants": parse_participants(header_text),
                "record_id": source_id,
            }
        )
    elif source_family in {"chat_line_oa", "chat_line_works"}:
        messages = parse_json_object_stream(text[:20000])
        participants = unique_preserve_order(str(message.get("speaker", "")).strip() for message in messages)
        message_ids = [str(message.get("message_id")) for message in messages if message.get("message_id")]
        timestamps = [str(message.get("timestamp")) for message in messages if message.get("timestamp")]
        event_date = first_normalized_date(source_path or "") or source_date
        participant_title = " -> ".join(participants[:2]) if participants else source_id
        metadata.update(
            {
                "document_title": f"Chat {source_family} | {event_date or 'unknown-date'} | {participant_title}",
                "event_date": event_date,
                "participants": participants,
                "speaker_a": participants[0] if participants else None,
                "speaker_b": participants[1] if len(participants) > 1 else None,
                "message_ids": message_ids[:20],
                "message_count": len(messages) or None,
                "time_range": f"{timestamps[0]}-{timestamps[-1]}" if timestamps else None,
                "record_id": source_id,
            }
        )
    elif source_family == "l1_kb":
        header = parse_prefixed_header(
            text[:1800],
            ["รหัสสินค้า", "แบรนด์", "หมวดหมู่", "ราคา", "สถานะ", "วันที่อัปเดต"],
        )
        sku_id = header.get("รหัสสินค้า") or next(iter(SKU_RE.findall(source_path or "")), None)
        updated_date = extract_thai_buddhist_date(header.get("วันที่อัปเดต")) or source_date
        metadata.update(
            {
                "product_name": source_title,
                "sku_id": sku_id,
                "sku_ids": [sku_id] if sku_id else [],
                "brand": header.get("แบรนด์"),
                "category": header.get("หมวดหมู่"),
                "price_thb": parse_money(header.get("ราคา")),
                "status": header.get("สถานะ"),
                "updated_date": updated_date,
                "event_date": updated_date,
                "record_id": sku_id or source_id,
            }
        )

    metadata["date"] = metadata.get("event_date") or metadata.get("source_date") or metadata.get("report_period")
    return prune_empty_values(metadata)


def metadata_from_chunk_text(text: str) -> dict[str, Any]:
    messages = parse_json_object_stream(text) if '"message_id"' in text or text.lstrip().startswith("{") else []
    participants = unique_preserve_order(str(message.get("speaker", "")).strip() for message in messages)
    timestamps = [str(message.get("timestamp")) for message in messages if message.get("timestamp")]
    metadata = {
        "entity_tokens": extract_entity_tokens(text),
        "sku_ids": unique_preserve_order(SKU_RE.findall(text)),
        "branch_codes": unique_preserve_order(BRANCH_CODE_RE.findall(text)),
        "txn_ids": unique_preserve_order(TXN_ID_RE.findall(text)),
        "message_ids": [str(message.get("message_id")) for message in messages if message.get("message_id")]
        or unique_preserve_order(MESSAGE_ID_RE.findall(text)),
        "participants": participants,
        "message_count": len(messages) or None,
        "time_range": f"{timestamps[0]}-{timestamps[-1]}" if timestamps else None,
        "content_sha256": sha256_text(text),
    }
    return prune_empty_values(metadata)


def extract_entity_tokens(text: str, limit: int = MAX_ENTITY_TOKENS) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for match in ENTITY_TOKEN_RE.finditer(text):
        token = match.group(0)
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= limit:
            break
    return tokens


def build_context_prefix(
    *,
    source_path: str | None,
    source_kind: str | None,
    source_title: str,
    source_date: str | None,
    section_heading: str | None,
    entity_tokens: list[str],
    extra_fields: list[tuple[str, Any]] | None = None,
) -> str:
    fields = [
        ("source", source_path or "unknown"),
        ("kind", source_kind or "markdown"),
        ("title", source_title),
    ]
    if source_date:
        fields.append(("date", source_date))
    if section_heading and section_heading != source_title:
        fields.append(("section", section_heading))
    if entity_tokens:
        fields.append(("entities", ",".join(entity_tokens)))
    if extra_fields:
        for key, value in extra_fields:
            if value in (None, "", [], {}):
                continue
            if isinstance(value, list):
                value = ",".join(str(item) for item in value[:8])
            fields.append((key, str(value)))

    prefix = "[" + " | ".join(f"{key}={compact_text(value, 120)}" for key, value in fields) + "]\n"
    if len(prefix) <= MAX_CONTEXT_PREFIX_CHARS:
        return prefix

    compact_fields = fields[:3]
    for key, value in fields[3:]:
        if key in {"type", "date", "period", "event", "section", "subject", "sku", "branch", "metric", "entities"}:
            compact_fields.append((key, value))
    while compact_fields:
        prefix = "[" + " | ".join(f"{key}={compact_text(value, 80)}" for key, value in compact_fields) + "]\n"
        if len(prefix) <= MAX_CONTEXT_PREFIX_CHARS or len(compact_fields) <= 3:
            return prefix
        compact_fields.pop()
    return ""


def context_extra_fields(metadata: dict[str, Any]) -> list[tuple[str, Any]]:
    return [
        ("type", metadata.get("source_type")),
        ("period", metadata.get("period") or metadata.get("report_period")),
        ("event", metadata.get("event_date")),
        ("subject", metadata.get("subject")),
        ("memo", metadata.get("memo_no")),
        ("meeting", metadata.get("meeting_no")),
        ("metric", metadata.get("metric_group")),
        ("sku", metadata.get("sku_id") or metadata.get("sku_ids")),
        ("branch", metadata.get("branch_code") or metadata.get("branch_codes")),
        ("txn", metadata.get("txn_id") or metadata.get("txn_ids")),
        ("participants", metadata.get("participants")),
        ("messages", metadata.get("message_ids")),
    ]


def stripped_piece(text: str, absolute_start: int, start: int, end: int) -> tuple[int, int, str] | None:
    piece = text[start:end]
    if not piece.strip():
        return None
    left_trimmed = len(piece) - len(piece.lstrip())
    right_trimmed = len(piece.rstrip())
    return absolute_start + start + left_trimmed, absolute_start + start + right_trimmed, piece.strip()


def markdown_sections(text: str, source_title: str) -> list[tuple[int, int, str | None, int]]:
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [(0, len(text), source_title, 0)]

    sections: list[tuple[int, int, str | None, int]] = []
    if matches[0].start() > 0:
        sections.append((0, matches[0].start(), source_title, 0))

    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        heading_level = len(match.group(1))
        heading_text = compact_text(match.group(2))
        sections.append((match.start(), end, heading_text, heading_level))
    return sections


def choose_boundary(text: str, start: int, end: int) -> tuple[int, str]:
    min_pos = start + max(1, int((end - start) * 0.45))
    if end >= len(text):
        return end, "end"

    paragraph = text.rfind("\n\n", min_pos, end)
    if paragraph > start:
        return paragraph + 2, "paragraph"

    heading = text.rfind("\n#", min_pos, end)
    if heading > start:
        return heading, "heading"

    newline = text.rfind("\n", min_pos, end)
    if newline > start:
        return newline + 1, "line"

    sentence_positions = []
    for separator in [".", "!", "?", "\u3002", "\uff01", "\uff1f"]:
        position = text.rfind(separator, min_pos, end)
        if position > start:
            sentence_positions.append((position + len(separator), "sentence"))
    if sentence_positions:
        return max(sentence_positions, key=lambda item: item[0])

    space = text.rfind(" ", min_pos, end)
    if space > start:
        return space + 1, "space"

    zero_width = text.rfind("\u200b", min_pos, end)
    if zero_width > start:
        return zero_width + 1, "zero_width_space"

    return end, "hard"


def split_large_text_block(
    text: str,
    absolute_start: int,
    chunk_chars: int,
    overlap_chars: int,
    metadata: dict[str, Any],
) -> list[ChunkPiece]:
    pieces: list[ChunkPiece] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        end, boundary_type = choose_boundary(text, start, end)
        stripped = stripped_piece(text, absolute_start, start, end)
        if stripped:
            char_start, char_end, piece_text = stripped
            piece_metadata = dict(metadata)
            piece_metadata["boundary_type"] = boundary_type
            pieces.append(ChunkPiece(char_start, char_end, piece_text, piece_metadata))
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return pieces


def is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def is_table_separator(line: str) -> bool:
    stripped = line.strip()
    return is_table_row(line) and all(char in "|-: " for char in stripped)


def markdown_blocks(section_text: str, section_start: int) -> list[tuple[int, int, str, str]]:
    blocks: list[tuple[int, int, str, str]] = []
    current_lines: list[str] = []
    current_kind: str | None = None
    current_start = 0
    offset = 0

    def flush(end_offset: int) -> None:
        nonlocal current_lines, current_kind, current_start
        if not current_lines or current_kind is None:
            current_lines = []
            current_kind = None
            return
        raw = "".join(current_lines)
        stripped = stripped_piece(raw, section_start + current_start, 0, len(raw))
        if stripped:
            char_start, char_end, block_text = stripped
            blocks.append((char_start, char_end, block_text, current_kind))
        current_lines = []
        current_kind = None
        current_start = end_offset

    for line in section_text.splitlines(keepends=True):
        line_kind = "table" if is_table_row(line) else "text"
        if not line.strip():
            if current_lines:
                current_lines.append(line)
                offset += len(line)
                flush(offset)
            else:
                offset += len(line)
            continue

        if current_kind is not None and current_kind != line_kind:
            flush(offset)
        if not current_lines:
            current_start = offset
            current_kind = line_kind
        current_lines.append(line)
        offset += len(line)
    flush(offset)
    return blocks


def split_large_table_block(
    table_text: str,
    absolute_start: int,
    chunk_chars: int,
    overlap_chars: int,
    metadata: dict[str, Any],
) -> list[ChunkPiece]:
    lines = table_text.splitlines(keepends=True)
    if len(lines) < 2:
        return split_large_text_block(table_text, absolute_start, chunk_chars, overlap_chars, metadata)

    header_lines = lines[:2] if is_table_separator(lines[1]) else lines[:1]
    body_lines = lines[len(header_lines) :]
    header_text = "".join(header_lines)
    if len(header_text) >= chunk_chars:
        return split_large_text_block(table_text, absolute_start, chunk_chars, overlap_chars, metadata)

    pieces: list[ChunkPiece] = []
    current = header_text
    current_start = absolute_start
    row_offset = len(header_text)

    for row in body_lines:
        row_start = absolute_start + row_offset
        if len(current) + len(row) > chunk_chars and current.strip() != header_text.strip():
            piece_metadata = dict(metadata)
            piece_metadata["boundary_type"] = "table_rows"
            pieces.append(ChunkPiece(current_start, absolute_start + row_offset, current.strip(), piece_metadata))
            current = header_text + row
            current_start = row_start
        elif len(row) > chunk_chars:
            if current.strip() != header_text.strip():
                piece_metadata = dict(metadata)
                piece_metadata["boundary_type"] = "table_rows"
                pieces.append(ChunkPiece(current_start, row_start, current.strip(), piece_metadata))
            pieces.extend(split_large_text_block(row, row_start, chunk_chars, overlap_chars, metadata))
            current = header_text
            current_start = row_start + len(row)
        else:
            current += row
        row_offset += len(row)

    if current.strip() and current.strip() != header_text.strip():
        piece_metadata = dict(metadata)
        piece_metadata["boundary_type"] = "table_rows"
        pieces.append(ChunkPiece(current_start, absolute_start + len(table_text), current.strip(), piece_metadata))
    return pieces


def split_section_body(
    section_text: str,
    section_start: int,
    chunk_chars: int,
    overlap_chars: int,
    metadata: dict[str, Any],
) -> list[ChunkPiece]:
    blocks = markdown_blocks(section_text, section_start)
    if not blocks:
        return []

    pieces: list[ChunkPiece] = []
    current_parts: list[str] = []
    current_start = 0
    current_end = 0
    current_kinds: set[str] = set()

    def flush() -> None:
        nonlocal current_parts, current_start, current_end, current_kinds
        if not current_parts:
            return
        piece_metadata = dict(metadata)
        piece_metadata["chunk_kind"] = "table" if current_kinds == {"table"} else "section"
        piece_metadata["boundary_type"] = "block_pack"
        pieces.append(ChunkPiece(current_start, current_end, "\n\n".join(current_parts).strip(), piece_metadata))
        current_parts = []
        current_start = 0
        current_end = 0
        current_kinds = set()

    for block_start, block_end, block_text, block_kind in blocks:
        block_metadata = dict(metadata)
        block_metadata["chunk_kind"] = "table" if block_kind == "table" else "text"
        if len(block_text) > chunk_chars:
            flush()
            if block_kind == "table":
                pieces.extend(split_large_table_block(block_text, block_start, chunk_chars, overlap_chars, block_metadata))
            else:
                pieces.extend(split_large_text_block(block_text, block_start, chunk_chars, overlap_chars, block_metadata))
            continue

        candidate_size = len("\n\n".join(current_parts + [block_text]))
        if current_parts and candidate_size > chunk_chars:
            flush()
        if not current_parts:
            current_start = block_start
        current_parts.append(block_text)
        current_end = block_end
        current_kinds.add(block_kind)
    flush()
    return pieces


def chunk_text_with_metadata(
    text: str,
    chunk_chars: int,
    overlap_chars: int,
    *,
    source_path: str | None = None,
    source_kind: str | None = None,
) -> list[ChunkPiece]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []

    source_title = extract_source_title(normalized, source_path)
    source_date = extract_source_date(normalized, source_path)
    document_metadata = metadata_from_source(
        normalized,
        source_path=source_path,
        source_kind=source_kind,
        source_title=source_title,
    )
    display_title = document_metadata.get("document_title") or source_title
    pieces: list[ChunkPiece] = []

    sections = markdown_sections(normalized, source_title)
    for section_start, section_end, section_heading, heading_level in sections:
        stripped = stripped_piece(normalized, 0, section_start, section_end)
        if not stripped:
            continue
        char_start, char_end, section_text = stripped
        base_metadata: dict[str, Any] = {
            "chunk_strategy": "section-aware-recursive",
            "splitter_version": CHUNK_SPLITTER_VERSION,
            "section_heading": section_heading,
            "heading_level": heading_level,
        }

        if len(section_text) <= chunk_chars:
            chunk_kind = "full_document" if len(sections) == 1 else "section"
            base_metadata.update({"chunk_kind": chunk_kind, "boundary_type": "section"})
            pieces.append(ChunkPiece(char_start, char_end, section_text, base_metadata))
        else:
            pieces.extend(split_section_body(section_text, char_start, chunk_chars, overlap_chars, base_metadata))

    contextualized: list[ChunkPiece] = []
    for piece in pieces:
        chunk_metadata = metadata_from_chunk_text(piece.chunk_text)
        metadata = dict(document_metadata)
        metadata.update(piece.metadata)
        metadata.update(chunk_metadata)
        if metadata.get("report_family") and int(metadata.get("heading_level") or 0) > 1:
            metadata["metric_group"] = metric_group_for_report(
                metadata.get("report_family"),
                metadata.get("section_heading"),
            )
        metadata = prune_empty_values(metadata)
        entity_tokens = list(metadata.get("entity_tokens", []))
        section_heading = piece.metadata.get("section_heading")
        if section_heading == source_title and display_title != source_title:
            section_heading = None
        prefix = build_context_prefix(
            source_path=source_path,
            source_kind=source_kind,
            source_title=str(display_title),
            source_date=metadata.get("date") or source_date,
            section_heading=section_heading,
            entity_tokens=entity_tokens,
            extra_fields=context_extra_fields(metadata),
        )
        metadata.update(
            {
                "source_title": source_title,
                "entity_tokens": entity_tokens,
                "content_char_start": piece.char_start,
                "content_char_end": piece.char_end,
                "context_prefix_chars": len(prefix),
            }
        )
        metadata = prune_empty_values(metadata)
        contextualized.append(
            ChunkPiece(
                piece.char_start,
                piece.char_end,
                prefix + piece.chunk_text,
                metadata,
            )
        )
    return contextualized


def chunk_text(text: str, chunk_chars: int, overlap_chars: int) -> list[tuple[int, int, str]]:
    return [
        (chunk.char_start, chunk.char_end, chunk.chunk_text)
        for chunk in chunk_text_with_metadata(text, chunk_chars, overlap_chars)
    ]


def resolve_entity_chunk_id(
    cur,
    source_document_id: str | None,
    entity_id: str | None,
    cache: dict[tuple[str, str], str | None],
) -> str | None:
    if not source_document_id or not entity_id:
        return None
    cache_key = (source_document_id, entity_id)
    if cache_key in cache:
        return cache[cache_key]
    cur.execute(
        """
        SELECT chunk_id
        FROM fah_sai_lpk_rag.document_chunks
        WHERE source_document_id = %s
          AND position(%s in chunk_text) > 0
        ORDER BY chunk_index
        LIMIT 1
        """,
        (source_document_id, entity_id),
    )
    row = cur.fetchone()
    chunk_id = row[0] if row else None
    cache[cache_key] = chunk_id
    return chunk_id


def resolve_entity_chunk_id_from_map(
    chunks_by_source: dict[str, list[tuple[str, str]]],
    source_document_id: str | None,
    entity_id: str | None,
    cache: dict[tuple[str, str], str | None],
) -> str | None:
    if not source_document_id or not entity_id:
        return None
    cache_key = (source_document_id, entity_id)
    if cache_key in cache:
        return cache[cache_key]
    for chunk_id, chunk_text_value in chunks_by_source.get(source_document_id, []):
        if entity_id in chunk_text_value:
            cache[cache_key] = chunk_id
            return chunk_id
    cache[cache_key] = None
    return None


def flush_markdown_document_batch(
    conn,
    source_rows: list[tuple[str, str, str, str]],
    chunk_rows: list[tuple[str, str, int, str, int, int, int, Jsonb]],
    delete_source_ids: list[str],
) -> None:
    if not source_rows and not chunk_rows:
        return

    with conn.transaction():
        with conn.cursor() as cur:
            if delete_source_ids:
                cur.execute(
                    "DELETE FROM fah_sai_lpk_rag.document_chunks WHERE source_document_id = ANY(%s)",
                    (delete_source_ids,),
                )
            if source_rows:
                cur.executemany(
                    """
                    INSERT INTO fah_sai_lpk_rag.source_documents
                        (source_document_id, source_path, source_kind, is_public_safe, safety_tier, content_sha256)
                    VALUES (%s, %s, %s, true, 'official', %s)
                    ON CONFLICT (source_path) DO UPDATE SET
                        source_kind = EXCLUDED.source_kind,
                        is_public_safe = true,
                        safety_tier = 'official',
                        content_sha256 = EXCLUDED.content_sha256,
                        updated_at = now()
                    """,
                    source_rows,
                )
            if chunk_rows:
                cur.executemany(
                    """
                    INSERT INTO fah_sai_lpk_rag.document_chunks
                        (chunk_id, source_document_id, chunk_index, chunk_text, token_count,
                         char_start, char_end, language_hint, is_public_safe, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'th-en', true, %s)
                    """,
                    chunk_rows,
                )


def load_markdown_documents(
    conn,
    chunk_chars: int,
    overlap_chars: int,
    *,
    delete_existing: bool = True,
    batch_documents: int = 1000,
) -> None:
    paths = list(markdown_paths())
    total_documents = len(paths)
    start_time = time.monotonic()
    document_count = 0
    chunk_count = 0
    source_rows: list[tuple[str, str, str, str]] = []
    chunk_rows: list[tuple[str, str, int, str, int, int, int, Jsonb]] = []
    delete_source_ids: list[str] = []

    for path in paths:
        rel_path = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        source_document_id = stable_id("doc", rel_path)
        content_sha = sha256_text(text)
        source_kind = source_kind_for(path)

        source_rows.append((source_document_id, rel_path, source_kind, content_sha))
        if delete_existing:
            delete_source_ids.append(source_document_id)

        for idx, chunk in enumerate(
            chunk_text_with_metadata(
                text,
                chunk_chars,
                overlap_chars,
                source_path=rel_path,
                source_kind=source_kind,
            )
        ):
            chunk_id = stable_id("chunk", f"{rel_path}:{idx}:{sha256_text(chunk.chunk_text)}")
            token_estimate = max(1, len(chunk.chunk_text) // 4)
            chunk_rows.append(
                (
                    chunk_id,
                    source_document_id,
                    idx,
                    chunk.chunk_text,
                    token_estimate,
                    chunk.char_start,
                    chunk.char_end,
                    Jsonb(chunk.metadata),
                )
            )
            chunk_count += 1
        document_count += 1

        if document_count % batch_documents == 0:
            flush_markdown_document_batch(conn, source_rows, chunk_rows, delete_source_ids)
            source_rows.clear()
            chunk_rows.clear()
            delete_source_ids.clear()
            print(progress_message("loaded markdown documents", document_count, total_documents, start_time), flush=True)

    flush_markdown_document_batch(conn, source_rows, chunk_rows, delete_source_ids)
    print(f"loaded markdown documents: {document_count}, chunks: {chunk_count}")


def parse_bool(value: str | None) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def count_csv_data_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return max(0, sum(1 for _ in fh) - 1)


def flush_entity_link_batch(
    conn,
    public_rows: list[tuple],
    unsafe_rows: list[tuple],
) -> None:
    if not public_rows and not unsafe_rows:
        return
    with conn.transaction():
        with conn.cursor() as cur:
            if public_rows:
                cur.executemany(
                    """
                    INSERT INTO fah_sai_lpk_rag.entity_links
                        (source_document_id, chunk_id, artifact_id, source_path, source_type, entity_type,
                         entity_id, linked_table, linked_column, link_method, confidence,
                         is_public_safe, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s)
                    """,
                    public_rows,
                )
            if unsafe_rows:
                cur.executemany(
                    """
                    INSERT INTO fah_sai_lpk_audit.provenance_entity_links
                        (artifact_id, source_path, source_type, entity_type, entity_id,
                         linked_table, linked_column, link_method, confidence,
                         is_public_safe, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, false, %s)
                    """,
                    unsafe_rows,
                )


def load_entity_links(conn, *, batch_size: int = 5000) -> None:
    link_files = [DERIVED_DIR / "DOC_ENTITY_LINKS.csv", DERIVED_DIR / "ARTIFACT_ENTITY_LINKS.csv"]
    total_rows = sum(count_csv_data_rows(path) for path in link_files)
    start_time = time.monotonic()
    processed_count = 0
    public_count = 0
    unsafe_count = 0
    public_rows: list[tuple] = []
    unsafe_rows: list[tuple] = []

    with conn.cursor() as cur:
        cur.execute("SELECT source_path, source_document_id FROM fah_sai_lpk_rag.source_documents")
        source_id_by_path = {row[0]: row[1] for row in cur.fetchall()}
        cur.execute(
            """
            SELECT source_document_id, chunk_id, chunk_text
            FROM fah_sai_lpk_rag.document_chunks
            ORDER BY source_document_id, chunk_index
            """
        )
        chunks_by_source: dict[str, list[tuple[str, str]]] = {}
        for source_document_id, chunk_id, chunk_text_value in cur.fetchall():
            chunks_by_source.setdefault(source_document_id, []).append((chunk_id, chunk_text_value))
        chunk_id_cache: dict[tuple[str, str], str | None] = {}

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
                        entity_id = row.get("entity_id")
                        chunk_id = resolve_entity_chunk_id_from_map(
                            chunks_by_source,
                            source_document_id,
                            entity_id,
                            chunk_id_cache,
                        )
                        public_rows.append(
                            (
                                source_document_id,
                                chunk_id,
                                artifact_id,
                                source_path,
                                row.get("source_type"),
                                row.get("entity_type"),
                                entity_id,
                                row.get("linked_table"),
                                row.get("linked_column"),
                                row.get("link_method"),
                                row.get("confidence") or "1.0",
                                row.get("notes"),
                            )
                        )
                        public_count += 1
                    else:
                        unsafe_rows.append(
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
                            )
                        )
                        unsafe_count += 1
                    processed_count += 1

                    if processed_count % batch_size == 0:
                        flush_entity_link_batch(conn, public_rows, unsafe_rows)
                        public_rows.clear()
                        unsafe_rows.clear()
                        print(progress_message("loaded entity link rows", processed_count, total_rows, start_time), flush=True)
        flush_entity_link_batch(conn, public_rows, unsafe_rows)
    print(f"loaded entity links: public_safe={public_count}, unsafe_audit={unsafe_count}")


def truncate_loaded_tables(conn) -> None:
    raw_tables = ", ".join(f"fah_sai_lpk_raw.{qident(table_name(t))}" for t in OFFICIAL_TABLES)
    core_tables = ", ".join(f"fah_sai_lpk_core.{qident(table_name(t))}" for t in OFFICIAL_TABLES)
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {raw_tables} RESTART IDENTITY")
        cur.execute(f"TRUNCATE {core_tables} RESTART IDENTITY CASCADE")
        cur.execute(
            """
            TRUNCATE
                fah_sai_lpk_rag.entity_links,
                fah_sai_lpk_rag.chunk_embeddings,
                fah_sai_lpk_rag.document_chunks,
                fah_sai_lpk_rag.source_documents,
                fah_sai_lpk_audit.provenance_entity_links,
                fah_sai_lpk_eval.question_tags,
                fah_sai_lpk_eval.answer_runs,
                fah_sai_lpk_eval.questions
            RESTART IDENTITY CASCADE
            """
        )


def truncate_rag_tables(conn) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                TRUNCATE
                    fah_sai_lpk_rag.entity_links,
                    fah_sai_lpk_rag.chunk_embeddings,
                    fah_sai_lpk_rag.document_chunks,
                    fah_sai_lpk_rag.source_documents,
                    fah_sai_lpk_audit.provenance_entity_links
                RESTART IDENTITY CASCADE
                """
            )


def truncate_entity_link_tables(conn) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                TRUNCATE
                    fah_sai_lpk_rag.entity_links,
                    fah_sai_lpk_audit.provenance_entity_links
                RESTART IDENTITY
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
                rows = copy_csv(cur, "fah_sai_lpk_raw", table, path)
                print(f"loaded fah_sai_lpk_raw.{table}: {rows}")
            if load_core:
                rows = copy_csv(cur, "fah_sai_lpk_core", table, path)
                print(f"loaded fah_sai_lpk_core.{table}: {rows}")


def refresh_materialized_views(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regprocedure('fah_sai_lpk_mart.refresh_all_materialized_views(boolean)')")
        if cur.fetchone()[0]:
            cur.execute("SELECT fah_sai_lpk_mart.refresh_all_materialized_views(false)")
            print("refreshed materialized views: non-concurrent first-load mode")
        else:
            print("skipped materialized refresh; run db/004_materialized_marts.sql first")


def configure_bulk_load_session(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = 0")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="Postgres connection URL")
    parser.add_argument("--truncate", action="store_true", help="Truncate loaded schemas before inserting")
    parser.add_argument("--skip-raw", action="store_true", help="Do not load fah_sai_lpk_raw.* CSV tables")
    parser.add_argument("--skip-core", action="store_true", help="Do not load fah_sai_lpk_core.* CSV tables")
    parser.add_argument("--skip-rag", action="store_true", help="Do not load markdown chunks/entity links")
    parser.add_argument("--skip-eval", action="store_true", help="Do not load questions.csv")
    parser.add_argument("--rag-only", action="store_true", help="Only rebuild public RAG documents/chunks/entity links")
    parser.add_argument("--truncate-rag", action="store_true", help="Truncate only RAG document/chunk/link tables before loading")
    parser.add_argument("--entity-links-only", action="store_true", help="Only rebuild RAG entity/provenance links")
    parser.add_argument("--truncate-entity-links", action="store_true", help="Truncate only entity/provenance link tables before loading")
    parser.add_argument(
        "--refresh-materialized",
        action="store_true",
        help="Refresh mart/RAG materialized views after loading, if the refresh function exists",
    )
    parser.add_argument("--chunk-chars", type=int, default=DEFAULT_CHUNK_CHARS)
    parser.add_argument("--chunk-overlap-chars", type=int, default=DEFAULT_CHUNK_OVERLAP_CHARS)
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("Set DATABASE_URL or pass --database-url")
    if args.chunk_overlap_chars >= args.chunk_chars:
        raise SystemExit("--chunk-overlap-chars must be smaller than --chunk-chars")
    if args.truncate and args.truncate_rag:
        raise SystemExit("Use either --truncate or --truncate-rag, not both")
    if args.truncate and args.truncate_entity_links:
        raise SystemExit("Use either --truncate or --truncate-entity-links, not both")

    if args.rag_only:
        args.skip_raw = True
        args.skip_core = True
        args.skip_eval = True
    if args.entity_links_only:
        args.rag_only = True
        args.skip_raw = True
        args.skip_core = True
        args.skip_eval = True
        args.skip_rag = True

    if args.entity_links_only:
        with psycopg.connect(args.database_url, autocommit=True) as conn:
            configure_bulk_load_session(conn)
            if args.truncate_entity_links:
                truncate_entity_link_tables(conn)
                print("truncated entity/provenance link tables", flush=True)
            load_entity_links(conn)
        return 0

    if args.rag_only or args.truncate_rag:
        with psycopg.connect(args.database_url, autocommit=True) as conn:
            configure_bulk_load_session(conn)
            if args.truncate_rag:
                truncate_rag_tables(conn)
                print("truncated RAG document/chunk/link tables", flush=True)
            if not args.skip_rag:
                load_markdown_documents(
                    conn,
                    args.chunk_chars,
                    args.chunk_overlap_chars,
                    delete_existing=not args.truncate_rag,
                )
                load_entity_links(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT to_regprocedure('fah_sai_lpk_audit.analyze_fahmai_model_tables()')")
                if cur.fetchone()[0]:
                    cur.execute("SELECT fah_sai_lpk_audit.analyze_fahmai_model_tables()")
                if args.refresh_materialized:
                    refresh_materialized_views(conn)
        return 0

    with psycopg.connect(args.database_url) as conn:
        configure_bulk_load_session(conn)
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
            cur.execute("SELECT to_regprocedure('fah_sai_lpk_audit.analyze_fahmai_model_tables()')")
            if cur.fetchone()[0]:
                cur.execute("SELECT fah_sai_lpk_audit.analyze_fahmai_model_tables()")
            else:
                print("skipped ANALYZE helper; run db/003_performance_indexes.sql, then call fah_sai_lpk_audit.analyze_fahmai_model_tables()")
            if args.refresh_materialized:
                refresh_materialized_views(conn)

    return 0


if __name__ == "__main__":
    sys.exit(main())
