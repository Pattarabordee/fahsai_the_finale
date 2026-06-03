# FahMai Enterprise Product Context

FahMai is an enterprise Decision Intelligence Platform for retail operators.
It turns governed operational data, policy documents, reports, chats, logs, and
OCR-safe evidence into auditable business answers.

This repository should be read as a production product workspace, not as a
one-off prototype. Historical challenge material is treated as seed data and
evaluation coverage for a broader company-grade product.

## Product Promise

Business users can ask operational questions and receive answers that separate:

- SQL-backed facts from narrative context.
- Approved evidence from audit-only provenance.
- Final conclusions from assumptions and caveats.
- Reusable decision workflows from one-off analysis.

## Primary Users

- Executive leadership reviewing business performance and risk.
- Operations leaders monitoring branch, inventory, shipping, service, and warranty health.
- Finance teams reconciling bank transactions, refunds, vendor payments, and promotions.
- Compliance and policy reviewers checking approval authority and contract/policy versions.
- Analysts who need traceable, repeatable answers instead of opaque chat output.

## Product Principles

- Numeric and financial answers must be backed by SQL over governed tables or marts.
- Retrieved text provides context and evidence, not standalone truth for exact values.
- Every final answer must carry source citations, SQL or workflow trace, and confidence.
- Untrusted content, OCR helper metadata, and audit-only provenance must not override official sources.
- Rebuild, ingest, embedding, retrieval, and answer generation must be repeatable from source.

## North Star

Trusted decisions per week: the number of reviewed business answers that users
accept and reuse for operational, financial, or compliance decisions.

## Current Product Surface

- Warehouse schemas: `raw`, `core`, `rag`, `mart`, `audit`, `eval`.
- Data load and chunking: `scripts/ingest_fahmai_to_postgres.py` and `scripts/ingest_rag_batches.py`.
- Embedding: `scripts/embed_chunks_openai.py` with Qwen 4096-dimensional embeddings.
- Evaluation and answer trace: `fah_sai_lpk_eval.answer_runs` and `scripts/run_question.py`.
- B200 bootstrap: `scripts/setup_b200_fahmai.sh`.

## Near-Term Product Milestone

Ship Trusted Business Answer Engine v1:

- Governed SQL answers for exact values.
- Hybrid retrieval for narrative evidence.
- Persistent answer review workflow.
- Source authority checks for final citations.
- Product metrics for trust, latency, coverage, and rebuild health.
