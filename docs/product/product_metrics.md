# FahMai Product Metrics

## North Star Metric

Trusted decisions per week: accepted, reviewed answers that users reuse for an
operational, financial, compliance, or executive decision.

## Quality Metrics

- Answer acceptance rate: reviewed answers marked `answered` divided by reviewed runs.
- SQL-backed answer rate: exact/numeric answers that include runnable SQL.
- Citation coverage: final answers with at least one approved source.
- Bad source rate: final answers citing audit-only or unsafe sources.
- Retrieval no-hit rate: questions with no useful retrieved evidence.
- Correction rate: answers changed by reviewers before approval.

## Reliability Metrics

- Fresh rebuild success: B200 bootstrap completes from clean checkout.
- Ingest completion time: CSV plus public document chunking duration.
- Embedding completion time: missing public chunks embedded per hour.
- Bad embedding dimensions: embeddings where `vector_dims(embedding) <> 4096`.
- Materialized view freshness: time since last successful refresh.

## Performance Metrics

- Median answer runtime.
- P95 answer runtime.
- Median retrieval runtime.
- P95 SQL template runtime.
- Failed query rate.

## Governance Metrics

- Answers in `needs_review` older than SLA.
- Percentage of answers with explicit source-authority classification.
- Prompt-injection safety pass rate.
- OCR evidence promotion/rejection counts.

## Suggested SQL Checks

```sql
SELECT status, count(*)
FROM fah_sai_lpk_eval.answer_runs
GROUP BY status
ORDER BY status;

SELECT count(*) AS bad_embedding_dims
FROM fah_sai_lpk_rag.chunk_embeddings
WHERE vector_dims(embedding) <> 4096;

SELECT count(*) AS answers_without_sources
FROM fah_sai_lpk_eval.answer_runs
WHERE cardinality(source_paths) = 0;

SELECT avg(runtime_ms)::numeric(18,2) AS avg_runtime_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY runtime_ms) AS p95_runtime_ms
FROM fah_sai_lpk_eval.answer_runs
WHERE runtime_ms IS NOT NULL;
```

## Readiness Command

Use the repo script to collect these metrics as JSON:

```bash
python scripts/evaluate_product_readiness.py --pretty
```
