from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "generate_fahmai_mschema.py"

spec = importlib.util.spec_from_file_location("generate_fahmai_mschema", MODULE_PATH)
assert spec is not None and spec.loader is not None
mschema = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mschema
spec.loader.exec_module(mschema)


class FahMaiModelMSchemaTest(unittest.TestCase):
    def build_model(self):
        return mschema.build_fallback_model("fahmai", mschema.DEFAULT_DDL_FILES, "model")

    def build_core_model(self):
        return mschema.build_fallback_model("fahmai", mschema.DEFAULT_DDL_FILES, "core")

    def test_model_prompt_exposes_exactly_eight_model_views(self):
        model = self.build_model()

        mschema.validate_model_prompt_surface(model)
        table_names = set(model.tables)

        self.assertEqual(table_names, mschema.expected_model_surface_relations())
        self.assertEqual(len(table_names), 8)
        self.assertTrue(all(name.startswith("fah_sai_lpk_model.") for name in table_names))
        self.assertTrue(all(table.type == "view" for table in model.tables.values()))

    def test_rendered_prompt_table_headers_stay_model_only(self):
        model = self.build_model()
        rendered = mschema.render_mschema(model, example_limit=3, show_type_detail=False)

        mschema.validate_rendered_model_prompt(rendered)
        table_headers = mschema.model_relation_names_from_prompt(rendered)

        self.assertEqual(len(table_headers), 8)
        self.assertTrue(all(header.startswith("fah_sai_lpk_model.") for header in table_headers))
        self.assertFalse(any(header.startswith("fah_sai_lpk_core.") for header in table_headers))
        self.assertFalse(any(header.startswith("fah_sai_lpk_mart.") for header in table_headers))
        self.assertFalse(any(header.startswith("fah_sai_lpk_rag.") for header in table_headers))
        self.assertFalse(any(header.startswith("fah_sai_lpk_eval.") for header in table_headers))

    def test_model_views_keep_citation_and_line_grain_guidance(self):
        model = self.build_model()

        for table_name, table_info in model.tables.items():
            with self.subTest(table=table_name):
                self.assertIn("source_table", table_info.fields)
                self.assertIn("source_pk", table_info.fields)

        line_fields = model.tables["fah_sai_lpk_model.sales_line_360"].fields
        self.assertIn("Do not sum", line_fields["order_net_total_thb"].comment)
        self.assertIn("source table", line_fields["source_table"].comment.lower())

        evidence_fields = model.tables["fah_sai_lpk_model.document_evidence"].fields
        self.assertIn("retrieval_profile", evidence_fields)
        self.assertIn("child_chunk_id", evidence_fields)
        self.assertIn("parent_chunk_id", evidence_fields)
        self.assertIn("parent_text", evidence_fields)
        self.assertIn("BGE-M3", evidence_fields["has_embedding"].comment)

    def test_legacy_mode_cannot_overwrite_default_prompt_artifacts(self):
        with self.assertRaises(SystemExit) as error:
            mschema.ensure_legacy_outputs_are_explicit(
                "legacy",
                mschema.DEFAULT_TEXT_OUTPUT,
                mschema.DEFAULT_JSON_OUTPUT,
            )

        self.assertIn("Refusing to write legacy schema", str(error.exception))

    def test_core_mode_exposes_only_official_core_tables(self):
        model = self.build_core_model()

        mschema.validate_core_schema_surface(model)
        table_names = set(model.tables)

        self.assertIn(len(table_names), mschema.CORE_TABLE_COUNT_RANGE)
        self.assertTrue(all(name.startswith("fah_sai_lpk_core.") for name in table_names))
        self.assertTrue(all(table.type == "table" for table in model.tables.values()))
        self.assertFalse(any(name.startswith("fah_sai_lpk_model.") for name in table_names))
        self.assertFalse(any(name.startswith("fah_sai_lpk_mart.") for name in table_names))
        self.assertFalse(any(name.startswith("fah_sai_lpk_rag.") for name in table_names))
        self.assertFalse(any(name.startswith("fah_sai_lpk_eval.") for name in table_names))

    def test_rendered_core_prompt_keeps_core_table_headers_and_fk_maps(self):
        model = self.build_core_model()
        rendered = mschema.render_mschema(model, example_limit=3, show_type_detail=False)

        mschema.validate_rendered_core_prompt(rendered)
        table_headers = mschema.model_relation_names_from_prompt(rendered)

        self.assertIn(len(table_headers), mschema.CORE_TABLE_COUNT_RANGE)
        self.assertTrue(all(header.startswith("fah_sai_lpk_core.") for header in table_headers))
        self.assertIn("Maps to fah_sai_lpk_core.dim_branch(branch_code)", rendered)


if __name__ == "__main__":
    unittest.main()
