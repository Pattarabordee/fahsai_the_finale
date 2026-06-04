#!/usr/bin/env python
"""Load FahMai OCR artifact predictions into the OCR schema.

Prerequisites:
  python scripts/apply_db_migrations.py --migrations 009
  pip install psycopg[binary]

Usage:
  python scripts/ingest_ocr_artifacts.py --dry-run --json
  python scripts/ingest_ocr_artifacts.py --database-url $env:DATABASE_URL --run-name ocr-5-artifact-v1

The loader treats 5_artifact.csv as OCR predictions, not official business
facts. Render sidecar source_row_ids are loaded only into audit tables.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit("Missing dependency: pip install psycopg[binary]") from exc


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV_PATH = ROOT / "5_artifact.csv"
DEFAULT_SIDECAR_DIR = (
    ROOT
    / "super-ai-engineer-season-6-fah-mai-the-finale-ocr"
    / "fahmai_renders_with_json"
    / "fahmai_renders_with_json"
    / "per_artifact"
)

BANK_FIELD_RE = re.compile(r"^(L\d+)_(BT-[^_]+)_(.+)$")
VENDOR_PAYMENT_ID_RE = re.compile(r"^VP-\d{6}-\d+$")
BANK_TXN_ID_RE = re.compile(r"^BT-\d{6}-\d+$")
TXN_ID_RE = re.compile(r"^TXN-\d{6}-\d+$")
MONEY_RE = re.compile(r"^[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")
EXPECTED_TYPE_COUNTS = {
    "warranty_form": 1963,
    "vendor_invoice": 792,
    "receipt": 563,
    "bank_statement": 336,
    "t2_doc": 81,
    "t3_doc": 11,
    "e7_banner": 4,
}


@dataclass
class Validation:
    rule_code: str
    severity: str
    field_path: str | None
    raw_value: str | None
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedPrediction:
    artifact_id: str
    artifact_type: str
    source_row_number: int
    raw_pred_json: str
    pred_json: dict[str, Any]
    pred_status: str
    parse_error: str | None = None
    fields: list[tuple[str, str, str | None, Any, str | None, date | None, Decimal | None, bool | None]] = field(
        default_factory=list
    )
    validations: list[Validation] = field(default_factory=list)
    receipt: dict[str, Any] | None = None
    receipt_lines: list[dict[str, Any]] = field(default_factory=list)
    vendor_invoice: dict[str, Any] | None = None
    warranty_claim: dict[str, Any] | None = None
    bank_header: dict[str, Any] | None = None
    bank_transactions: list[dict[str, Any]] = field(default_factory=list)
    e7_banner: dict[str, Any] | None = None
    t3_snapshot: dict[str, Any] | None = None


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def raw_value_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def parse_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    if isinstance(value, int):
        return Decimal(value).quantize(Decimal("0.01"))
    if isinstance(value, float):
        return Decimal(str(value)).quantize(Decimal("0.01"))
    text = str(value).strip()
    if not text:
        return None
    compact = re.sub(r"\s+", "", text)
    if not MONEY_RE.fullmatch(compact):
        return None
    try:
        return Decimal(compact.replace(",", "")).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def parse_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        decimal_value = Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None
    if decimal_value != decimal_value.to_integral_value():
        return None
    return int(decimal_value)


def coerce_year(year_value: int) -> int:
    if year_value >= 2400:
        return year_value - 543
    if 0 <= year_value <= 69:
        return 2000 + year_value
    if 70 <= year_value <= 99:
        return 1900 + year_value
    return year_value


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    iso_match = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if iso_match:
        year = coerce_year(int(iso_match.group(1)))
        try:
            return date(year, int(iso_match.group(2)), int(iso_match.group(3)))
        except ValueError:
            return None
    slash_match = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})", text)
    if slash_match:
        day = int(slash_match.group(1))
        month = int(slash_match.group(2))
        year = coerce_year(int(slash_match.group(3)))
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed_date = parse_date(text)
        if parsed_date:
            return datetime.combine(parsed_date, time.min)
    return None


def parse_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def normalize_field_value(value: Any) -> tuple[str | None, date | None, Decimal | None, bool | None]:
    if isinstance(value, (dict, list)):
        return None, None, None, None
    normalized_text = clean_text(value)
    return normalized_text, parse_date(value), parse_decimal(value), parse_bool(value)


def field_name_from_path(path: str) -> str:
    segment = path.split(".")[-1]
    segment = re.sub(r"\[\d+\]$", "", segment)
    if segment.isdigit() and "." in path:
        segment = path.split(".")[-2]
        segment = re.sub(r"\[\d+\]$", "", segment)
    return segment


def flatten_json(value: Any, path: str = "") -> list[tuple[str, str, str | None, Any, str | None, date | None, Decimal | None, bool | None]]:
    rows = []
    if path:
        normalized_text, normalized_date, normalized_numeric, normalized_boolean = normalize_field_value(value)
        rows.append(
            (
                path,
                field_name_from_path(path),
                raw_value_text(value),
                value,
                normalized_text,
                normalized_date,
                normalized_numeric,
                normalized_boolean,
            )
        )
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            rows.extend(flatten_json(child, child_path))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            child_path = f"{path}[{idx}]"
            rows.extend(flatten_json(child, child_path))
    return rows


def validation(
    rule_code: str,
    severity: str,
    field_path: str | None,
    raw_value: Any,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> Validation:
    return Validation(rule_code, severity, field_path, raw_value_text(raw_value), message, metadata or {})


def date_field(data: dict[str, Any], key: str, validations: list[Validation], *, required: bool = False) -> date | None:
    raw = data.get(key)
    if raw is None or str(raw).strip() == "":
        if required:
            validations.append(validation("missing_date", "warning", key, raw, f"Missing date field {key}"))
        return None
    parsed = parse_date(raw)
    if parsed is None:
        validations.append(validation("invalid_date", "error", key, raw, f"Could not parse date field {key}"))
    return parsed


def timestamp_field(data: dict[str, Any], key: str, validations: list[Validation]) -> datetime | None:
    raw = data.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    parsed = parse_timestamp(raw)
    if parsed is None:
        validations.append(validation("invalid_timestamp", "error", key, raw, f"Could not parse timestamp field {key}"))
    return parsed


def amount_field(data: dict[str, Any], key: str, validations: list[Validation], *, field_path: str | None = None) -> Decimal | None:
    raw = data.get(key)
    path = field_path or key
    if raw is None:
        return None
    if str(raw).strip() == "":
        validations.append(validation("empty_numeric", "warning", path, raw, f"Empty numeric field {path}"))
        return None
    parsed = parse_decimal(raw)
    if parsed is None:
        validations.append(validation("invalid_amount", "error", path, raw, f"Could not parse amount field {path}"))
    return parsed


def int_field(data: dict[str, Any], key: str, validations: list[Validation], *, field_path: str | None = None) -> int | None:
    raw = data.get(key)
    path = field_path or key
    if raw is None or str(raw).strip() == "":
        return None
    parsed = parse_int(raw)
    if parsed is None:
        validations.append(validation("invalid_integer", "error", path, raw, f"Could not parse integer field {path}"))
    return parsed


def normalize_warranty_claim_id(raw_claim_id: Any) -> str | None:
    raw = clean_text(raw_claim_id)
    if not raw:
        return None
    match = re.fullmatch(r"WC-(\d{4})-(\d{2})-(\d+)", raw)
    if match:
        year = coerce_year(int(match.group(1)))
        return f"WC-{year}{match.group(2)}-{match.group(3)}"
    match = re.fullmatch(r"WC-(20\d{2})(\d{2})-(\d+)", raw)
    if match:
        return raw
    return raw


def infer_artifact_type(artifact_id: str) -> str:
    if artifact_id.startswith("WC-"):
        return "warranty_form"
    if artifact_id.startswith("VI-"):
        return "vendor_invoice"
    if artifact_id.startswith("RC-"):
        return "receipt"
    if artifact_id.startswith("BS-"):
        return "bank_statement"
    if artifact_id.startswith("BN-"):
        return "e7_banner"
    if artifact_id.startswith("T3-"):
        return "t3_doc"
    if artifact_id.startswith(("VC-", "POL-", "EMAIL-", "MEMO-", "TRAIN-", "AUD-")):
        return "t2_doc"
    return "unknown"


def build_sidecar_type_map(sidecar_dir: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not sidecar_dir.exists():
        return mapping
    for path in sidecar_dir.rglob("*.json"):
        mapping[path.stem] = path.parent.name
    return mapping


def parse_receipt(data: dict[str, Any], validations: list[Validation]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    receipt = {
        "txn_id": clean_text(data.get("txn_id")),
        "business_event_date": date_field(data, "business_event_date", validations),
        "branch_code": clean_text(data.get("branch_code")),
        "branch_name_th": clean_text(data.get("branch_name_th")),
        "branch_name_en": clean_text(data.get("branch_name_en")),
        "customer_id": clean_text(data.get("customer_id")),
        "employee_id": clean_text(data.get("employee_id")),
        "channel": clean_text(data.get("channel")),
        "basket_total_thb": amount_field(data, "basket_total_thb", validations),
        "discount_total_thb": amount_field(data, "discount_total_thb", validations),
        "net_total_thb": amount_field(data, "net_total_thb", validations),
        "shipping_charge_thb": amount_field(data, "shipping_charge_thb", validations),
        "promo_campaign_id": clean_text(data.get("promo_campaign_id")),
        "payment_method": clean_text(data.get("payment_method")),
        "payment_status": clean_text(data.get("payment_status")),
        "schema_version": clean_text(data.get("schema_version")),
        "is_b2b": parse_bool(data.get("is_b2b")),
        "artifact_id": clean_text(data.get("artifact_id")),
        "pos_id": clean_text(data.get("pos_id")),
        "cash_received_thb": amount_field(data, "cash_received_thb", validations),
        "change_thb": amount_field(data, "change_thb", validations),
    }
    if receipt["txn_id"] and not TXN_ID_RE.fullmatch(receipt["txn_id"]):
        validations.append(validation("malformed_txn_id", "error", "txn_id", receipt["txn_id"], "Receipt txn_id is malformed"))

    ocr_validation = data.get("ocr_validation") if isinstance(data.get("ocr_validation"), dict) else {}
    receipt.update(
        {
            "ocr_validation_status": clean_text(ocr_validation.get("status")),
            "ocr_validation_score": parse_decimal(ocr_validation.get("score")),
            "ocr_validation_issues": clean_text(ocr_validation.get("issues")),
            "ocr_status": clean_text(ocr_validation.get("ocr_status")),
            "ocr_txn_id": clean_text(ocr_validation.get("ocr_txn_id")),
            "ocr_date_iso": parse_date(ocr_validation.get("ocr_date_iso")),
            "ocr_branch_code": clean_text(ocr_validation.get("ocr_branch_code")),
            "ocr_payment_method": clean_text(ocr_validation.get("ocr_payment_method")),
            "ocr_net_total": parse_decimal(ocr_validation.get("ocr_net_total")),
            "ocr_item_count": parse_int(ocr_validation.get("ocr_item_count")),
            "ocr_cache_path": clean_text(ocr_validation.get("ocr_cache_path")),
        }
    )

    line_items_raw = data.get("line_items")
    line_items = line_items_raw if isinstance(line_items_raw, list) else []
    rows = []
    line_total_sum = Decimal("0.00")
    parsed_line_total_count = 0
    for ordinal, item in enumerate(line_items):
        if not isinstance(item, dict):
            validations.append(validation("invalid_line_item", "error", f"line_items[{ordinal}]", item, "Line item is not an object"))
            continue
        line_total = amount_field(item, "line_total_thb", validations, field_path=f"line_items[{ordinal}].line_total_thb")
        if line_total is not None:
            line_total_sum += line_total
            parsed_line_total_count += 1
        rows.append(
            {
                "line_item_ordinal": ordinal,
                "line_item_id": clean_text(item.get("line_item_id")),
                "sku_id": clean_text(item.get("sku_id")),
                "brand_family": clean_text(item.get("brand_family")),
                "category": clean_text(item.get("category")),
                "subcategory": clean_text(item.get("subcategory")),
                "quantity": int_field(item, "quantity", validations, field_path=f"line_items[{ordinal}].quantity"),
                "unit_price_thb": amount_field(item, "unit_price_thb", validations, field_path=f"line_items[{ordinal}].unit_price_thb"),
                "line_discount_thb": amount_field(
                    item, "line_discount_thb", validations, field_path=f"line_items[{ordinal}].line_discount_thb"
                ),
                "line_total_thb": line_total,
                "is_care_plus": parse_bool(item.get("is_care_plus")),
            }
        )

    db_checks = data.get("db_checks") if isinstance(data.get("db_checks"), dict) else {}
    if parse_bool(db_checks.get("line_sum_valid")) is False:
        validations.append(validation("receipt_line_sum_mismatch", "warning", "db_checks.line_sum_valid", False, "Receipt db_checks reports invalid line sum"))
    if parsed_line_total_count == len(rows) and receipt["basket_total_thb"] is not None and line_total_sum != receipt["basket_total_thb"]:
        validations.append(
            validation(
                "receipt_line_sum_mismatch",
                "warning",
                "line_items",
                str(line_total_sum),
                "Receipt line total sum does not match basket_total_thb",
                {"line_sum_thb": str(line_total_sum), "basket_total_thb": str(receipt["basket_total_thb"])},
            )
        )
    return receipt, rows


def parse_vendor_invoice(data: dict[str, Any], validations: list[Validation]) -> dict[str, Any]:
    payment_id = clean_text(data.get("payment_id"))
    if payment_id and not VENDOR_PAYMENT_ID_RE.fullmatch(payment_id):
        validations.append(validation("malformed_payment_id", "error", "payment_id", payment_id, "Vendor payment_id is malformed"))
    return {
        "payment_id": payment_id,
        "vendor_id": clean_text(data.get("vendor_id")),
        "vendor_invoice_id": clean_text(data.get("vendor_invoice_id")),
        "invoice_period_start": date_field(data, "invoice_period_start", validations),
        "invoice_period_end": date_field(data, "invoice_period_end", validations),
        "paid_amount_thb": amount_field(data, "paid_amount_thb", validations),
        "business_event_date": date_field(data, "business_event_date", validations),
    }


def parse_warranty_claim(data: dict[str, Any], validations: list[Validation]) -> dict[str, Any]:
    raw_claim_id = clean_text(data.get("claim_id"))
    return {
        "claim_id_raw": raw_claim_id,
        "claim_id_normalized": normalize_warranty_claim_id(raw_claim_id),
        "business_event_date": date_field(data, "business_event_date", validations),
        "customer_id": clean_text(data.get("customer_id")),
        "sku_id": clean_text(data.get("sku_id")),
        "claim_reason": clean_text(data.get("claim_reason")),
        "claim_amount_thb": amount_field(data, "claim_amount_thb", validations),
    }


def parse_bank_statement(data: dict[str, Any], validations: list[Validation]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    header = None
    if any(key.startswith("L0_") for key in data):
        header = {
            "account_id": clean_text(data.get("L0_account_id")),
            "bank": clean_text(data.get("L0_bank")),
            "account_number": clean_text(data.get("L0_account_number")),
            "account_role": clean_text(data.get("L0_account_role")),
            "currency": clean_text(data.get("L0_currency")),
        }

    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for key, value in data.items():
        match = BANK_FIELD_RE.fullmatch(key)
        if not match:
            continue
        group_label, bank_txn_id, field_name = match.groups()
        if bank_txn_id not in grouped:
            grouped[bank_txn_id] = {"group_label": group_label, "bank_txn_id": bank_txn_id}
            order.append(bank_txn_id)
            if not BANK_TXN_ID_RE.fullmatch(bank_txn_id):
                validations.append(validation("malformed_bank_txn_id", "error", key, bank_txn_id, "Bank transaction id is malformed"))
        grouped[bank_txn_id][field_name] = value

    transactions = []
    for sequence, bank_txn_id in enumerate(order):
        row = grouped[bank_txn_id]
        transactions.append(
            {
                "group_label": row["group_label"],
                "sequence_in_prediction": sequence,
                "bank_txn_id": bank_txn_id,
                "business_event_date": date_field(row, "business_event_date", validations, required=True),
                "transaction_type": clean_text(row.get("transaction_type")),
                "amount_thb": amount_field(row, "amount_thb", validations, field_path=f"{bank_txn_id}.amount_thb"),
                "balance_after_thb": amount_field(row, "balance_after_thb", validations, field_path=f"{bank_txn_id}.balance_after_thb"),
                "description": clean_text(row.get("description")),
                "account_id": clean_text(row.get("account_id")),
            }
        )
    return header, transactions


def parse_e7_banner(data: dict[str, Any], validations: list[Validation]) -> dict[str, Any]:
    return {
        "campaign_id": clean_text(data.get("campaign_id")),
        "description_th": clean_text(data.get("description_th")),
        "start_timestamp": timestamp_field(data, "start_timestamp", validations),
        "end_timestamp": timestamp_field(data, "end_timestamp", validations),
        "scope_filter": clean_text(data.get("scope_filter")),
    }


def parse_t3_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    branch_code = clean_text(data.get("branch_code"))
    vendor_id = clean_text(data.get("vendor_id"))
    return {
        "entity_kind": "branch" if branch_code else "vendor" if vendor_id else "unknown",
        "branch_code": branch_code,
        "vendor_id": vendor_id,
        "name_th": clean_text(data.get("name_th")),
        "name_en": clean_text(data.get("name_en")),
        "branch_type": clean_text(data.get("branch_type")),
        "category": clean_text(data.get("category")),
        "role": clean_text(data.get("role")),
        "payment_terms": clean_text(data.get("payment_terms")),
    }


def finalize_status(status: str, validations: list[Validation]) -> str:
    if status in {"empty", "invalid_json"}:
        return status
    if any(item.severity == "error" for item in validations):
        return "needs_review"
    return status


def parse_prediction(row: dict[str, str], source_row_number: int, artifact_type_map: dict[str, str]) -> ParsedPrediction:
    artifact_id = clean_text(row.get("artifact_id")) or ""
    raw_pred_json = row.get("pred_json") or ""
    artifact_type = artifact_type_map.get(artifact_id) or infer_artifact_type(artifact_id)
    validations: list[Validation] = []

    try:
        parsed_json = json.loads(raw_pred_json) if raw_pred_json.strip() else {}
        if not isinstance(parsed_json, dict):
            validations.append(validation("invalid_json_shape", "error", None, raw_pred_json, "pred_json must be a JSON object"))
            parsed_json = {}
    except json.JSONDecodeError as exc:
        return ParsedPrediction(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            source_row_number=source_row_number,
            raw_pred_json=raw_pred_json,
            pred_json={},
            pred_status="invalid_json",
            parse_error=str(exc),
            validations=[validation("invalid_json", "error", None, raw_pred_json, f"Could not parse pred_json: {exc}")],
        )

    status = "empty" if not parsed_json else "ok"
    if not parsed_json:
        validations.append(validation("empty_json", "warning", None, raw_pred_json, "pred_json is empty"))
    if artifact_type == "unknown":
        validations.append(validation("unknown_artifact_type", "error", "artifact_id", artifact_id, "Could not resolve artifact type"))

    parsed = ParsedPrediction(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        source_row_number=source_row_number,
        raw_pred_json=raw_pred_json,
        pred_json=parsed_json,
        pred_status=status,
        validations=validations,
        fields=flatten_json(parsed_json),
    )

    if parsed_json:
        if artifact_type == "receipt":
            parsed.receipt, parsed.receipt_lines = parse_receipt(parsed_json, parsed.validations)
        elif artifact_type == "vendor_invoice":
            parsed.vendor_invoice = parse_vendor_invoice(parsed_json, parsed.validations)
        elif artifact_type == "warranty_form":
            parsed.warranty_claim = parse_warranty_claim(parsed_json, parsed.validations)
        elif artifact_type == "bank_statement":
            parsed.bank_header, parsed.bank_transactions = parse_bank_statement(parsed_json, parsed.validations)
        elif artifact_type == "e7_banner":
            parsed.e7_banner = parse_e7_banner(parsed_json, parsed.validations)
        elif artifact_type == "t3_doc":
            parsed.t3_snapshot = parse_t3_snapshot(parsed_json)
    parsed.pred_status = finalize_status(parsed.pred_status, parsed.validations)
    return parsed


def parse_csv_predictions(csv_path: Path, sidecar_dir: Path) -> list[ParsedPrediction]:
    artifact_type_map = build_sidecar_type_map(sidecar_dir)
    parsed_rows = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row_number, row in enumerate(reader, start=2):
            parsed_rows.append(parse_prediction(row, row_number, artifact_type_map))
    return parsed_rows


def summarize_parsed_predictions(parsed_rows: list[ParsedPrediction], sidecar_dir: Path) -> dict[str, Any]:
    type_counts = Counter(row.artifact_type for row in parsed_rows)
    status_counts = Counter(row.pred_status for row in parsed_rows)
    validation_counts = Counter(item.rule_code for row in parsed_rows for item in row.validations)
    sidecar_pages = count_sidecar_pages(sidecar_dir)
    return {
        "total_predictions": len(parsed_rows),
        "artifact_type_counts": dict(sorted(type_counts.items())),
        "expected_type_counts": EXPECTED_TYPE_COUNTS,
        "status_counts": dict(sorted(status_counts.items())),
        "empty_json_count": status_counts.get("empty", 0),
        "receipt_line_items": sum(len(row.receipt_lines) for row in parsed_rows),
        "bank_statement_transactions": sum(len(row.bank_transactions) for row in parsed_rows),
        "validation_counts": dict(sorted(validation_counts.items())),
        "sidecar_pages": sidecar_pages,
        "type_count_matches_expected": {key: type_counts.get(key, 0) == expected for key, expected in EXPECTED_TYPE_COUNTS.items()},
    }


def count_sidecar_pages(sidecar_dir: Path) -> int:
    if not sidecar_dir.exists():
        return 0
    total = 0
    for path in sidecar_dir.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        pages = data.get("pages") if isinstance(data, dict) else None
        if isinstance(pages, list):
            total += len(pages)
    return total


def insert_ocr_run(conn, run_name: str, source_csv_path: Path, model_name: str | None, metadata: dict[str, Any]) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO fah_sai_lpk_ocr.ocr_runs (run_name, source_csv_path, model_name, metadata)
            VALUES (%s, %s, %s, %s)
            RETURNING ocr_run_id
            """,
            (run_name, str(source_csv_path), model_name, Jsonb(metadata)),
        )
        return str(cur.fetchone()[0])


def replace_existing_run(conn, run_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM fah_sai_lpk_ocr.ocr_runs WHERE run_name = %s", (run_name,))
        return cur.rowcount


def insert_prediction_row(conn, run_id: str, parsed: ParsedPrediction) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO fah_sai_lpk_ocr.artifact_predictions
                (ocr_run_id, artifact_id, artifact_type, pred_json, raw_pred_json,
                 pred_status, parse_error, source_row_number)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING prediction_id
            """,
            (
                run_id,
                parsed.artifact_id,
                parsed.artifact_type,
                Jsonb(parsed.pred_json),
                parsed.raw_pred_json,
                parsed.pred_status,
                parsed.parse_error,
                parsed.source_row_number,
            ),
        )
        return int(cur.fetchone()[0])


def insert_fields(cur, prediction_id: int, fields: list[tuple[str, str, str | None, Any, str | None, date | None, Decimal | None, bool | None]]) -> None:
    if not fields:
        return
    cur.executemany(
        """
        INSERT INTO fah_sai_lpk_ocr.prediction_fields
            (prediction_id, field_path, field_name, raw_value, value_jsonb,
             normalized_text, normalized_date, normalized_numeric, normalized_boolean)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (prediction_id, field_path) DO UPDATE SET
            field_name = EXCLUDED.field_name,
            raw_value = EXCLUDED.raw_value,
            value_jsonb = EXCLUDED.value_jsonb,
            normalized_text = EXCLUDED.normalized_text,
            normalized_date = EXCLUDED.normalized_date,
            normalized_numeric = EXCLUDED.normalized_numeric,
            normalized_boolean = EXCLUDED.normalized_boolean
        """,
        [
            (prediction_id, path, name, raw, Jsonb(value), text, parsed_date, numeric, boolean)
            for path, name, raw, value, text, parsed_date, numeric, boolean in fields
        ],
    )


def insert_validations(cur, prediction_id: int, validations: list[Validation]) -> None:
    if not validations:
        return
    cur.executemany(
        """
        INSERT INTO fah_sai_lpk_ocr.prediction_validations
            (prediction_id, rule_code, severity, field_path, raw_value, message, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        [
            (
                prediction_id,
                item.rule_code,
                item.severity,
                item.field_path,
                item.raw_value,
                item.message,
                Jsonb(item.metadata),
            )
            for item in validations
        ],
    )


def insert_receipt(cur, prediction_id: int, row: dict[str, Any]) -> None:
    columns = list(row)
    cur.execute(
        f"""
        INSERT INTO fah_sai_lpk_ocr.ocr_receipts (prediction_id, {", ".join(columns)})
        VALUES (%s, {", ".join(["%s"] * len(columns))})
        ON CONFLICT (prediction_id) DO UPDATE SET
            {", ".join(f"{column} = EXCLUDED.{column}" for column in columns)}
        """,
        (prediction_id, *[row[column] for column in columns]),
    )


def insert_receipt_lines(cur, prediction_id: int, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    cur.executemany(
        f"""
        INSERT INTO fah_sai_lpk_ocr.ocr_receipt_line_items (prediction_id, {", ".join(columns)})
        VALUES (%s, {", ".join(["%s"] * len(columns))})
        ON CONFLICT (prediction_id, line_item_ordinal) DO UPDATE SET
            {", ".join(f"{column} = EXCLUDED.{column}" for column in columns if column != "line_item_ordinal")}
        """,
        [(prediction_id, *[row[column] for column in columns]) for row in rows],
    )


def insert_single_typed_row(cur, table: str, prediction_id: int, row: dict[str, Any]) -> None:
    columns = list(row)
    cur.execute(
        f"""
        INSERT INTO fah_sai_lpk_ocr.{table} (prediction_id, {", ".join(columns)})
        VALUES (%s, {", ".join(["%s"] * len(columns))})
        ON CONFLICT (prediction_id) DO UPDATE SET
            {", ".join(f"{column} = EXCLUDED.{column}" for column in columns)}
        """,
        (prediction_id, *[row[column] for column in columns]),
    )


def insert_bank_transactions(cur, prediction_id: int, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    cur.executemany(
        f"""
        INSERT INTO fah_sai_lpk_ocr.ocr_bank_statement_transactions (prediction_id, {", ".join(columns)})
        VALUES (%s, {", ".join(["%s"] * len(columns))})
        ON CONFLICT (prediction_id, bank_txn_id) DO UPDATE SET
            {", ".join(f"{column} = EXCLUDED.{column}" for column in columns if column != "bank_txn_id")}
        """,
        [(prediction_id, *[row[column] for column in columns]) for row in rows],
    )


def load_predictions(conn, run_id: str, parsed_rows: list[ParsedPrediction]) -> dict[str, int]:
    counts = Counter()
    for parsed in parsed_rows:
        prediction_id = insert_prediction_row(conn, run_id, parsed)
        with conn.cursor() as cur:
            insert_fields(cur, prediction_id, parsed.fields)
            insert_validations(cur, prediction_id, parsed.validations)
            if parsed.receipt is not None:
                insert_receipt(cur, prediction_id, parsed.receipt)
                insert_receipt_lines(cur, prediction_id, parsed.receipt_lines)
                counts["ocr_receipts"] += 1
                counts["ocr_receipt_line_items"] += len(parsed.receipt_lines)
            if parsed.vendor_invoice is not None:
                insert_single_typed_row(cur, "ocr_vendor_invoices", prediction_id, parsed.vendor_invoice)
                counts["ocr_vendor_invoices"] += 1
            if parsed.warranty_claim is not None:
                insert_single_typed_row(cur, "ocr_warranty_claims", prediction_id, parsed.warranty_claim)
                counts["ocr_warranty_claims"] += 1
            if parsed.bank_header is not None:
                insert_single_typed_row(cur, "ocr_bank_statement_headers", prediction_id, parsed.bank_header)
                counts["ocr_bank_statement_headers"] += 1
            if parsed.bank_transactions:
                insert_bank_transactions(cur, prediction_id, parsed.bank_transactions)
                counts["ocr_bank_statement_transactions"] += len(parsed.bank_transactions)
            if parsed.e7_banner is not None:
                insert_single_typed_row(cur, "ocr_e7_banners", prediction_id, parsed.e7_banner)
                counts["ocr_e7_banners"] += 1
            if parsed.t3_snapshot is not None:
                insert_single_typed_row(cur, "ocr_t3_entity_snapshots", prediction_id, parsed.t3_snapshot)
                counts["ocr_t3_entity_snapshots"] += 1
            counts["prediction_fields"] += len(parsed.fields)
            counts["prediction_validations"] += len(parsed.validations)
            counts["artifact_predictions"] += 1
    return dict(counts)


def load_sidecar_provenance(conn, sidecar_dir: Path) -> int:
    if not sidecar_dir.exists():
        return 0
    rows = []
    for path in sidecar_dir.rglob("*.json"):
        artifact_type = path.parent.name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        pages = data.get("pages") if isinstance(data, dict) else None
        if not isinstance(pages, list):
            continue
        for page in pages:
            if not isinstance(page, dict):
                continue
            rows.append(
                (
                    data.get("artifact_id") or path.stem,
                    artifact_type,
                    page.get("output_path"),
                    page.get("page_kind"),
                    data.get("renderer_template_id"),
                    data.get("template_version"),
                    page.get("source_fact_table"),
                    [str(item) for item in page.get("source_row_ids") or []],
                    [str(item) for item in page.get("visible_fields") or []],
                    False,
                    Jsonb({"all_source_row_ids": data.get("all_source_row_ids") or []}),
                )
            )
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO fah_sai_lpk_audit.render_provenance_pages
                (artifact_id, artifact_type, output_path, page_kind, renderer_template_id,
                 template_version, source_fact_table, source_row_ids, visible_fields,
                 is_public_safe, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (artifact_id, output_path) DO UPDATE SET
                artifact_type = EXCLUDED.artifact_type,
                page_kind = EXCLUDED.page_kind,
                renderer_template_id = EXCLUDED.renderer_template_id,
                template_version = EXCLUDED.template_version,
                source_fact_table = EXCLUDED.source_fact_table,
                source_row_ids = EXCLUDED.source_row_ids,
                visible_fields = EXCLUDED.visible_fields,
                is_public_safe = false,
                metadata = EXCLUDED.metadata
            """,
            rows,
        )
    return len(rows)


def core_table_has_rows(conn, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)::text", (f"fah_sai_lpk_core.{table}",))
        if cur.fetchone()[0] is None:
            return False
        cur.execute(f"SELECT EXISTS (SELECT 1 FROM fah_sai_lpk_core.{table} LIMIT 1)")
        return bool(cur.fetchone()[0])


def insert_core_validation_sql(conn, run_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        if core_table_has_rows(conn, "fact_sales"):
            cur.execute(
                """
                INSERT INTO fah_sai_lpk_ocr.prediction_validations
                    (prediction_id, rule_code, severity, field_path, raw_value, message, metadata)
                SELECT o.prediction_id, 'core_table_mismatch', 'warning', 'txn_id', o.txn_id,
                       'No matching core.fact_sales row for OCR txn_id',
                       jsonb_build_object('core_table', 'fact_sales')
                FROM fah_sai_lpk_ocr.ocr_receipts o
                JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = o.prediction_id
                WHERE p.ocr_run_id = %s
                  AND o.txn_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM fah_sai_lpk_core.fact_sales s WHERE s.txn_id = o.txn_id
                  )
                """,
                (run_id,),
            )
            counts["receipt_missing_core"] = cur.rowcount
            cur.execute(
                """
                INSERT INTO fah_sai_lpk_ocr.prediction_validations
                    (prediction_id, rule_code, severity, field_path, raw_value, message, metadata)
                SELECT o.prediction_id, 'core_value_mismatch', 'warning', 'txn_id', o.txn_id,
                       'OCR receipt differs from core.fact_sales on date, branch, net total, or payment method',
                       jsonb_build_object('core_table', 'fact_sales')
                FROM fah_sai_lpk_ocr.ocr_receipts o
                JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = o.prediction_id
                WHERE p.ocr_run_id = %s
                  AND EXISTS (SELECT 1 FROM fah_sai_lpk_core.fact_sales s WHERE s.txn_id = o.txn_id)
                  AND NOT EXISTS (
                      SELECT 1
                      FROM fah_sai_lpk_core.fact_sales s
                      WHERE s.txn_id = o.txn_id
                        AND s.business_event_date IS NOT DISTINCT FROM o.business_event_date
                        AND s.branch_code IS NOT DISTINCT FROM o.branch_code
                        AND s.net_total_thb IS NOT DISTINCT FROM o.net_total_thb
                        AND s.payment_method IS NOT DISTINCT FROM o.payment_method
                  )
                """,
                (run_id,),
            )
            counts["receipt_value_mismatch"] = cur.rowcount

        if core_table_has_rows(conn, "fact_vendor_payment"):
            cur.execute(
                """
                INSERT INTO fah_sai_lpk_ocr.prediction_validations
                    (prediction_id, rule_code, severity, field_path, raw_value, message, metadata)
                SELECT o.prediction_id, 'core_table_mismatch', 'warning', 'vendor_invoice_id', o.vendor_invoice_id,
                       'No matching core.fact_vendor_payment row for OCR vendor_invoice_id',
                       jsonb_build_object('core_table', 'fact_vendor_payment')
                FROM fah_sai_lpk_ocr.ocr_vendor_invoices o
                JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = o.prediction_id
                WHERE p.ocr_run_id = %s
                  AND o.vendor_invoice_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM fah_sai_lpk_core.fact_vendor_payment vp
                      WHERE vp.vendor_invoice_id = o.vendor_invoice_id
                  )
                """,
                (run_id,),
            )
            counts["vendor_missing_core"] = cur.rowcount
            cur.execute(
                """
                INSERT INTO fah_sai_lpk_ocr.prediction_validations
                    (prediction_id, rule_code, severity, field_path, raw_value, message, metadata)
                SELECT o.prediction_id, 'core_value_mismatch', 'warning', 'vendor_invoice_id', o.vendor_invoice_id,
                       'OCR vendor invoice has no exact matching core.fact_vendor_payment value set',
                       jsonb_build_object('core_table', 'fact_vendor_payment')
                FROM fah_sai_lpk_ocr.ocr_vendor_invoices o
                JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = o.prediction_id
                WHERE p.ocr_run_id = %s
                  AND EXISTS (
                      SELECT 1 FROM fah_sai_lpk_core.fact_vendor_payment vp
                      WHERE vp.vendor_invoice_id = o.vendor_invoice_id
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM fah_sai_lpk_core.fact_vendor_payment vp
                      WHERE vp.vendor_invoice_id = o.vendor_invoice_id
                        AND vp.vendor_id IS NOT DISTINCT FROM o.vendor_id
                        AND vp.business_event_date IS NOT DISTINCT FROM o.business_event_date
                        AND vp.invoice_period_start IS NOT DISTINCT FROM o.invoice_period_start
                        AND vp.invoice_period_end IS NOT DISTINCT FROM o.invoice_period_end
                        AND vp.paid_amount_thb IS NOT DISTINCT FROM o.paid_amount_thb
                  )
                """,
                (run_id,),
            )
            counts["vendor_value_mismatch"] = cur.rowcount

        if core_table_has_rows(conn, "fact_warranty_claim"):
            cur.execute(
                """
                INSERT INTO fah_sai_lpk_ocr.prediction_validations
                    (prediction_id, rule_code, severity, field_path, raw_value, message, metadata)
                SELECT o.prediction_id, 'core_table_mismatch', 'warning', 'claim_id', o.claim_id_normalized,
                       'No matching core.fact_warranty_claim row for OCR claim_id',
                       jsonb_build_object('core_table', 'fact_warranty_claim')
                FROM fah_sai_lpk_ocr.ocr_warranty_claims o
                JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = o.prediction_id
                WHERE p.ocr_run_id = %s
                  AND o.claim_id_normalized IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM fah_sai_lpk_core.fact_warranty_claim w
                      WHERE w.claim_id = o.claim_id_normalized
                  )
                """,
                (run_id,),
            )
            counts["warranty_missing_core"] = cur.rowcount
            cur.execute(
                """
                INSERT INTO fah_sai_lpk_ocr.prediction_validations
                    (prediction_id, rule_code, severity, field_path, raw_value, message, metadata)
                SELECT o.prediction_id, 'core_value_mismatch', 'warning', 'claim_id', o.claim_id_normalized,
                       'OCR warranty claim differs from core.fact_warranty_claim',
                       jsonb_build_object('core_table', 'fact_warranty_claim')
                FROM fah_sai_lpk_ocr.ocr_warranty_claims o
                JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = o.prediction_id
                WHERE p.ocr_run_id = %s
                  AND EXISTS (
                      SELECT 1 FROM fah_sai_lpk_core.fact_warranty_claim w
                      WHERE w.claim_id = o.claim_id_normalized
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM fah_sai_lpk_core.fact_warranty_claim w
                      WHERE w.claim_id = o.claim_id_normalized
                        AND w.business_event_date IS NOT DISTINCT FROM o.business_event_date
                        AND w.customer_id IS NOT DISTINCT FROM o.customer_id
                        AND w.sku_id IS NOT DISTINCT FROM o.sku_id
                        AND w.claim_reason IS NOT DISTINCT FROM o.claim_reason
                        AND w.claim_amount_thb IS NOT DISTINCT FROM o.claim_amount_thb
                  )
                """,
                (run_id,),
            )
            counts["warranty_value_mismatch"] = cur.rowcount

        if core_table_has_rows(conn, "fact_bank_transaction"):
            cur.execute(
                """
                INSERT INTO fah_sai_lpk_ocr.prediction_validations
                    (prediction_id, rule_code, severity, field_path, raw_value, message, metadata)
                SELECT o.prediction_id, 'core_table_mismatch', 'warning', 'bank_txn_id', o.bank_txn_id,
                       'No matching core.fact_bank_transaction row for OCR bank_txn_id',
                       jsonb_build_object('core_table', 'fact_bank_transaction')
                FROM fah_sai_lpk_ocr.ocr_bank_statement_transactions o
                JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = o.prediction_id
                WHERE p.ocr_run_id = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM fah_sai_lpk_core.fact_bank_transaction bt
                      WHERE bt.bank_txn_id = o.bank_txn_id
                  )
                """,
                (run_id,),
            )
            counts["bank_missing_core"] = cur.rowcount
            cur.execute(
                """
                INSERT INTO fah_sai_lpk_ocr.prediction_validations
                    (prediction_id, rule_code, severity, field_path, raw_value, message, metadata)
                SELECT o.prediction_id, 'core_value_mismatch', 'warning', 'bank_txn_id', o.bank_txn_id,
                       'OCR bank transaction differs from core.fact_bank_transaction',
                       jsonb_build_object('core_table', 'fact_bank_transaction')
                FROM fah_sai_lpk_ocr.ocr_bank_statement_transactions o
                JOIN fah_sai_lpk_ocr.artifact_predictions p ON p.prediction_id = o.prediction_id
                WHERE p.ocr_run_id = %s
                  AND EXISTS (
                      SELECT 1 FROM fah_sai_lpk_core.fact_bank_transaction bt
                      WHERE bt.bank_txn_id = o.bank_txn_id
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM fah_sai_lpk_core.fact_bank_transaction bt
                      WHERE bt.bank_txn_id = o.bank_txn_id
                        AND bt.business_event_date IS NOT DISTINCT FROM o.business_event_date
                        AND bt.account_id IS NOT DISTINCT FROM o.account_id
                        AND bt.amount_thb IS NOT DISTINCT FROM o.amount_thb
                        AND bt.balance_after_thb IS NOT DISTINCT FROM o.balance_after_thb
                  )
                """,
                (run_id,),
            )
            counts["bank_value_mismatch"] = cur.rowcount
    return counts


def mark_finished(conn, run_id: str, metadata: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE fah_sai_lpk_ocr.ocr_runs
            SET finished_at = now(), metadata = metadata || %s::jsonb
            WHERE ocr_run_id = %s
            """,
            (json.dumps(metadata, ensure_ascii=False), run_id),
        )


def analyze_ocr_tables(conn) -> None:
    tables = [
        "artifact_predictions",
        "prediction_fields",
        "prediction_validations",
        "ocr_receipts",
        "ocr_receipt_line_items",
        "ocr_vendor_invoices",
        "ocr_warranty_claims",
        "ocr_bank_statement_headers",
        "ocr_bank_statement_transactions",
        "ocr_e7_banners",
        "ocr_t3_entity_snapshots",
    ]
    with conn.cursor() as cur:
        for table in tables:
            cur.execute(f"ANALYZE fah_sai_lpk_ocr.{table}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="PostgreSQL connection URL")
    parser.add_argument("--csv-path", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--sidecar-dir", type=Path, default=DEFAULT_SIDECAR_DIR)
    parser.add_argument("--run-name", default="ocr-5-artifact")
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--replace-run", action="store_true", help="Delete existing OCR runs with the same run name before loading")
    parser.add_argument("--skip-sidecars", action="store_true", help="Do not load per_artifact sidecar provenance")
    parser.add_argument("--skip-core-validation", action="store_true", help="Skip optional validations against fah_sai_lpk_core tables")
    parser.add_argument("--dry-run", action="store_true", help="Parse files and print counts without connecting to PostgreSQL")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    if not args.csv_path.exists():
        raise SystemExit(f"CSV file not found: {args.csv_path}")

    parsed_rows = parse_csv_predictions(args.csv_path, args.sidecar_dir)
    summary = summarize_parsed_predictions(parsed_rows, args.sidecar_dir)
    if args.dry_run:
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print(f"parsed predictions: {summary['total_predictions']}")
            print(f"artifact types: {summary['artifact_type_counts']}")
            print(f"statuses: {summary['status_counts']}")
            print(f"validations: {summary['validation_counts']}")
        return 0

    if not args.database_url:
        raise SystemExit("Set DATABASE_URL or pass --database-url")

    with psycopg.connect(args.database_url) as conn:
        with conn.transaction():
            if args.replace_run:
                deleted_runs = replace_existing_run(conn, args.run_name)
            else:
                deleted_runs = 0
            run_id = insert_ocr_run(
                conn,
                args.run_name,
                args.csv_path,
                args.model_name,
                {"parse_summary": summary, "deleted_replaced_runs": deleted_runs},
            )
            sidecar_rows = 0 if args.skip_sidecars else load_sidecar_provenance(conn, args.sidecar_dir)
            inserted_counts = load_predictions(conn, run_id, parsed_rows)
            core_validation_counts = {} if args.skip_core_validation else insert_core_validation_sql(conn, run_id)
            mark_finished(
                conn,
                run_id,
                {
                    "inserted_counts": inserted_counts,
                    "sidecar_provenance_pages": sidecar_rows,
                    "core_validation_counts": core_validation_counts,
                },
            )
            analyze_ocr_tables(conn)

    result = {
        "ocr_run_id": run_id,
        "parse_summary": summary,
        "inserted_counts": inserted_counts,
        "sidecar_provenance_pages": sidecar_rows,
        "core_validation_counts": core_validation_counts,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"loaded OCR run {run_id}")
        print(f"inserted: {inserted_counts}")
        print(f"sidecar provenance pages: {sidecar_rows}")
        print(f"core validations: {core_validation_counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
