# FahMai Enterprise Roadmap

## Product Thesis

Retail enterprises do not need another dashboard or generic document chatbot.
They need a trusted answer layer that joins operational truth, policy context,
and document evidence while leaving an audit trail.

## Milestone 1: Trusted Answer Foundation

- Product framing and capability contract live in `PRODUCT.md` and `docs/product/`.
- B200 bootstrap starts Postgres, Qwen embedding service, migrations, and smoke checks.
- Answer runs persist source, SQL, status, confidence, runtime, and review metadata.
- 4096-dimensional embeddings remain supported even when HNSW is unavailable.

## Milestone 2: Governed Retrieval

- Add `fah_sai_lpk_rag.hybrid_search_public_chunks` for vector, full-text, and trigram fusion.
- Return ranked evidence with source authority and public-safety metadata.
- Add duplicate suppression and parent-context support for long conversations/reports.
- Track retrieval coverage and failed/no-source questions.

## Milestone 3: SQL-Backed Answer Orchestration

- Classify questions into structured, document, hybrid, policy, reconciliation, and safety categories.
- Route exact-answer questions through SQL templates or approved marts.
- Keep retrieved text as explanation/corroboration for exact numeric answers.
- Persist generated SQL, result summaries, and evidence decisions.

## Milestone 4: Enterprise Workflows

- Executive Copilot: trusted KPI answers and narrative explanations.
- Ops Command Center: branch, inventory, shipping, warranty, and customer-service health.
- Finance Reconciliation Assistant: deposits, refunds, vendor payments, and promotion leakage.
- Policy Reviewer: approval limits, contract versions, and exception detection.
- Evidence Workbench: answer review, source inspection, correction, and approval.

## Milestone 5: Production Governance

- Add role-based answer review and approval states.
- Add product metrics and quality gates to deployment checks.
- Add source-authority regression tests for prompt-injection-like content.
- Add operational monitoring for ingest, embeddings, retrieval latency, and answer quality.

## First 30-Day Build Order

1. Implement hybrid retrieval v1.
2. Add answer quality checks for `fah_sai_lpk_eval.answer_runs`.
3. Add 5 high-impact semantic marts from source comparison findings.
4. Upgrade `run_question.py` to choose SQL templates before final answer text.
5. Create a minimal reviewer workflow around `needs_review` and `answered`.
