from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.plugins.docling.runner import (
    MANIFEST_NAME,
    build_conversion_plan,
    resolve_html_dir,
    resolve_markdown_dir,
    run_conversion,
)


class DoclingRunnerTests(unittest.TestCase):
    def test_resolve_markdown_dir_uses_addon_sibling_folder(self) -> None:
        source_path = (
            PROJECT_ROOT
            / "app"
            / "systems"
            / "cypher"
            / "addons"
            / "csrd"
            / "source"
            / "Cypher-System-Reference-Document-2025-08-22.docx"
        )
        markdown_dir = resolve_markdown_dir(source_path)
        html_dir = resolve_html_dir(source_path)
        self.assertEqual(markdown_dir.name, "source_markdown")
        self.assertEqual(markdown_dir.parent.name, "csrd")
        self.assertEqual(html_dir.name, "source_html")
        self.assertEqual(html_dir.parent.name, "csrd")

    def test_build_plan_points_to_expected_markdown_file(self) -> None:
        source_path = (
            PROJECT_ROOT
            / "app"
            / "systems"
            / "cypher"
            / "addons"
            / "csrd"
            / "source"
            / "Cypher-System-Reference-Document-2025-08-22.docx"
        )
        plan = build_conversion_plan(source_path, device="cpu", dry_run=True)
        self.assertIn(".venv/bin/docling", plan.command)
        self.assertIn("--to md", plan.command)
        self.assertIn("--to html", plan.command)
        self.assertTrue(plan.expected_markdown_path.endswith("Cypher-System-Reference-Document-2025-08-22.md"))
        self.assertTrue(plan.expected_html_path.endswith("Cypher-System-Reference-Document-2025-08-22.html"))

    def test_dry_run_writes_manifest_without_running_docling(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            addon_root = Path(td) / "app" / "systems" / "cypher" / "addons" / "csrd"
            source_dir = addon_root / "source"
            source_dir.mkdir(parents=True)
            source_path = source_dir / "sample.docx"
            source_path.write_text("placeholder", encoding="utf-8")

            plan = run_conversion(source_path, dry_run=True)

            manifest_path = Path(plan.markdown_output_dir) / MANIFEST_NAME
            self.assertTrue(manifest_path.exists())
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "dry_run")
            self.assertEqual(payload["plan"]["source_path"], str(source_path.resolve()))
            self.assertEqual(payload["artifacts"]["markdown_exists"], False)
            self.assertEqual(payload["artifacts"]["html_exists"], False)

    def test_run_conversion_requires_expected_markdown_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            addon_root = Path(td) / "app" / "systems" / "cypher" / "addons" / "csrd"
            source_dir = addon_root / "source"
            source_dir.mkdir(parents=True)
            source_path = source_dir / "sample.docx"
            source_path.write_text("placeholder", encoding="utf-8")

            previous = os.environ.get("DOCLING_CMD_TEMPLATE")
            os.environ["DOCLING_CMD_TEMPLATE"] = 'python -c "print(\'simulated docling\')"'
            try:
                with self.assertRaises(RuntimeError):
                    run_conversion(source_path, dry_run=False)
            finally:
                if previous is None:
                    os.environ.pop("DOCLING_CMD_TEMPLATE", None)
                else:
                    os.environ["DOCLING_CMD_TEMPLATE"] = previous

            manifest_path = addon_root / "source_markdown" / MANIFEST_NAME
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["artifacts"]["markdown_exists"], False)
            self.assertEqual(payload["artifacts"]["html_exists"], False)

    def test_run_conversion_can_require_html_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            addon_root = Path(td) / "app" / "systems" / "cypher" / "addons" / "csrd"
            source_dir = addon_root / "source"
            markdown_dir = addon_root / "source_markdown"
            source_dir.mkdir(parents=True)
            markdown_dir.mkdir(parents=True)
            source_path = source_dir / "sample.docx"
            source_path.write_text("placeholder", encoding="utf-8")
            markdown_path = (markdown_dir / "sample.md").resolve()

            previous = os.environ.get("DOCLING_CMD_TEMPLATE")
            os.environ["DOCLING_CMD_TEMPLATE"] = f'touch "{markdown_path}"'
            try:
                with self.assertRaises(RuntimeError):
                    run_conversion(source_path, dry_run=False, require_html=True)
            finally:
                if previous is None:
                    os.environ.pop("DOCLING_CMD_TEMPLATE", None)
                else:
                    os.environ["DOCLING_CMD_TEMPLATE"] = previous

            manifest_path = addon_root / "source_markdown" / MANIFEST_NAME
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["artifacts"]["markdown_exists"], True)
            self.assertEqual(payload["artifacts"]["html_exists"], False)

    def test_run_conversion_moves_generated_html_into_source_html(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            addon_root = Path(td) / "app" / "systems" / "cypher" / "addons" / "csrd"
            source_dir = addon_root / "source"
            markdown_dir = addon_root / "source_markdown"
            html_dir = addon_root / "source_html"
            source_dir.mkdir(parents=True)
            markdown_dir.mkdir(parents=True)
            html_dir.mkdir(parents=True)
            source_path = source_dir / "sample.docx"
            source_path.write_text("placeholder", encoding="utf-8")
            markdown_path = (markdown_dir / "sample.md").resolve()
            generated_html_in_markdown_dir = (markdown_dir / "sample.html").resolve()

            previous = os.environ.get("DOCLING_CMD_TEMPLATE")
            os.environ["DOCLING_CMD_TEMPLATE"] = f'touch "{markdown_path}" "{generated_html_in_markdown_dir}"'
            try:
                plan = run_conversion(source_path, dry_run=False, require_html=True)
            finally:
                if previous is None:
                    os.environ.pop("DOCLING_CMD_TEMPLATE", None)
                else:
                    os.environ["DOCLING_CMD_TEMPLATE"] = previous

            self.assertTrue(Path(plan.expected_markdown_path).exists())
            self.assertTrue(Path(plan.expected_html_path).exists())
            self.assertFalse(generated_html_in_markdown_dir.exists())


if __name__ == "__main__":
    unittest.main()
