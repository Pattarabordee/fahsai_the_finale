# Trusted Business Answer Engine Capability

## Capability

FahMai users can ask business questions and receive a governed answer that is
backed by SQL, cited evidence, source-authority rules, and a persisted review
record. The capability serves leaders, finance, operations, compliance, and
analysts who need repeatable decisions rather than opaque chat responses.

## Constraints

- Numeric, financial, inventory, and count answers should default to SQL over the compact `fah_sai_lpk_model.*` surfaces.
- `fah_sai_lpk_core.*`, approved `fah_sai_lpk_mart.*`, and `fah_sai_lpk_rag.*` remain source-of-truth/debug surfaces for verification, citations, and retrieval internals.
- Final citations must be public-safe or explicitly approved; audit-only provenance remains review-only.
- Every answer run must be persisted to `fah_sai_lpk_eval.answer_runs` unless explicitly run in dry/no-persist mode.
- The system must tolerate pgvector environments where 4096-dimensional HNSW indexes cannot be created.

## Implementation Contract

- Actors: executive user, operations analyst, finance reviewer, compliance reviewer, platform operator.
- Surfaces: CLI runners now, later API/UI endpoints that call the same answer engine.
- Inputs: natural-language question, optional entity filters, optional date window, run label, retrieval settings.
- Outputs: answer text, structured answer JSON, SQL used, source paths/tables, confidence, status, runtime, model name.
- States: `draft`, `needs_review`, `answered`, `blocked`, `rejected`.
- Data ownership:
  - `fah_sai_lpk_core.*` owns official table facts.
  - `fah_sai_lpk_mart.*` owns approved business views.
  - `fah_sai_lpk_rag.*` owns public-safe retrieval evidence.
  - `fah_sai_lpk_model.*` owns the compact LLM-facing query surface.
  - `fah_sai_lpk_audit.*` owns provenance and operational trace.
  - `fah_sai_lpk_eval.*` owns answer lifecycle and review state.

## Non-Goals

- Do not build a generic chatbot over all files.
- Do not embed every table row as text.
- Do not let document instructions override source authority.
- Do not collapse all domains into one giant reconciliation view.

## Open Questions

- Which human roles can approve an answer from `needs_review` to `answered`?
- What confidence threshold is acceptable for automated surfacing versus analyst review?
- Which OCR artifact families should be promoted from audit-only to approved evidence?
- Which UI surface is first: analyst workbench, executive dashboard, or API?

## Handoff

Ready for implementation as a capability slice. The next engineering step is to
upgrade `scripts/run_question.py` into a governed answer orchestrator and add a
hybrid retrieval migration.
