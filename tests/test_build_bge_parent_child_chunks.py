from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "build_bge_parent_child_chunks.py"

sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("build_bge_parent_child_chunks", MODULE_PATH)
assert spec is not None and spec.loader is not None
builder = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = builder
spec.loader.exec_module(builder)


class BgeParentChildChunkBuilderTest(unittest.TestCase):
    def test_small_parent_becomes_single_child_with_parent_metadata(self):
        parent = builder.ParentChunk(
            chunk_id="chunk-parent-1",
            source_document_id="doc-1",
            chunk_index=3,
            chunk_text="short policy text",
            char_start=10,
            char_end=27,
            is_public_safe=True,
            metadata={"section_heading": "Policy"},
            source_path="docs/policy.md",
            source_kind="doc_policy",
        )

        children = builder.split_parent_chunk(
            parent,
            profile="bge_m3_v1",
            child_chars=900,
            child_overlap_chars=120,
        )

        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].chunk_text, "short policy text")
        self.assertEqual(children[0].metadata["parent_chunk_id"], "chunk-parent-1")
        self.assertEqual(children[0].metadata["retrieval_profile"], "bge_m3_v1")
        self.assertEqual(children[0].metadata["splitter_version"], "parent-child-bge-m3-v1")

    def test_large_parent_splits_into_bounded_children(self):
        table = "| sku | value |\n|---|---|\n" + "\n".join(f"| SKU-{i:03d} | {i} |" for i in range(80))
        text = "# Inventory\n\n" + ("Paragraph with context. " * 90) + "\n\n" + table
        parent = builder.ParentChunk(
            chunk_id="chunk-parent-2",
            source_document_id="doc-2",
            chunk_index=0,
            chunk_text=text,
            char_start=0,
            char_end=len(text),
            is_public_safe=True,
            metadata={"section_heading": "Inventory"},
            source_path="docs/inventory.md",
            source_kind="report_md",
        )

        rows, _ = builder.child_rows_for_parent(
            parent,
            profile="bge_m3_v1",
            source_child_index=0,
            child_chars=900,
            child_overlap_chars=120,
        )

        self.assertGreater(len(rows), 1)
        self.assertEqual(len({row[0] for row in rows}), len(rows))
        for row in rows:
            metadata = row[14].obj
            span_length = row[8] - row[7]
            self.assertIsNone(row[6])
            self.assertLessEqual(span_length, 1050)
            self.assertEqual(row[1], "chunk-parent-2")
            self.assertEqual(row[2], "bge_m3_v1")
            self.assertEqual(metadata["parent_chunk_id"], "chunk-parent-2")


if __name__ == "__main__":
    unittest.main()
