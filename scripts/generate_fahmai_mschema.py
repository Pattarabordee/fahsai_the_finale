#!/usr/bin/env python
"""Generate FahMai M-Schema artifacts for Text-to-SQL prompts.

The live PostgreSQL database is the preferred source of truth. When no database
URL is supplied, this script falls back to a metadata-only representation parsed
from the migration files plus the stable model-facing view contracts. By
default, it emits only the compact fah_sai_lpk_model schema. Legacy mode is
available for inspection, but it cannot overwrite the default LLM prompt
artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEXT_OUTPUT = ROOT / "derived" / "fahmai_model_mschema.txt"
DEFAULT_JSON_OUTPUT = ROOT / "derived" / "fahmai_model_mschema.json"
DEFAULT_CORE_TEXT_OUTPUT = ROOT / "derived" / "fahmai_core_mschema.txt"
DEFAULT_CORE_JSON_OUTPUT = ROOT / "derived" / "fahmai_core_mschema.json"
DEFAULT_DDL_FILES = sorted((ROOT / "db").glob("*.sql"))

MODEL_SCHEMA = "fah_sai_lpk_model"
CORE_SCHEMA = "fah_sai_lpk_core"
MODEL_SURFACE_VIEWS = {
    "sales_order_360",
    "sales_line_360",
    "finance_event",
    "customer_ops_event",
    "inventory_event",
    "product_catalog",
    "policy_catalog",
    "document_evidence",
}
CORE_TABLE_COUNT_RANGE = range(31, 33)
MODEL_CITATION_COLUMNS = {"source_table", "source_pk"}
MODEL_CITATION_COLUMN_HINTS = {
    "source_table": "Official source table for citation and routing.",
    "source_pk": "Official source primary key for citation and audit trace.",
}
MODEL_MART_VIEWS = {
    "v_sales_order",
    "v_sales_line",
    "v_bank_reconciliation",
    "v_sales_deposit_batch_reconciliation",
    "v_vendor_payment",
}
MODEL_RAG_OBJECTS = {"v_public_retrievable_chunks", "entity_links"}
MODEL_EVAL_TABLES = {
    "questions",
    "question_tags",
    "sql_templates",
    "source_authority_rules",
}
SCHEMA_ORDER = {
    "fah_sai_lpk_model": 0,
    "fah_sai_lpk_core": 10,
    "fah_sai_lpk_mart": 11,
    "fah_sai_lpk_rag": 12,
    "fah_sai_lpk_eval": 13,
}

TYPE_STOP_RE = re.compile(
    r"\b(PRIMARY\s+KEY|NOT\s+NULL|NULL|DEFAULT|REFERENCES|CHECK|GENERATED|"
    r"UNIQUE|COLLATE)\b",
    re.IGNORECASE,
)
COMMENT_TABLE_RE = re.compile(
    r"COMMENT\s+ON\s+TABLE\s+([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)\s+IS\s+'((?:''|[^'])*)'\s*;",
    re.IGNORECASE | re.DOTALL,
)
COMMENT_COLUMN_RE = re.compile(
    r"COMMENT\s+ON\s+COLUMN\s+([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)"
    r"\s+IS\s+'((?:''|[^'])*)'\s*;",
    re.IGNORECASE | re.DOTALL,
)
CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)"
    r"\s*\((.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
ALTER_FK_RE = re.compile(
    r"ALTER\s+TABLE\s+([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*).*?"
    r"FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+"
    r"([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)\s*\(([^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)
MSCHEMA_TABLE_HEADER_RE = re.compile(r"^# Table:\s+([^,\s]+)", re.MULTILINE)

SENSITIVE_COLUMN_RE = re.compile(
    r"(email|phone|first_name|last_name|name_th|name_en|customer_name|"
    r"employee_name|description|notes|chunk_text|embedding|metadata|"
    r"sql_template|answer|reviewer|body|content|text$)",
    re.IGNORECASE,
)
SAFE_TEXT_COLUMN_RE = re.compile(
    r"(^.*_id$|^.*_code$|.*_date$|.*_timestamp$|^.*_status$|^.*_type$|"
    r"^.*_kind$|^.*_tier$|^.*_channel$|^.*_method$|^.*_role$|"
    r"^.*_family$|^.*category$|^.*subcategory$|^.*province$|^.*region$|"
    r"^.*currency$|^.*_table$|^.*_column$|^.*difficulty$|^.*tag$|"
    r"^.*_scope$|^.*_authority$|^.*allowed_for_final_answer$)",
    re.IGNORECASE,
)
SKIPPED_EXAMPLE_TYPE_RE = re.compile(
    r"(json|vector|tsvector|\[\]|array|bytea)", re.IGNORECASE
)

TABLE_HINTS = {
    "fah_sai_lpk_model.sales_order_360": (
        "Model-facing sales order surface. Grain: one row per FACT_SALES.txn_id. "
        "Use for order counts, branch/channel/customer/payment status, basket/net totals, B2B AR, and sales-header questions."
    ),
    "fah_sai_lpk_model.sales_line_360": (
        "Model-facing sales line surface. Grain: one row per FACT_SALES_LINE_ITEM.line_item_id. "
        "Use for SKU/product/category/vendor units and line_total_thb revenue. Do not sum order totals from this line-grain view."
    ),
    "fah_sai_lpk_model.finance_event": (
        "Model-facing finance event surface combining bank transactions, refund paid, vendor payment, and payroll."
    ),
    "fah_sai_lpk_model.customer_ops_event": (
        "Model-facing customer operations event surface combining returns, warranty claims, CS interactions, shipping, loyalty ledger, and promo redemptions."
    ),
    "fah_sai_lpk_model.inventory_event": (
        "Model-facing inventory event surface combining inventory movements and monthly snapshots."
    ),
    "fah_sai_lpk_model.product_catalog": (
        "Model-facing product catalog surface. Grain: one row per DIM_PRODUCT.sku_id with department, vendor, care-plus, and recall context."
    ),
    "fah_sai_lpk_model.policy_catalog": (
        "Model-facing policy/catalog surface for policy versions, signing authority ladder rows, promo campaigns/mechanics, and vendor contract versions."
    ),
    "fah_sai_lpk_model.document_evidence": (
        "Model-facing public-safe document evidence surface over compact BGE-M3 parent-child RAG chunks and entity links."
    ),
    "fah_sai_lpk_core.fact_sales": "Official sales order/header fact; one row per txn_id.",
    "fah_sai_lpk_core.fact_sales_line_item": "Official sales line fact; one row per line_item_id.",
    "fah_sai_lpk_core.fact_bank_transaction": "Official bank transaction fact and reconciliation spine.",
    "fah_sai_lpk_core.fact_return": "Official return fact for product/customer return events.",
    "fah_sai_lpk_core.fact_refund_paid": "Official refund payout fact with approval and bank context.",
    "fah_sai_lpk_core.fact_vendor_payment": "Official vendor payment fact with invoice and contract context.",
    "fah_sai_lpk_core.t2_doc_inventory": "Official document inventory; lineage hints are not normal FKs.",
    "fah_sai_lpk_mart.v_sales_order": "Model-facing sales order view; one row per transaction.",
    "fah_sai_lpk_mart.v_sales_line": "Model-facing sales line view; one row per sales line item.",
    "fah_sai_lpk_mart.v_bank_reconciliation": "Model-facing bank reconciliation view; one row per bank_txn_id.",
    "fah_sai_lpk_mart.v_sales_deposit_batch_reconciliation": (
        "Virtual QA view for sales deposit batch reconciliation; not an official table."
    ),
    "fah_sai_lpk_mart.v_vendor_payment": "Model-facing vendor payment view with vendor, contract, and bank context.",
    "fah_sai_lpk_rag.v_public_retrievable_chunks": "Public-safe retrieval view for chunks and optional embeddings.",
    "fah_sai_lpk_rag.entity_links": "Public-safe links from retrieved evidence back to official entities.",
    "fah_sai_lpk_eval.questions": "Public eval questions loaded from questions.csv.",
    "fah_sai_lpk_eval.question_tags": "Rule-based tags used to route eval questions.",
    "fah_sai_lpk_eval.sql_templates": "Reusable SQL templates for retrieval and answer generation.",
    "fah_sai_lpk_eval.source_authority_rules": "Source authority policy for final-answer evidence.",
}

COLUMN_HINTS = {
    "fah_sai_lpk_model.sales_order_360.source_table": "Official source table for citation; this view cites FACT_SALES rows.",
    "fah_sai_lpk_model.sales_order_360.txn_id": "Sales order grain. One row per txn_id.",
    "fah_sai_lpk_model.sales_line_360.line_item_id": "Sales line item grain. One row per line_item_id.",
    "fah_sai_lpk_model.sales_line_360.line_total_thb": "Use for SKU/product gross revenue from line-level sales.",
    "fah_sai_lpk_model.sales_line_360.order_net_total_thb": "Repeated order-level value. Do not sum this from line-grain rows.",
    "fah_sai_lpk_model.finance_event.source_table": "Official source table for citation and routing.",
    "fah_sai_lpk_model.customer_ops_event.source_table": "Official source table for citation and routing.",
    "fah_sai_lpk_model.inventory_event.related_txn_id": "Polymorphic id; TXN-* can point to sales and XFER-* is an internal transfer id.",
    "fah_sai_lpk_model.policy_catalog.effective_date": (
        "Policy/catalog start date. For active-version lookup use effective_date <= target date "
        "and (end_date IS NULL OR target date < end_date) unless the question states an inclusive end-date rule."
    ),
    "fah_sai_lpk_model.document_evidence.has_embedding": (
        "True when this public-safe BGE-M3 child chunk has a 1024-dimensional embedding available through match_public_chunks_bge_m3."
    ),
    "fah_sai_lpk_model.document_evidence.retrieval_profile": (
        "Retrieval profile for embedded evidence. Default production profile is bge_m3_v1."
    ),
    "fah_sai_lpk_model.document_evidence.child_chunk_id": (
        "Embedding-grain child chunk id for BGE-M3 retrieval and citations."
    ),
    "fah_sai_lpk_model.document_evidence.parent_chunk_id": (
        "Parent context row used to hydrate this embedded child chunk."
    ),
    "fah_sai_lpk_model.document_evidence.parent_text": (
        "Hydrated parent context for the matched child chunk. Use for answer context, not as a separate table."
    ),
    "fah_sai_lpk_core.fact_bank_transaction.related_entity_table": (
        "Polymorphic discriminator; FACT_SALES_DEPOSIT_BATCH is virtual."
    ),
    "fah_sai_lpk_core.fact_inventory_movement.related_txn_id": (
        "Polymorphic id; TXN-* can point to sales and XFER-* is an internal transfer id."
    ),
    "fah_sai_lpk_rag.entity_links.chunk_id": "Join to fah_sai_lpk_rag.v_public_retrievable_chunks.chunk_id when present.",
    "fah_sai_lpk_rag.entity_links.linked_table": "Official table name for the linked entity.",
    "fah_sai_lpk_rag.entity_links.entity_id": "Official entity identifier found in public-safe evidence.",
    "fah_sai_lpk_mart.v_sales_order.txn_id": "Sales order grain.",
    "fah_sai_lpk_mart.v_sales_line.line_item_id": "Sales line item grain.",
    "fah_sai_lpk_mart.v_bank_reconciliation.bank_txn_id": "Bank transaction grain.",
}

FACT_DATE_COLUMN_HINTS = {
    "business_event_date": (
        "Canonical default date axis for fact period filters. If a question asks "
        "for a year/month/quarter without naming a date column, filter here."
    ),
    "posting_date": (
        "Accounting posting date. Use only when the question explicitly asks for "
        "posted/booked/accounting timing."
    ),
    "effective_date": "Fact-row effective metadata; not the default period filter.",
    "as_of_date": "Bundle/snapshot as-of metadata; not the event period filter.",
}

VENDOR_PAYMENT_DATE_COLUMN_HINTS = {
    **FACT_DATE_COLUMN_HINTS,
    "business_event_date": (
        "Canonical default date axis for vendor-payment period filters. Posting "
        "date may lag by about 28 days because of NET-30 terms."
    ),
    "posting_date": (
        "Accounting posting date for vendor payments. Use only for explicit "
        "posted/booked/accounting timing; may lag business_event_date because "
        "of NET-30 terms."
    ),
}

MODEL_MART_DATE_HINT_TABLES = {
    "fah_sai_lpk_mart.v_sales_order",
    "fah_sai_lpk_mart.v_sales_line",
    "fah_sai_lpk_mart.v_bank_reconciliation",
    "fah_sai_lpk_mart.v_sales_deposit_batch_reconciliation",
    "fah_sai_lpk_mart.v_vendor_payment",
}
MODEL_SURFACE_DATE_HINT_TABLES = {
    "fah_sai_lpk_model.sales_order_360",
    "fah_sai_lpk_model.sales_line_360",
    "fah_sai_lpk_model.finance_event",
    "fah_sai_lpk_model.customer_ops_event",
    "fah_sai_lpk_model.inventory_event",
}


@dataclass
class FieldInfo:
    type: str
    primary_key: bool = False
    nullable: bool = True
    default: str | None = None
    autoincrement: bool = False
    comment: str = ""
    examples: list[str] = field(default_factory=list)


@dataclass
class TableInfo:
    type: str
    comment: str = ""
    fields: dict[str, FieldInfo] = field(default_factory=dict)
    examples: list[Any] = field(default_factory=list)


@dataclass
class MSchemaModel:
    db_id: str
    schema: None = None
    tables: dict[str, TableInfo] = field(default_factory=dict)
    foreign_keys: list[list[str]] = field(default_factory=list)


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def qualified(schema: str, name: str) -> str:
    return f"{schema}.{name}"


def expected_model_surface_relations() -> set[str]:
    return {qualified(MODEL_SCHEMA, view_name) for view_name in MODEL_SURFACE_VIEWS}


def path_matches(path: Path, expected: Path) -> bool:
    try:
        return path.resolve() == expected.resolve()
    except OSError:
        return path == expected


def ensure_legacy_outputs_are_explicit(schema_mode: str, output_text: Path, output_json: Path) -> None:
    if schema_mode == "model":
        return
    if path_matches(output_text, DEFAULT_TEXT_OUTPUT) or path_matches(output_json, DEFAULT_JSON_OUTPUT):
        raise SystemExit(
            "Refusing to write legacy schema to the default LLM prompt artifacts. "
            "Use --schema-mode model for derived/fahmai_model_mschema.* or pass "
            "custom --output-text/--output-json paths for legacy inspection output."
        )


def resolve_output_paths(args: argparse.Namespace) -> None:
    if args.schema_mode != "core":
        return
    if path_matches(args.output_text, DEFAULT_TEXT_OUTPUT):
        args.output_text = DEFAULT_CORE_TEXT_OUTPUT
    if path_matches(args.output_json, DEFAULT_JSON_OUTPUT):
        args.output_json = DEFAULT_CORE_JSON_OUTPUT


def validate_model_prompt_surface(model: MSchemaModel) -> None:
    expected = expected_model_surface_relations()
    actual = set(model.tables)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    non_views = sorted(name for name, table in model.tables.items() if table.type != "view")
    missing_citation_columns = {
        name: sorted(MODEL_CITATION_COLUMNS - set(table.fields))
        for name, table in model.tables.items()
        if MODEL_CITATION_COLUMNS - set(table.fields)
    }

    errors = []
    if missing:
        errors.append(f"missing model views: {', '.join(missing)}")
    if extra:
        errors.append(f"unexpected prompt relations: {', '.join(extra)}")
    if non_views:
        errors.append(f"non-view prompt relations: {', '.join(non_views)}")
    if missing_citation_columns:
        details = ", ".join(
            f"{name} lacks {', '.join(columns)}"
            for name, columns in sorted(missing_citation_columns.items())
        )
        errors.append(f"missing citation columns: {details}")

    if errors:
        raise ValueError("Invalid FahMai model prompt surface: " + "; ".join(errors))


def model_relation_names_from_prompt(rendered_mschema: str) -> list[str]:
    return MSCHEMA_TABLE_HEADER_RE.findall(rendered_mschema)


def validate_rendered_model_prompt(rendered_mschema: str) -> None:
    expected = expected_model_surface_relations()
    actual = set(model_relation_names_from_prompt(rendered_mschema))
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    count = len(model_relation_names_from_prompt(rendered_mschema))

    errors = []
    if count != len(expected):
        errors.append(f"expected {len(expected)} table headers, found {count}")
    if missing:
        errors.append(f"missing table headers: {', '.join(missing)}")
    if extra:
        errors.append(f"unexpected table headers: {', '.join(extra)}")

    if errors:
        raise ValueError("Invalid rendered FahMai model prompt: " + "; ".join(errors))


def validate_core_schema_surface(model: MSchemaModel) -> None:
    table_count = len(model.tables)
    errors = []
    if table_count not in CORE_TABLE_COUNT_RANGE:
        errors.append(f"expected 31-32 core tables, found {table_count}")
    non_core = sorted(name for name in model.tables if not name.startswith(f"{CORE_SCHEMA}."))
    if non_core:
        errors.append(f"unexpected non-core relations: {', '.join(non_core)}")
    non_tables = sorted(name for name, table in model.tables.items() if table.type != "table")
    if non_tables:
        errors.append(f"non-table core relations: {', '.join(non_tables)}")

    if errors:
        raise ValueError("Invalid FahMai core M-Schema surface: " + "; ".join(errors))


def validate_rendered_core_prompt(rendered_mschema: str) -> None:
    table_headers = model_relation_names_from_prompt(rendered_mschema)
    errors = []
    if len(table_headers) not in CORE_TABLE_COUNT_RANGE:
        errors.append(f"expected 31-32 table headers, found {len(table_headers)}")
    non_core = sorted(name for name in table_headers if not name.startswith(f"{CORE_SCHEMA}."))
    if non_core:
        errors.append(f"unexpected non-core table headers: {', '.join(non_core)}")

    if errors:
        raise ValueError("Invalid rendered FahMai core M-Schema: " + "; ".join(errors))


def object_type_from_relkind(relkind: str) -> str:
    return {
        "r": "table",
        "p": "table",
        "v": "view",
        "m": "materialized_view",
    }.get(relkind, relkind)


def should_include_object(schema: str, name: str, object_type: str, schema_mode: str) -> bool:
    if schema_mode == "model":
        return schema == MODEL_SCHEMA and object_type == "view" and name in MODEL_SURFACE_VIEWS
    if schema_mode == "core":
        return schema == CORE_SCHEMA and object_type == "table"

    if schema == CORE_SCHEMA and object_type == "table":
        return True
    if schema == "fah_sai_lpk_mart" and object_type == "view":
        return name in MODEL_MART_VIEWS
    if schema == "fah_sai_lpk_rag":
        return (
            (name == "v_public_retrievable_chunks" and object_type == "view")
            or (name == "entity_links" and object_type == "table")
        )
    if schema == "fah_sai_lpk_eval" and object_type == "table":
        return name in MODEL_EVAL_TABLES
    return False


def table_sort_key(table_name: str) -> tuple[int, str]:
    schema, _, name = table_name.partition(".")
    return (SCHEMA_ORDER.get(schema, 99), name)


def unescape_sql_string(value: str) -> str:
    return value.replace("''", "'").strip()


def simple_type(field_type: str) -> str:
    return field_type.split("(", 1)[0].upper()


def examples_to_str(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or "\n" in text or "\t" in text or len(text) > 40:
            continue
        if "@" in text:
            continue
        if text not in result:
            result.append(text)
    return result


def should_collect_examples(field_name: str, field_type: str) -> bool:
    if SENSITIVE_COLUMN_RE.search(field_name):
        return False
    if SKIPPED_EXAMPLE_TYPE_RE.search(field_type):
        return False
    normalized_type = field_type.lower()
    if any(token in normalized_type for token in ("date", "time", "bool", "int", "numeric", "double")):
        return True
    return bool(SAFE_TEXT_COLUMN_RE.search(field_name))


def split_sql_items(body: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    depth = 0
    in_single_quote = False
    index = 0

    while index < len(body):
        char = body[index]
        next_char = body[index + 1] if index + 1 < len(body) else ""

        if char == "'" and in_single_quote and next_char == "'":
            current.append(char)
            current.append(next_char)
            index += 2
            continue
        if char == "'":
            in_single_quote = not in_single_quote
            current.append(char)
        elif not in_single_quote and char == "(":
            depth += 1
            current.append(char)
        elif not in_single_quote and char == ")":
            depth = max(depth - 1, 0)
            current.append(char)
        elif not in_single_quote and depth == 0 and char == ",":
            item = "".join(current).strip()
            if item:
                items.append(item)
            current = []
        else:
            current.append(char)
        index += 1

    item = "".join(current).strip()
    if item:
        items.append(item)
    return items


def parse_column_item(item: str) -> tuple[str, FieldInfo, tuple[str, str, str] | None] | None:
    item = re.sub(r"\s+", " ", item.strip())
    first_token = item.split(" ", 1)[0].upper()
    if first_token in {"CONSTRAINT", "PRIMARY", "FOREIGN", "UNIQUE", "CHECK"}:
        return None

    parts = item.split(" ", 1)
    if len(parts) != 2:
        return None
    column_name, remainder = parts
    stop_match = TYPE_STOP_RE.search(remainder)
    type_part = remainder[: stop_match.start()].strip() if stop_match else remainder.strip()
    if not type_part:
        return None

    primary_key = bool(re.search(r"\bPRIMARY\s+KEY\b", remainder, re.IGNORECASE))
    not_null = bool(re.search(r"\bNOT\s+NULL\b", remainder, re.IGNORECASE))
    default_match = re.search(
        r"\bDEFAULT\s+(.+?)(?=\s+(?:NOT\s+NULL|NULL|REFERENCES|CHECK|PRIMARY\s+KEY|UNIQUE)\b|$)",
        remainder,
        re.IGNORECASE,
    )
    default = default_match.group(1).strip() if default_match else None

    fk_match = re.search(
        r"\bREFERENCES\s+([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)\s*\(([^)]+)\)",
        remainder,
        re.IGNORECASE,
    )
    fk_target = None
    if fk_match:
        fk_target = (
            fk_match.group(1),
            fk_match.group(2),
            fk_match.group(3).strip(),
        )

    return (
        column_name,
        FieldInfo(
            type=type_part,
            primary_key=primary_key,
            nullable=not (not_null or primary_key),
            default=default,
        ),
        fk_target,
    )


def parse_primary_key_item(item: str) -> list[str]:
    match = re.match(r"PRIMARY\s+KEY\s*\(([^)]+)\)", item.strip(), re.IGNORECASE)
    if not match:
        return []
    return [column.strip().strip('"') for column in match.group(1).split(",")]


def add_foreign_key(
    model: MSchemaModel,
    source_table: str,
    source_column: str,
    ref_schema: str,
    ref_table: str,
    ref_column: str,
) -> None:
    ref_qualified = qualified(ref_schema, ref_table)
    if source_table not in model.tables or ref_qualified not in model.tables:
        return
    fk = [source_table, source_column, ref_schema, ref_qualified, ref_column]
    if fk not in model.foreign_keys:
        model.foreign_keys.append(fk)


def parse_fallback_tables(model: MSchemaModel, sql_text: str, schema_mode: str) -> None:
    for match in CREATE_TABLE_RE.finditer(sql_text):
        schema, table, body = match.groups()
        table_name = qualified(schema, table)
        if not should_include_object(schema, table, "table", schema_mode):
            continue

        model.tables.setdefault(table_name, TableInfo(type="table"))
        pending_primary_keys: list[str] = []
        pending_foreign_keys: list[tuple[str, str, str, str]] = []

        for item in split_sql_items(body):
            table_pk = parse_primary_key_item(item)
            if table_pk:
                pending_primary_keys.extend(table_pk)
                continue

            parsed = parse_column_item(item)
            if parsed is None:
                continue
            column_name, field_info, fk_target = parsed
            model.tables[table_name].fields[column_name] = field_info
            if fk_target is not None:
                pending_foreign_keys.append((column_name, *fk_target))

        for column_name in pending_primary_keys:
            field_info = model.tables[table_name].fields.get(column_name)
            if field_info is not None:
                field_info.primary_key = True
                field_info.nullable = False

        for source_column, ref_schema, ref_table, ref_column in pending_foreign_keys:
            add_foreign_key(model, table_name, source_column, ref_schema, ref_table, ref_column)


def parse_fallback_comments(model: MSchemaModel, sql_text: str) -> None:
    for match in COMMENT_TABLE_RE.finditer(sql_text):
        schema, table, comment = match.groups()
        table_name = qualified(schema, table)
        if table_name in model.tables:
            model.tables[table_name].comment = unescape_sql_string(comment)

    for match in COMMENT_COLUMN_RE.finditer(sql_text):
        schema, table, column, comment = match.groups()
        table_name = qualified(schema, table)
        field_info = model.tables.get(table_name, TableInfo("table")).fields.get(column)
        if field_info is not None:
            field_info.comment = unescape_sql_string(comment)


def parse_fallback_alter_foreign_keys(model: MSchemaModel, sql_text: str) -> None:
    for match in ALTER_FK_RE.finditer(sql_text):
        schema, table, columns, ref_schema, ref_table, ref_columns = match.groups()
        table_name = qualified(schema, table)
        source_columns = [column.strip().strip('"') for column in columns.split(",")]
        target_columns = [column.strip().strip('"') for column in ref_columns.split(",")]
        for source_column, ref_column in zip(source_columns, target_columns):
            add_foreign_key(model, table_name, source_column, ref_schema, ref_table, ref_column)


def copy_field(source: FieldInfo, *, comment: str | None = None) -> FieldInfo:
    return FieldInfo(
        type=source.type,
        primary_key=False,
        nullable=source.nullable,
        default=None,
        autoincrement=False,
        comment=source.comment if comment is None else comment,
    )


def text_field(comment: str = "", field_type: str = "text") -> FieldInfo:
    return FieldInfo(type=field_type, comment=comment)


def fields_from_specs(specs: list[str | tuple[str, str] | tuple[str, str, str]]) -> dict[str, FieldInfo]:
    fields: dict[str, FieldInfo] = {}
    for spec in specs:
        if isinstance(spec, str):
            fields[spec] = text_field()
            continue
        if len(spec) == 2:
            name, field_type = spec
            comment = ""
        else:
            name, field_type, comment = spec
        fields[name] = text_field(comment=comment, field_type=field_type)
    return fields


def clone_source_fields(model: MSchemaModel, source_table: str) -> dict[str, FieldInfo]:
    source = model.tables.get(source_table)
    if source is None:
        return {}
    return {name: copy_field(field_info) for name, field_info in source.fields.items()}


def add_view(model: MSchemaModel, table_name: str, fields: dict[str, FieldInfo], comment: str) -> None:
    model.tables[table_name] = TableInfo(type="view", comment=comment, fields=fields)


def add_fallback_model_views(model: MSchemaModel) -> None:
    common_event_prefix: list[str | tuple[str, str] | tuple[str, str, str]] = [
        ("source_table", "text", "Official source table for citation and routing."),
        "source_pk",
        ("source_aliases", "text[]"),
        "event_type",
        "event_id",
        ("business_event_date", "date"),
        ("posting_date", "date"),
        ("effective_date", "date"),
        ("as_of_date", "date"),
    ]

    add_view(
        model,
        "fah_sai_lpk_model.sales_order_360",
        fields_from_specs(
            [
                ("source_table", "text", "Official source table for citation; this view cites FACT_SALES rows."),
                "source_pk",
                ("source_aliases", "text[]"),
                ("txn_id", "text", "Sales order grain. One row per txn_id."),
                ("business_event_date", "date"),
                ("posting_date", "date"),
                ("effective_date", "date"),
                ("as_of_date", "date"),
                "branch_code",
                "branch_name_en",
                "branch_type",
                ("is_service_center", "boolean"),
                "customer_id",
                "customer_type",
                "b2b_subtype",
                "customer_payment_terms",
                "loyalty_tier",
                "customer_province",
                "customer_region",
                "account_manager_id",
                "employee_id",
                "sales_employee_position",
                "sales_employee_position_level",
                "sales_employee_dept_code",
                "channel",
                ("basket_total_thb", "numeric(18,2)"),
                ("discount_total_thb", "numeric(18,2)"),
                ("net_total_thb", "numeric(18,2)"),
                ("shipping_charge_thb", "numeric(18,2)"),
                "shipping_method",
                "promo_campaign_id",
                "promo_description_en",
                ("promo_start_timestamp", "timestamptz"),
                ("promo_end_timestamp", "timestamptz"),
                "payment_method",
                "payment_status",
                ("payment_due_date", "date"),
                ("payment_received_date", "date"),
                "settlement_bank_txn_id",
                "settlement_account_id",
                "settlement_transaction_type",
                ("settlement_amount_thb", "numeric(18,2)"),
                "web_log_line_id",
                "schema_version",
                ("is_b2b", "boolean"),
                "retry_idempotency_marker",
            ]
        ),
        TABLE_HINTS["fah_sai_lpk_model.sales_order_360"],
    )

    add_view(
        model,
        "fah_sai_lpk_model.sales_line_360",
        fields_from_specs(
            [
                "source_table",
                "source_pk",
                ("source_aliases", "text[]"),
                ("line_item_id", "text", "Sales line item grain. One row per line_item_id."),
                "txn_id",
                ("business_event_date", "date"),
                ("posting_date", "date"),
                ("effective_date", "date"),
                ("as_of_date", "date"),
                "branch_code",
                "customer_id",
                "employee_id",
                "channel",
                "payment_method",
                "payment_status",
                ("is_b2b", "boolean"),
                ("order_net_total_thb", "numeric(18,2)", "Repeated order-level value. Do not sum this from line-grain rows."),
                "sku_id",
                "brand_family",
                "dept_code",
                "dept_name_en",
                "category",
                "subcategory",
                ("msrp_thb", "numeric(18,2)"),
                "msrp_tier",
                ("is_third_party", "boolean"),
                "vendor_id",
                "vendor_name_en",
                ("launch_date", "date"),
                ("end_of_life_date", "date"),
                ("warranty_months", "integer"),
                ("care_plus_eligible", "boolean"),
                ("quantity", "integer"),
                ("unit_price_thb", "numeric(18,2)"),
                ("line_discount_thb", "numeric(18,2)"),
                ("line_total_thb", "numeric(18,2)", "Use for SKU/product gross revenue from line-level sales."),
                ("is_care_plus", "boolean"),
                "pos_log_line_id",
            ]
        ),
        TABLE_HINTS["fah_sai_lpk_model.sales_line_360"],
    )

    add_view(
        model,
        "fah_sai_lpk_model.finance_event",
        fields_from_specs(
            common_event_prefix
            + [
                "bank_txn_id",
                "account_id",
                "bank",
                "account_role",
                "associated_branch_code",
                "transaction_type",
                "related_entity_table",
                "related_entity_id",
                ("amount_thb", "numeric(18,2)"),
                "amount_direction",
                ("balance_after_thb", "numeric(18,2)"),
                "counterparty",
                "description",
                "customer_id",
                "vendor_id",
                "vendor_name_en",
                "employee_id",
                "employee_position_level",
                "refund_id",
                "return_id",
                "payment_id",
                "payroll_id",
                "vendor_invoice_id",
                ("invoice_period_start", "date"),
                ("invoice_period_end", "date"),
                ("request_date", "date"),
                "approver_employee_id",
                "cosig_employee_id",
                ("attributes", "jsonb"),
            ]
        ),
        TABLE_HINTS["fah_sai_lpk_model.finance_event"],
    )

    add_view(
        model,
        "fah_sai_lpk_model.customer_ops_event",
        fields_from_specs(
            common_event_prefix
            + [
                "customer_id",
                "customer_type",
                "loyalty_tier",
                "employee_id",
                "employee_position_level",
                "branch_code",
                "branch_name_en",
                "txn_id",
                "line_item_id",
                "sku_id",
                "brand_family",
                "category",
                "subcategory",
                "vendor_id",
                "shipping_vendor_id",
                "shipping_vendor_name_en",
                ("amount_thb", "numeric(18,2)"),
                ("points_delta", "integer"),
                ("resulting_balance_points", "integer"),
                "resulting_tier",
                "return_id",
                "refund_id",
                "warranty_claim_id",
                "shipping_id",
                "cs_interaction_id",
                "loyalty_ledger_id",
                "promo_redemption_id",
                "campaign_id",
                "channel",
                "interaction_type",
                "resolution_type",
                "return_reason",
                "claim_reason",
                "routing_destination",
                "shipping_confirmation_status",
                "loyalty_event_type",
                ("discount_applied_thb", "numeric(18,2)"),
                ("attributes", "jsonb"),
            ]
        ),
        TABLE_HINTS["fah_sai_lpk_model.customer_ops_event"],
    )

    add_view(
        model,
        "fah_sai_lpk_model.inventory_event",
        fields_from_specs(
            common_event_prefix
            + [
                ("month_end_date", "date"),
                "sku_id",
                "brand_family",
                "dept_code",
                "dept_name_en",
                "category",
                "subcategory",
                "vendor_id",
                "vendor_name_en",
                "branch_code",
                "branch_name_en",
                "branch_type",
                "movement_type",
                ("quantity", "integer"),
                ("related_txn_id", "text", "Polymorphic id; TXN-* can point to sales and XFER-* is an internal transfer id."),
                ("closing_units", "integer"),
                ("is_stockout", "boolean"),
                ("attributes", "jsonb"),
            ]
        ),
        TABLE_HINTS["fah_sai_lpk_model.inventory_event"],
    )

    add_view(
        model,
        "fah_sai_lpk_model.product_catalog",
        fields_from_specs(
            [
                "source_table",
                "source_pk",
                ("source_aliases", "text[]"),
                "sku_id",
                "brand_family",
                "dept_code",
                "dept_name_en",
                "dept_type",
                "category",
                "subcategory",
                ("msrp_thb", "numeric(18,2)"),
                "msrp_tier",
                ("is_third_party", "boolean"),
                "vendor_id",
                "vendor_name_en",
                "vendor_category",
                "vendor_role",
                ("launch_date", "date"),
                ("end_of_life_date", "date"),
                ("warranty_months", "integer"),
                ("care_plus_eligible", "boolean"),
                ("care_plus_tier_count", "integer"),
                ("min_care_plus_price_thb", "numeric(18,2)"),
                ("max_care_plus_price_thb", "numeric(18,2)"),
                ("max_care_plus_coverage_months", "integer"),
                ("recall_history_count", "integer"),
                "latest_recall_status",
                ("latest_recall_transition_date", "date"),
                ("care_plus_tiers", "jsonb"),
                ("recall_history", "jsonb"),
            ]
        ),
        TABLE_HINTS["fah_sai_lpk_model.product_catalog"],
    )

    add_view(
        model,
        "fah_sai_lpk_model.policy_catalog",
        fields_from_specs(
            [
                "source_table",
                "source_pk",
                ("source_aliases", "text[]"),
                "policy_domain",
                "catalog_row_id",
                "policy_class",
                "policy_variable",
                "scope_filter",
                ("value_numeric", "numeric"),
                "value_text",
                ("effective_date", "date"),
                ("end_date", "date"),
                ("start_timestamp", "timestamptz"),
                ("end_timestamp", "timestamptz"),
                "campaign_id",
                "promo_mechanic_id",
                "vendor_id",
                "vendor_name_en",
                "vendor_contract_version_id",
                ("contract_version_number", "integer"),
                "position_level_code",
                "dept_code",
                ("amount_ceiling_thb", "numeric(18,2)"),
                ("min_co_signers", "integer"),
                "co_signer_min_position_level_code",
                "document_filename",
                "description_th",
                "description_en",
                ("attributes", "jsonb"),
            ]
        ),
        TABLE_HINTS["fah_sai_lpk_model.policy_catalog"],
    )

    add_view(
        model,
        "fah_sai_lpk_model.document_evidence",
        fields_from_specs(
            [
                "evidence_row_id",
                "source_table",
                "source_pk",
                ("source_aliases", "text[]"),
                "retrieval_profile",
                "chunk_id",
                "child_chunk_id",
                "parent_chunk_id",
                "source_document_id",
                "source_path",
                "source_kind",
                "artifact_id",
                "doc_id",
                ("chunk_index", "integer"),
                "chunk_text",
                "parent_text",
                ("token_count", "integer"),
                ("search_tsv", "tsvector"),
                "embedding_model",
                ("has_embedding", "boolean"),
                "document_source_table",
                "document_source_pk",
                ("entity_link_id", "bigint"),
                "entity_type",
                "entity_id",
                "linked_table",
                "linked_column",
                "link_method",
                ("confidence", "numeric(5,4)"),
                ("chunk_metadata", "jsonb"),
                ("parent_metadata", "jsonb"),
                ("source_metadata", "jsonb"),
            ]
        ),
        TABLE_HINTS["fah_sai_lpk_model.document_evidence"],
    )


def add_fallback_legacy_views(model: MSchemaModel) -> None:
    sales_order = clone_source_fields(model, "fah_sai_lpk_core.fact_sales")
    sales_order.update(
        {
            "customer_type": text_field(),
            "loyalty_tier": text_field(),
            "branch_name_en": text_field(),
            "sales_employee_position": text_field(),
            "promo_description_en": text_field(),
            "settlement_transaction_type": text_field(),
            "settlement_amount_thb": text_field(field_type="numeric(18,2)"),
        }
    )
    add_view(model, "fah_sai_lpk_mart.v_sales_order", sales_order, TABLE_HINTS["fah_sai_lpk_mart.v_sales_order"])

    sales_line = clone_source_fields(model, "fah_sai_lpk_core.fact_sales_line_item")
    sales_line.update(
        {
            "branch_code": text_field(),
            "customer_id": text_field(),
            "employee_id": text_field(),
            "channel": text_field(),
            "payment_method": text_field(),
            "brand_family": text_field(),
            "category": text_field(),
            "subcategory": text_field(),
            "vendor_id": text_field(),
            "vendor_name_en": text_field(),
            "dept_name_en": text_field(),
        }
    )
    add_view(model, "fah_sai_lpk_mart.v_sales_line", sales_line, TABLE_HINTS["fah_sai_lpk_mart.v_sales_line"])

    add_view(
        model,
        "fah_sai_lpk_mart.v_sales_deposit_batch_reconciliation",
        {
            "sales_deposit_batch_id": text_field("Virtual batch id reconstructed from sales."),
            "business_event_date": text_field(field_type="date"),
            "branch_code": text_field(),
            "payment_method": text_field(),
            "txn_count": text_field(field_type="integer"),
            "net_total_thb": text_field(field_type="numeric(18,2)"),
            "settlement_bank_txn_id": text_field(),
            "settlement_account_id": text_field(),
            "bank_amount_thb": text_field(field_type="numeric(18,2)"),
            "reconciliation_status": text_field(),
        },
        TABLE_HINTS["fah_sai_lpk_mart.v_sales_deposit_batch_reconciliation"],
    )

    add_view(
        model,
        "fah_sai_lpk_mart.v_bank_reconciliation",
        {
            "bank_txn_id": text_field(),
            "business_event_date": text_field(field_type="date"),
            "posting_date": text_field(field_type="date"),
            "account_id": text_field(),
            "bank": text_field(),
            "account_role": text_field(),
            "associated_branch_code": text_field(),
            "transaction_type": text_field(),
            "related_entity_table": text_field(),
            "related_entity_id": text_field(),
            "amount_thb": text_field(field_type="numeric(18,2)"),
            "balance_after_thb": text_field(field_type="numeric(18,2)"),
            "description": text_field(),
            "deposit_batch_reconciliation_status": text_field(),
            "direct_sales_txn_id": text_field(),
            "payroll_id": text_field(),
            "refund_id": text_field(),
            "ledger_id": text_field(),
            "vendor_payment_id": text_field(),
        },
        TABLE_HINTS["fah_sai_lpk_mart.v_bank_reconciliation"],
    )

    vendor_payment = clone_source_fields(model, "fah_sai_lpk_core.fact_vendor_payment")
    vendor_payment.update(
        {
            "vendor_name_en": text_field(),
            "vendor_category": text_field(),
            "contract_version_number": text_field(field_type="integer"),
            "contract_effective_date": text_field(field_type="date"),
            "contract_end_date": text_field(field_type="date"),
            "signing_employee_position_level": text_field(),
            "cosig_employee_position_level": text_field(),
            "bank_amount_thb": text_field(field_type="numeric(18,2)"),
        }
    )
    add_view(model, "fah_sai_lpk_mart.v_vendor_payment", vendor_payment, TABLE_HINTS["fah_sai_lpk_mart.v_vendor_payment"])

    add_view(
        model,
        "fah_sai_lpk_rag.v_public_retrievable_chunks",
        {
            "chunk_id": text_field(),
            "source_document_id": text_field(),
            "source_path": text_field(),
            "source_kind": text_field(),
            "artifact_id": text_field(),
            "doc_id": text_field(),
            "source_table": text_field(),
            "source_pk": text_field(),
            "chunk_index": text_field(field_type="integer"),
            "chunk_text": text_field(),
            "token_count": text_field(field_type="integer"),
            "search_tsv": text_field(field_type="tsvector"),
            "embedding_model": text_field(),
            "embedding": text_field(field_type="vector(4096)"),
            "chunk_metadata": text_field(field_type="jsonb"),
            "source_metadata": text_field(field_type="jsonb"),
        },
        TABLE_HINTS["fah_sai_lpk_rag.v_public_retrievable_chunks"],
    )


def date_hints_for_table(table_name: str) -> dict[str, str]:
    if table_name in {"fah_sai_lpk_core.fact_vendor_payment", "fah_sai_lpk_mart.v_vendor_payment"}:
        return VENDOR_PAYMENT_DATE_COLUMN_HINTS
    if (
        table_name.startswith("fah_sai_lpk_core.fact_")
        or table_name in MODEL_MART_DATE_HINT_TABLES
        or table_name in MODEL_SURFACE_DATE_HINT_TABLES
    ):
        return FACT_DATE_COLUMN_HINTS
    return {}


def apply_model_hints(model: MSchemaModel) -> None:
    for table_name, comment in TABLE_HINTS.items():
        if table_name in model.tables and not model.tables[table_name].comment:
            model.tables[table_name].comment = comment

    for table_name, table_info in model.tables.items():
        for column_name, comment in date_hints_for_table(table_name).items():
            field_info = table_info.fields.get(column_name)
            if field_info is not None and not field_info.comment:
                field_info.comment = comment

    for key, comment in COLUMN_HINTS.items():
        table_name, _, column_name = key.rpartition(".")
        field_info = model.tables.get(table_name, TableInfo("table")).fields.get(column_name)
        if field_info is not None and not field_info.comment:
            field_info.comment = comment

    for table_name, table_info in model.tables.items():
        if not table_name.startswith(f"{MODEL_SCHEMA}."):
            continue
        for column_name, comment in MODEL_CITATION_COLUMN_HINTS.items():
            field_info = table_info.fields.get(column_name)
            if field_info is not None and not field_info.comment:
                field_info.comment = comment


def build_fallback_model(db_id: str, ddl_files: list[Path], schema_mode: str) -> MSchemaModel:
    model = MSchemaModel(db_id=db_id)
    sql_text = "\n".join(path.read_text(encoding="utf-8") for path in ddl_files if path.exists())
    if schema_mode == "model":
        add_fallback_model_views(model)
    elif schema_mode == "core":
        parse_fallback_tables(model, sql_text, schema_mode)
    else:
        parse_fallback_tables(model, sql_text, schema_mode)
        add_fallback_legacy_views(model)
    parse_fallback_comments(model, sql_text)
    parse_fallback_alter_foreign_keys(model, sql_text)
    apply_model_hints(model)
    sort_model(model)
    if not model.tables:
        raise RuntimeError("No model-facing objects found in the live database")
    return model


def sort_model(model: MSchemaModel) -> None:
    model.tables = dict(sorted(model.tables.items(), key=lambda item: table_sort_key(item[0])))
    model.foreign_keys.sort(key=lambda fk: (table_sort_key(fk[0]), fk[1], table_sort_key(fk[3]), fk[4]))


def fetch_examples(
    conn: Any,
    table_name: str,
    field_name: str,
    field_type: str,
    example_limit: int,
) -> list[str]:
    if example_limit <= 0 or not should_collect_examples(field_name, field_type):
        return []

    schema, _, relation = table_name.partition(".")
    sql = (
        f"SELECT DISTINCT {qident(field_name)}::text AS value "
        f"FROM {qident(schema)}.{qident(relation)} "
        f"WHERE {qident(field_name)} IS NOT NULL "
        f"ORDER BY 1 LIMIT %s"
    )
    with conn.cursor() as cur:
        try:
            cur.execute(sql, (max(example_limit * 4, example_limit),))
            rows = [row[0] for row in cur.fetchall()]
        except Exception:
            conn.rollback()
            return []
    return examples_to_str(rows)[:example_limit]


def schemas_for_mode(schema_mode: str) -> list[str]:
    if schema_mode == "model":
        return [MODEL_SCHEMA]
    if schema_mode == "core":
        return [CORE_SCHEMA]
    return ["fah_sai_lpk_core", "fah_sai_lpk_mart", "fah_sai_lpk_rag", "fah_sai_lpk_eval"]


def build_live_model(db_id: str, database_url: str, example_limit: int, schema_mode: str) -> MSchemaModel:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("Missing dependency: pip install psycopg[binary]") from exc

    model = MSchemaModel(db_id=db_id)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c.oid,
                    n.nspname AS schema_name,
                    c.relname AS relation_name,
                    c.relkind,
                    obj_description(c.oid, 'pg_class') AS relation_comment
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = ANY(%s)
                  AND c.relkind IN ('r', 'p', 'v', 'm')
                ORDER BY n.nspname, c.relname;
                """,
                (schemas_for_mode(schema_mode),),
            )
            relations = cur.fetchall()

        relation_oids: dict[str, int] = {}
        for oid, schema, name, relkind, comment in relations:
            object_type = object_type_from_relkind(relkind)
            if not should_include_object(schema, name, object_type, schema_mode):
                continue
            table_name = qualified(schema, name)
            model.tables[table_name] = TableInfo(type=object_type, comment=comment or "")
            relation_oids[table_name] = oid

        for table_name, oid in relation_oids.items():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT a.attname
                    FROM pg_index i
                    JOIN pg_attribute a
                      ON a.attrelid = i.indrelid
                     AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = %s
                      AND i.indisprimary
                    ORDER BY array_position(i.indkey, a.attnum);
                    """,
                    (oid,),
                )
                primary_keys = {row[0] for row in cur.fetchall()}

                cur.execute(
                    """
                    SELECT
                        a.attname,
                        pg_catalog.format_type(a.atttypid, a.atttypmod) AS field_type,
                        a.attnotnull,
                        pg_get_expr(ad.adbin, ad.adrelid) AS default_expr,
                        col_description(a.attrelid, a.attnum) AS column_comment
                    FROM pg_attribute a
                    LEFT JOIN pg_attrdef ad
                      ON ad.adrelid = a.attrelid
                     AND ad.adnum = a.attnum
                    WHERE a.attrelid = %s
                      AND a.attnum > 0
                      AND NOT a.attisdropped
                    ORDER BY a.attnum;
                    """,
                    (oid,),
                )
                columns = cur.fetchall()

            for column_name, field_type, attnotnull, default, comment in columns:
                model.tables[table_name].fields[column_name] = FieldInfo(
                    type=field_type,
                    primary_key=column_name in primary_keys,
                    nullable=not (attnotnull or column_name in primary_keys),
                    default=default,
                    comment=comment or "",
                    examples=fetch_examples(conn, table_name, column_name, field_type, example_limit),
                )

        included_tables = set(model.tables)
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH fk AS (
                    SELECT
                        con.oid,
                        src_ns.nspname AS src_schema,
                        src_cls.relname AS src_table,
                        ref_ns.nspname AS ref_schema,
                        ref_cls.relname AS ref_table,
                        con.conkey,
                        con.confkey
                    FROM pg_constraint con
                    JOIN pg_class src_cls ON src_cls.oid = con.conrelid
                    JOIN pg_namespace src_ns ON src_ns.oid = src_cls.relnamespace
                    JOIN pg_class ref_cls ON ref_cls.oid = con.confrelid
                    JOIN pg_namespace ref_ns ON ref_ns.oid = ref_cls.relnamespace
                    WHERE con.contype = 'f'
                )
                SELECT
                    fk.src_schema,
                    fk.src_table,
                    src_att.attname AS src_column,
                    fk.ref_schema,
                    fk.ref_table,
                    ref_att.attname AS ref_column
                FROM fk
                JOIN unnest(fk.conkey) WITH ORDINALITY AS src_key(attnum, ord) ON true
                JOIN unnest(fk.confkey) WITH ORDINALITY AS ref_key(attnum, ord)
                  ON ref_key.ord = src_key.ord
                JOIN pg_attribute src_att
                  ON src_att.attrelid = (fk.src_schema || '.' || fk.src_table)::regclass
                 AND src_att.attnum = src_key.attnum
                JOIN pg_attribute ref_att
                  ON ref_att.attrelid = (fk.ref_schema || '.' || fk.ref_table)::regclass
                 AND ref_att.attnum = ref_key.attnum
                ORDER BY fk.src_schema, fk.src_table, fk.oid, src_key.ord;
                """
            )
            foreign_keys = cur.fetchall()

        for src_schema, src_table, src_column, ref_schema, ref_table, ref_column in foreign_keys:
            source_name = qualified(src_schema, src_table)
            ref_name = qualified(ref_schema, ref_table)
            if source_name in included_tables and ref_name in included_tables:
                add_foreign_key(model, source_name, src_column, ref_schema, ref_table, ref_column)

    apply_model_hints(model)
    sort_model(model)
    return model


def dump_model(model: MSchemaModel) -> dict[str, Any]:
    return {
        "db_id": model.db_id,
        "schema": model.schema,
        "tables": {
            table_name: {
                "type": table_info.type,
                "comment": table_info.comment,
                "examples": table_info.examples,
                "fields": {
                    field_name: {
                        "type": field_info.type,
                        "primary_key": field_info.primary_key,
                        "nullable": field_info.nullable,
                        "default": field_info.default,
                        "autoincrement": field_info.autoincrement,
                        "comment": field_info.comment,
                        "examples": field_info.examples,
                    }
                    for field_name, field_info in table_info.fields.items()
                },
            }
            for table_name, table_info in model.tables.items()
        },
        "foreign_keys": model.foreign_keys,
    }


def render_mschema(model: MSchemaModel, *, example_limit: int, show_type_detail: bool) -> str:
    output = [f"〖DB_ID〗 {model.db_id}", "〖Schema〗"]
    fk_by_source_column = {
        (table_name, field_name): (ref_table_name, ref_field_name)
        for table_name, field_name, _ref_schema, ref_table_name, ref_field_name in model.foreign_keys
    }

    for table_name, table_info in model.tables.items():
        if table_info.comment:
            output.append(f"# Table: {table_name}, {table_info.comment}")
        else:
            output.append(f"# Table: {table_name}")

        field_lines = []
        for field_name, field_info in table_info.fields.items():
            field_type = field_info.type if show_type_detail else simple_type(field_info.type)
            field_line = f"({field_name}:{field_type.upper()}"
            if field_info.comment:
                field_line += f", {field_info.comment.strip()}"
            if field_info.primary_key:
                field_line += ", Primary Key"
            fk_target = fk_by_source_column.get((table_name, field_name))
            if fk_target:
                ref_table_name, ref_field_name = fk_target
                field_line += f", Maps to {ref_table_name}({ref_field_name})"
            examples = examples_to_str(field_info.examples)[:example_limit]
            if examples:
                field_line += f", Examples: [{', '.join(examples)}]"
            field_line += ")"
            field_lines.append(field_line)

        output.append("[")
        output.append(",\n".join(field_lines))
        output.append("]")

    output.append("〖Foreign keys〗")
    for table_name, field_name, _ref_schema, ref_table_name, ref_field_name in model.foreign_keys:
        output.append(f"{table_name}.{field_name}={ref_table_name}.{ref_field_name}")

    return "\n".join(output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-id", default="fahmai", help="M-Schema DB_ID value.")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection string. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--fallback-only",
        action="store_true",
        help="Skip live DB introspection and generate metadata from migration files.",
    )
    parser.add_argument(
        "--strict-live",
        action="store_true",
        help="Fail instead of falling back when DATABASE_URL is set but live introspection fails.",
    )
    parser.add_argument(
        "--schema-mode",
        choices=["model", "core", "legacy"],
        default="model",
        help=(
            "model exposes only fah_sai_lpk_model's 8 LLM-facing views; "
            "core exposes official fah_sai_lpk_core tables only; "
            "legacy exposes the older broad core/mart/rag/eval surface."
        ),
    )
    parser.add_argument("--output-text", type=Path, default=DEFAULT_TEXT_OUTPUT)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--example-limit", type=int, default=3)
    parser.add_argument(
        "--show-type-detail",
        action="store_true",
        help="Keep detailed types such as numeric(18,2) in the text output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    resolve_output_paths(args)
    ensure_legacy_outputs_are_explicit(args.schema_mode, args.output_text, args.output_json)
    source = "fallback"

    if args.database_url and not args.fallback_only:
        try:
            model = build_live_model(args.db_id, args.database_url, args.example_limit, args.schema_mode)
            source = "live-db"
        except Exception as exc:
            if args.strict_live:
                raise
            print(f"Live DB introspection failed; using fallback metadata: {exc}", file=sys.stderr)
            model = build_fallback_model(args.db_id, DEFAULT_DDL_FILES, args.schema_mode)
    else:
        model = build_fallback_model(args.db_id, DEFAULT_DDL_FILES, args.schema_mode)

    if args.schema_mode == "model":
        validate_model_prompt_surface(model)
    elif args.schema_mode == "core":
        validate_core_schema_surface(model)

    rendered_mschema = render_mschema(
        model,
        example_limit=args.example_limit,
        show_type_detail=args.show_type_detail,
    )
    if args.schema_mode == "model":
        validate_rendered_model_prompt(rendered_mschema)
    elif args.schema_mode == "core":
        validate_rendered_core_prompt(rendered_mschema)

    args.output_text.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_text.write_text(rendered_mschema, encoding="utf-8")
    args.output_json.write_text(
        json.dumps(dump_model(model), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {args.output_text}")
    print(f"Wrote {args.output_json}")
    print(
        f"Source: {source}; schema mode: {args.schema_mode}; "
        f"tables/views: {len(model.tables)}; foreign keys: {len(model.foreign_keys)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
