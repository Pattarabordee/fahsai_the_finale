# FahMai L3 — Renders + Provenance

Standalone bundle of all rendered artifacts (PNG/PDF) from the FahMai L3 release-full
simulation, paired with their JSON provenance metadata.

Generated: 2026-05-31
Render types included: bank_statement, e7_banner, receipt, t2_doc, t3_doc, vendor_invoice, warranty_form
Total files: 6128

## Layout

    render_provenance.jsonl       Master mapping — one line per rendered page.
                                   Schema:
                                     {
                                       "artifact_id": "BS-KBANK-OPER-2567-01",
                                       "output_path": "private/renders/bank_statement/2024-01/BS-KBANK-OPER-2567-01_transactions_p1.png",
                                       "release_lane": "grader_only",
                                       "renderer_template_id": "bank_statement_kbank",
                                       "source_fact_table": "FACT_BANK_TRANSACTION",
                                       "source_row_ids": ["BT-202401-...", ...],
                                       "template_version": "v1",
                                       "visible_fields": ["account_id", "amount_thb", ...]
                                     }

    per_artifact/<type>/<artifact_id>.json
                                   Derived view, one JSON per artifact_id, collapsing
                                   header + transaction pages into a single sidecar.
                                   Schema:
                                     {
                                       "artifact_id": "BS-KBANK-OPER-2567-01",
                                       "renderer_template_id": "bank_statement_kbank",
                                       "template_version": "v1",
                                       "pages": [
                                         {
                                           "output_path": "...",
                                           "page_kind": "header" | "transactions_p1" | ...,
                                           "source_fact_table": "DIM_BANK_ACCOUNT" | "FACT_BANK_TRANSACTION",
                                           "source_row_ids": [...],
                                           "visible_fields": [...]
                                         },
                                         ...
                                       ],
                                       "all_source_row_ids": [...]   (union across pages)
                                     }

    renders/<type>/YYYY-MM/*.png|pdf
                                   The rendered artifacts themselves.

## Render types and their source tables

| Type             | Source table                  | Notes |
|------------------|-------------------------------|-------|
| bank_statement   | DIM_BANK_ACCOUNT (header) +   | Per-month statement per account; |
|                  | FACT_BANK_TRANSACTION (txn pages) | header + N transaction pages. |
| receipt          | FACT_SALES + FACT_SALES_LINE_ITEM | One PNG per B2C sale |
| vendor_invoice   | FACT_VENDOR_PAYMENT           | One PNG per invoice payment |
| warranty_form    | FACT_WARRANTY_CLAIM           | One PNG per warranty claim |
| e7_banner        | DIM_PROMO_CAMPAIGN            | Campaign banners |
| t2_doc           | T2_DOC_INVENTORY              | Lease/training/audit PDFs (weasyprint) |
| t3_doc           | FACT_VENDOR_PAYMENT (V-014    | Bank corp-resolution PNGs |
|                  | corp resolution path)         | |

## Provenance fields explained

- **`output_path`** — relative path under the bundle's `private/renders/...`. The
  same artifact ALSO exists at `public/renders/...` (the public bundle promotes
  renders via hardlink/copy). In THIS zip both views point at `renders/...`.
- **`release_lane`** — always `"grader_only"` in the source provenance, but the
  PNG itself is in the public lane. The provenance record is grader-only because
  the `source_row_ids` mapping itself would let a model trivially solve any
  visual-grounding question by joining back to FACT/DIM tables.
- **`source_row_ids`** — the exact primary-key values from `source_fact_table`
  that are displayed on this specific PNG/PDF. For bank-statement transaction
  pages, this is the list of `bank_txn_id`s on that one page (each statement
  has 1 header page + N transaction pages, paginated by row count).
- **`visible_fields`** — which columns of `source_fact_table` are exposed on
  the render. Other columns from the same row are NOT shown.
- **`template_version`** — bumped when the render template materially changes
  (currently all `v1`).

## Counts (this bundle)

| Render type | Provenance pages |
|---|---|
| `bank_statement` | 2,714 pages |
| `e7_banner` | 4 pages |
| `receipt` | 563 pages |
| `t2_doc` | 81 pages |
| `t3_doc` | 11 pages |
| `vendor_invoice` | 792 pages |
| `warranty_form` | 1,963 pages |
