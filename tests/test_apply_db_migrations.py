from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "apply_db_migrations.py"

spec = importlib.util.spec_from_file_location("apply_db_migrations", MODULE_PATH)
assert spec is not None and spec.loader is not None
migrations = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = migrations
spec.loader.exec_module(migrations)


class ApplyDbMigrationsPresetTest(unittest.TestCase):
    def test_schema_preset_includes_bge_compact_and_mschema_artifacts(self):
        selected = migrations.parse_migration_selection("schema")

        self.assertEqual(
            selected,
            ["001", "002", "007", "008", "009", "010", "012", "013", "014"],
        )
        self.assertIn("012", selected)
        self.assertIn("013", selected)
        self.assertIn("014", selected)

    def test_full_preset_keeps_bge_hnsw_after_compact_schema(self):
        selected = migrations.parse_migration_selection("full")

        self.assertEqual(
            selected,
            [
                "001",
                "002",
                "007",
                "003",
                "004",
                "005",
                "008",
                "009",
                "010",
                "012",
                "013",
                "014",
                "011",
            ],
        )
        self.assertGreater(selected.index("011"), selected.index("012"))
        self.assertGreater(selected.index("011"), selected.index("014"))

    def test_full_dry_run_exposes_all_planned_migration_paths(self):
        result = migrations.run_migration_batch(
            database_url=None,
            selection="full",
            dry_run=True,
            verify=False,
            verbose=False,
        )

        planned_paths = [entry["path"] for entry in result["migrations"]]
        self.assertEqual(result["selected_migrations"], migrations.DEFAULT_FULL_MIGRATIONS)
        self.assertIn("db/012_rag_bge_m3_compact_child_spans.sql", planned_paths)
        self.assertIn("db/013_model_schema_prompt_hygiene.sql", planned_paths)
        self.assertIn("db/014_mschema_artifacts.sql", planned_paths)
        self.assertEqual(planned_paths[-1], "db/011_rag_bge_m3_hnsw.sql")


if __name__ == "__main__":
    unittest.main()
