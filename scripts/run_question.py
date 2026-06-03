#!/usr/bin/env python
"""Run FahMai questions through retrieval and persist eval evidence.

Prerequisites:
  pip install psycopg[binary]

For local Qwen3-Embedding-8B via Hugging Face Text Embeddings Inference:
  docker run --gpus all -p 8080:80 -v hf_cache:/data --pull always ghcr.io/huggingface/text-embeddings-inference:1.7.2 --model-id Qwen/Qwen3-Embedding-8B --dtype float16

Usage:
  $env:DATABASE_URL = "postgresql://fahmai_app:<password>@0.tcp.ap.ngrok.io:26551/fahmai?sslmode=disable"
  python scripts/run_question.py --question-id FAHMAI-Q-L1-001 --run-label rag-smoke
  python scripts/run_question.py --question-text "Which source mentions refund approval policy?" --run-label ad-hoc
  python scripts/run_question.py --all --limit 100 --run-label eval-v1

This script is intentionally retrieval-first. It does not invent a final answer;
it stores sources, candidate SQL templates, and retrieval evidence in
fah_sai_lpk_eval.answer_runs for review or downstream answer generation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from decimal import Decimal
from typing import Any, Iterable, Sequence
from urllib import error, request

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError as exc:  # pragma: no cover - dependency guard
    psycopg = None
    dict_row = None
    Jsonb = None
    PSYCOPG_IMPORT_ERROR = exc
else:
    PSYCOPG_IMPORT_ERROR = None


DEFAULT_MODEL = "Qwen/Qwen3-Embedding-8B"
DEFAULT_DIMENSION = 4096
DEFAULT_TEI_ENDPOINT = "http://localhost:8080/embed"
DEFAULT_MATCH_COUNT = 8
DEFAULT_CANDIDATE_COUNT = 80
DEFAULT_TEMPLATE_LIMIT = 8
DEFAULT_EXCERPT_CHARS = 900
QWEN_QUERY_TASK = (
    "Given a Thai/English FahMai business question, retrieve relevant public-safe "
    "evidence passages that answer the question or route it to the right governed source."
)

TAG_TEMPLATE_FAMILIES = {
    "bank": {"bank", "finance", "reconciliation", "retrieval"},
    "doc": {"retrieval", "policy"},
    "injection": {"retrieval", "policy"},
    "ocr": {"retrieval"},
    "policy": {"policy", "retrieval"},
    "sales": {"sales", "returns", "ar", "retrieval"},
    "structured": {"sales", "bank", "policy", "returns", "vendor", "ar", "retrieval"},
}


def require_psycopg() -> None:
    if psycopg is None:
        raise SystemExit("Missing dependency: pip install psycopg[binary]") from PSYCOPG_IMPORT_ERROR


def vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(value):.9g}" for value in values) + "]"


def stable_ad_hoc_question_id(question_text: str) -> str:
    digest = hashlib.sha1(question_text.encode("utf-8")).hexdigest()[:24]
    return f"ADHOC-{digest}"


def normalize_embedding_response(payload: Any) -> list[list[float]]:
    if isinstance(payload, list):
        if not payload:
            return []
        if isinstance(payload[0], dict) and "embedding" in payload[0]:
            return [item["embedding"] for item in payload]
        return payload
    if isinstance(payload, dict) and "data" in payload:
        return [item["embedding"] for item in payload["data"]]
    raise ValueError("Embedding endpoint returned an unsupported response shape")


def query_text_for_embedding(question_text: str, model: str) -> tuple[str, bool]:
    if "Qwen3-Embedding" not in model:
        return question_text, False
    return f"Instruct: {QWEN_QUERY_TASK}\nQuery: {question_text}", True


def embed_with_tei(endpoint: str, text: str, timeout_seconds: int, max_retries: int) -> list[float]:
    body = json.dumps({"inputs": [text]}).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    for attempt in range(max_retries + 1):
        try:
            req = request.Request(endpoint, data=body, headers=headers, method="POST")
            with request.urlopen(req, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            embeddings = normalize_embedding_response(payload)
            if len(embeddings) != 1:
                raise ValueError(f"Expected one query embedding, got {len(embeddings)}")
            return embeddings[0]
        except (TimeoutError, error.URLError, error.HTTPError) as exc:
            if attempt >= max_retries:
                raise RuntimeError(f"TEI query embedding failed after {attempt + 1} attempts: {exc}") from exc
            time.sleep(min(2**attempt, 8))

    raise RuntimeError("TEI query embedding failed")


def embed_with_openai_compatible(
    model: str,
    text: str,
    base_url: str | None,
    api_key: str | None,
    max_retries: int,
) -> list[float]:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise SystemExit("Missing dependency for --provider openai-compatible: pip install openai") from exc

    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=max_retries)
    response = client.embeddings.create(model=model, input=[text])
    return response.data[0].embedding


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def truncate_text(text: str | None, max_chars: int) -> str | None:
    if text is None or len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def load_question(conn, question_id: str) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT question_id, question_text, difficulty, question_family, metadata
            FROM fah_sai_lpk_eval.questions
            WHERE question_id = %s
            """,
            (question_id,),
        )
        row = cur.fetchone()
    if not row:
        raise SystemExit(f"Question {question_id!r} not found in fah_sai_lpk_eval.questions")
    return dict(row)


def load_all_questions(conn, limit: int) -> list[dict[str, Any]]:
    sql = """
        SELECT question_id, question_text, difficulty, question_family, metadata
        FROM fah_sai_lpk_eval.questions
        WHERE is_public = true
        ORDER BY question_id
    """
    params: tuple[Any, ...] = ()
    if limit > 0:
        sql += " LIMIT %s"
        params = (limit,)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def upsert_ad_hoc_question(conn, question_text: str) -> dict[str, Any]:
    question_id = stable_ad_hoc_question_id(question_text)
    question_hash = hashlib.sha256(question_text.encode("utf-8")).hexdigest()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO fah_sai_lpk_eval.questions
                (question_id, question_text, difficulty, question_family, source_file, question_hash, metadata)
            VALUES (%s, %s, 'ad_hoc', 'ad_hoc', 'run_question.py', %s, %s)
            ON CONFLICT (question_id) DO UPDATE SET
                question_text = EXCLUDED.question_text,
                question_hash = EXCLUDED.question_hash,
                updated_at = now()
            RETURNING question_id, question_text, difficulty, question_family, metadata
            """,
            (
                question_id,
                question_text,
                question_hash,
                Jsonb({"created_by": "scripts/run_question.py"}),
            ),
        )
        return dict(cur.fetchone())


def load_question_tags(conn, question_id: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT tag
            FROM fah_sai_lpk_eval.question_tags
            WHERE question_id = %s
            ORDER BY confidence DESC, tag
            """,
            (question_id,),
        )
        return [row[0] for row in cur.fetchall()]


def candidate_template_families(tags: Iterable[str]) -> set[str]:
    families: set[str] = set()
    for tag in tags:
        families.update(TAG_TEMPLATE_FAMILIES.get(tag, set()))
    return families


def load_candidate_templates(conn, tags: list[str], limit: int) -> list[dict[str, Any]]:
    families = candidate_template_families(tags)
    with conn.cursor(row_factory=dict_row) as cur:
        if families:
            cur.execute(
                """
                SELECT template_name, template_family, description, parameters, source_authority
                FROM fah_sai_lpk_eval.sql_templates
                WHERE template_family = ANY(%s)
                   OR template_family = 'retrieval'
                ORDER BY template_family, template_name
                LIMIT %s
                """,
                (sorted(families), limit),
            )
        else:
            cur.execute(
                """
                SELECT template_name, template_family, description, parameters, source_authority
                FROM fah_sai_lpk_eval.sql_templates
                ORDER BY template_family, template_name
                LIMIT %s
                """,
                (limit,),
            )
        return [json_safe(dict(row)) for row in cur.fetchall()]


def fetch_vector_results(conn, embedding: Sequence[float], match_count: int, candidate_count: int, excerpt_chars: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT *
            FROM fah_sai_lpk_rag.match_public_chunks(%s::vector, %s, %s)
            """,
            (vector_literal(embedding), match_count, candidate_count),
        )
        rows = [json_safe(dict(row)) for row in cur.fetchall()]
    for row in rows:
        row["chunk_text"] = truncate_text(row.get("chunk_text"), excerpt_chars)
    return rows


def fetch_text_results(conn, question_text: str, match_count: int, excerpt_chars: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT *
            FROM fah_sai_lpk_rag.search_public_chunks_text(%s, %s)
            """,
            (question_text, match_count),
        )
        rows = [json_safe(dict(row)) for row in cur.fetchall()]
    for row in rows:
        row["chunk_text"] = truncate_text(row.get("chunk_text"), excerpt_chars)
    return rows


def unique_ordered(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def build_answer_text(
    question: dict[str, Any],
    vector_results: list[dict[str, Any]],
    text_results: list[dict[str, Any]],
    templates: list[dict[str, Any]],
) -> str:
    lines = [
        "Retrieval-only eval run. Review sources before writing a final answer.",
        "",
        f"Question: {question['question_text']}",
        "",
        "Top vector sources:",
    ]
    if vector_results:
        for result in vector_results[:5]:
            score = result.get("similarity")
            score_text = f" similarity={score:.4f}" if isinstance(score, (float, int)) else ""
            lines.append(f"- {result.get('source_path')}#{result.get('chunk_index')}{score_text}")
    else:
        lines.append("- none")

    lines.extend(["", "Top text sources:"])
    if text_results:
        for result in text_results[:5]:
            score = result.get("rank_score")
            score_text = f" rank={score:.4f}" if isinstance(score, (float, int)) else ""
            lines.append(f"- {result.get('source_path')}#{result.get('chunk_index')}{score_text}")
    else:
        lines.append("- none")

    if templates:
        lines.extend(["", "Candidate SQL templates:"])
        for template in templates[:5]:
            lines.append(f"- {template['template_name']} ({template['template_family']})")

    return "\n".join(lines)


def save_answer_run(
    conn,
    question: dict[str, Any],
    run_label: str,
    status: str,
    answer_text: str,
    answer_json: dict[str, Any],
    template_names: list[str],
    runtime_ms: int,
    model_name: str,
) -> str:
    vector_results = answer_json.get("vector_results", [])
    text_results = answer_json.get("text_results", [])
    source_paths = unique_ordered(
        [row.get("source_path") for row in vector_results]
        + [row.get("source_path") for row in text_results]
    )
    source_tables = unique_ordered(
        [
            (row.get("source_metadata") or {}).get("source_table")
            for row in vector_results
            if isinstance(row.get("source_metadata"), dict)
        ]
    )
    sql_used = "\n".join(
        [
            "SELECT * FROM fah_sai_lpk_rag.match_public_chunks(:query_embedding::vector(4096), :match_count, :candidate_count);",
            "SELECT * FROM fah_sai_lpk_rag.search_public_chunks_text(:query_text, :match_count);",
        ]
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO fah_sai_lpk_eval.answer_runs
                (question_id, run_label, status, answer_text, answer_json, sql_used,
                 source_paths, source_tables, template_names, runtime_ms, model_name, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING answer_run_id
            """,
            (
                question["question_id"],
                run_label,
                status,
                answer_text,
                Jsonb(answer_json),
                sql_used,
                source_paths,
                source_tables,
                template_names,
                runtime_ms,
                model_name,
                Jsonb({"runner": "scripts/run_question.py", "retrieval_only": True}),
            ),
        )
        return str(cur.fetchone()[0])


def run_one_question(conn, args: argparse.Namespace, question: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    tags = load_question_tags(conn, question["question_id"])
    templates = load_candidate_templates(conn, tags, args.template_limit)

    embedding: list[float] | None = None
    vector_results: list[dict[str, Any]] = []
    query_instruction_applied = False
    if not args.skip_vector:
        embedding_input, query_instruction_applied = query_text_for_embedding(question["question_text"], args.model)
        if args.provider == "tei":
            embedding = embed_with_tei(args.endpoint, embedding_input, args.timeout_seconds, args.max_retries)
        else:
            embedding = embed_with_openai_compatible(
                args.model,
                embedding_input,
                args.base_url,
                args.api_key,
                args.max_retries,
            )
        if len(embedding) != DEFAULT_DIMENSION:
            raise ValueError(f"Query embedding dimension {len(embedding)} != {DEFAULT_DIMENSION}")
        vector_results = fetch_vector_results(
            conn,
            embedding,
            args.match_count,
            args.candidate_count,
            args.excerpt_chars,
        )

    text_results = fetch_text_results(conn, question["question_text"], args.text_match_count, args.excerpt_chars)
    runtime_ms = int((time.perf_counter() - started) * 1000)
    answer_json = {
        "question": json_safe(question),
        "question_tags": tags,
        "embedding": {
            "provider": None if args.skip_vector else args.provider,
            "model": None if args.skip_vector else args.model,
            "dimension": None if args.skip_vector else DEFAULT_DIMENSION,
            "query_instruction": "fahmai_public_rag_v1" if query_instruction_applied else None,
        },
        "vector_results": vector_results,
        "text_results": text_results,
        "candidate_templates": templates,
        "runtime_ms": runtime_ms,
    }
    answer_text = build_answer_text(question, vector_results, text_results, templates)
    template_names = [template["template_name"] for template in templates]
    answer_run_id = None
    if not args.no_persist:
        answer_run_id = save_answer_run(
            conn,
            question,
            args.run_label,
            args.status,
            answer_text,
            answer_json,
            template_names,
            runtime_ms,
            args.model if not args.skip_vector else "text-only",
        )

    return {
        "answer_run_id": answer_run_id,
        "question_id": question["question_id"],
        "vector_result_count": len(vector_results),
        "text_result_count": len(text_results),
        "template_count": len(templates),
        "runtime_ms": runtime_ms,
        "persisted": not args.no_persist,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    question_group = parser.add_mutually_exclusive_group(required=True)
    question_group.add_argument("--question-id", help="Load one question from fah_sai_lpk_eval.questions")
    question_group.add_argument("--question-text", help="Run an ad-hoc question and upsert it into fah_sai_lpk_eval.questions")
    question_group.add_argument("--all", action="store_true", help="Run all public fah_sai_lpk_eval.questions, optionally capped by --limit")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="Postgres connection URL")
    parser.add_argument("--run-label", default="retrieval-v1")
    parser.add_argument(
        "--status",
        default="needs_review",
        choices=["draft", "answered", "needs_review", "blocked", "rejected"],
        help="Status to store in fah_sai_lpk_eval.answer_runs. Retrieval-only runs should stay needs_review.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit used with --all. 0 means no limit.")
    parser.add_argument("--match-count", type=int, default=DEFAULT_MATCH_COUNT)
    parser.add_argument("--text-match-count", type=int, default=DEFAULT_MATCH_COUNT)
    parser.add_argument("--candidate-count", type=int, default=DEFAULT_CANDIDATE_COUNT)
    parser.add_argument("--template-limit", type=int, default=DEFAULT_TEMPLATE_LIMIT)
    parser.add_argument("--excerpt-chars", type=int, default=DEFAULT_EXCERPT_CHARS)
    parser.add_argument("--skip-vector", action="store_true", help="Run text retrieval only, without calling an embedding backend")
    parser.add_argument("--no-persist", action="store_true", help="Print results without inserting fah_sai_lpk_eval.answer_runs")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary")
    parser.add_argument("--model", default=os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL))
    parser.add_argument(
        "--provider",
        choices=["tei", "openai-compatible"],
        default=os.getenv("EMBEDDING_PROVIDER", "tei"),
    )
    parser.add_argument("--endpoint", default=os.getenv("EMBEDDING_ENDPOINT", DEFAULT_TEI_ENDPOINT))
    parser.add_argument("--base-url", default=os.getenv("EMBEDDING_BASE_URL"))
    parser.add_argument("--api-key", default=os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY"))
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("Set DATABASE_URL or pass --database-url")
    for field in ("match_count", "text_match_count", "candidate_count", "template_limit"):
        if getattr(args, field) < 1:
            raise SystemExit(f"--{field.replace('_', '-')} must be >= 1")
    if args.limit < 0:
        raise SystemExit("--limit must be >= 0")
    if args.excerpt_chars < 120:
        raise SystemExit("--excerpt-chars must be >= 120")
    if args.timeout_seconds < 1:
        raise SystemExit("--timeout-seconds must be >= 1")
    if args.max_retries < 0:
        raise SystemExit("--max-retries must be >= 0")
    return args


def main() -> int:
    args = parse_args()
    require_psycopg()
    summaries: list[dict[str, Any]] = []
    with psycopg.connect(args.database_url) as conn:
        if args.all:
            questions = load_all_questions(conn, args.limit)
        elif args.question_id:
            questions = [load_question(conn, args.question_id)]
        elif args.no_persist:
            questions = [
                {
                    "question_id": stable_ad_hoc_question_id(args.question_text),
                    "question_text": args.question_text,
                    "difficulty": "ad_hoc",
                    "question_family": "ad_hoc",
                    "metadata": {"source": "no_persist"},
                }
            ]
        else:
            questions = [upsert_ad_hoc_question(conn, args.question_text)]

        if not questions:
            raise SystemExit("No questions found")

        for question in questions:
            try:
                summary = run_one_question(conn, args, question)
                if not args.no_persist:
                    conn.commit()
            except Exception:
                conn.rollback()
                raise
            summaries.append(summary)
            if not args.json:
                run_id = summary["answer_run_id"] or "(not persisted)"
                print(
                    f"{summary['question_id']}: answer_run_id={run_id} "
                    f"vector={summary['vector_result_count']} text={summary['text_result_count']} "
                    f"templates={summary['template_count']} runtime_ms={summary['runtime_ms']}"
                )

    if args.json:
        print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
