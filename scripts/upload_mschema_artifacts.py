#!/usr/bin/env python
"""Upload generated FahMai M-Schema artifacts to the remote metadata schema."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit("Missing dependency: pip install psycopg[binary]") from exc


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEXT_PATH = ROOT / "derived" / "fahmai_model_mschema.txt"
DEFAULT_JSON_PATH = ROOT / "derived" / "fahmai_model_mschema.json"
TABLE_HEADER_RE = re.compile(r"^# Table:\s+", re.MULTILINE)
BACKEND_SCHEMA_RE = re.compile(r"fah_sai_lpk_(?:core|rag|mart|eval)\.")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def relation_count(mschema_text: str) -> int:
    return len(TABLE_HEADER_RE.findall(mschema_text))


def validate_artifacts(mschema_text: str, mschema_json: str) -> dict[str, Any]:
    count = relation_count(mschema_text)
    if count != 8:
        raise SystemExit(f"Expected 8 model-facing relations in M-Schema text, found {count}")
    leaked = BACKEND_SCHEMA_RE.findall(mschema_text)
    if leaked:
        raise SystemExit("M-Schema text leaks backend schema names; regenerate prompt hygiene first")
    parsed_json = json.loads(mschema_json)
    json_count = len(parsed_json.get("tables", {}))
    if json_count != 8:
        raise SystemExit(f"Expected 8 model-facing relations in M-Schema JSON, found {json_count}")
    return {"text_relation_count": count, "json_relation_count": json_count}


def upload_artifacts(args: argparse.Namespace) -> dict[str, Any]:
    mschema_text = args.text_path.read_text(encoding="utf-8")
    mschema_json = args.json_path.read_text(encoding="utf-8")
    validation = validate_artifacts(mschema_text, mschema_json)
    text_hash = sha256_text(mschema_text)
    json_hash = sha256_text(mschema_json)

    rows = [
        (
            "fahmai_model_mschema",
            "model",
            "text",
            mschema_text,
            text_hash,
            validation["text_relation_count"],
            args.retrieval_profile,
            Jsonb(
                {
                    "source_path": args.text_path.relative_to(ROOT).as_posix(),
                    "prompt_surface": "fah_sai_lpk_model_8_views",
                }
            ),
        ),
        (
            "fahmai_model_mschema",
            "model",
            "json",
            mschema_json,
            json_hash,
            validation["json_relation_count"],
            args.retrieval_profile,
            Jsonb(
                {
                    "source_path": args.json_path.relative_to(ROOT).as_posix(),
                    "prompt_surface": "fah_sai_lpk_model_8_views",
                }
            ),
        ),
    ]

    with psycopg.connect(args.database_url) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO fah_sai_lpk_meta.mschema_artifacts
                    (artifact_name, schema_mode, artifact_format, content,
                     content_sha256, relation_count, retrieval_profile, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (artifact_name, schema_mode, artifact_format) DO UPDATE SET
                    content = EXCLUDED.content,
                    content_sha256 = EXCLUDED.content_sha256,
                    relation_count = EXCLUDED.relation_count,
                    retrieval_profile = EXCLUDED.retrieval_profile,
                    generated_at = now(),
                    metadata = EXCLUDED.metadata
                """,
                rows,
            )
        conn.commit()

    return {
        "uploaded": True,
        "artifact_name": "fahmai_model_mschema",
        "formats": ["text", "json"],
        "relation_count": 8,
        "retrieval_profile": args.retrieval_profile,
        "text_sha256": text_hash,
        "json_sha256": json_hash,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--text-path", type=Path, default=DEFAULT_TEXT_PATH)
    parser.add_argument("--json-path", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--retrieval-profile", default=os.getenv("RETRIEVAL_PROFILE", "bge_m3_v1"))
    parser.add_argument("--json", action="store_true", help="Print machine-readable upload summary")
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("Set DATABASE_URL or pass --database-url")
    if not args.text_path.exists():
        raise SystemExit(f"M-Schema text file not found: {args.text_path}")
    if not args.json_path.exists():
        raise SystemExit(f"M-Schema JSON file not found: {args.json_path}")
    return args


def main() -> int:
    args = parse_args()
    result = upload_artifacts(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"uploaded {result['artifact_name']} formats={','.join(result['formats'])} "
            f"relations={result['relation_count']} profile={result['retrieval_profile']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
