import os
import shutil
import tempfile
import unittest
from pathlib import Path

from docassist.server import App

ROOT = Path(__file__).resolve().parent.parent
DIFF = (ROOT / "demo" / "change.diff").read_text()


class ServerLogicTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)  # keep tests offline and deterministic
        self.tmp = tempfile.mkdtemp()
        self.doc = Path(self.tmp) / "usage.md"
        shutil.copy(ROOT / "demo" / "docs" / "usage.md", self.doc)
        self.app = App()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_analyze_reports_three_sections_and_marks_rename_safe(self):
        r = self.app.analyze(DIFF, [str(self.doc)])
        self.assertEqual(r["summary"]["flagged"], 3)
        safe = [i for i in r["items"] if i["safe"]]
        self.assertEqual([i["heading"] for i in safe], ["Quick start"])

    def test_apply_only_selected_fix(self):
        r = self.app.analyze(DIFF, [str(self.doc)])
        quick = next(i["id"] for i in r["items"] if i["heading"] == "Quick start")
        out = self.app.apply([quick])
        self.assertEqual(out["applied"], 1)
        text = self.doc.read_text()
        self.assertIn("create_client(api_key", text)
        self.assertNotIn("was removed in this change", text)  # unselected fix untouched

    def test_apply_refuses_when_file_changed_since_analysis(self):
        r = self.app.analyze(DIFF, [str(self.doc)])
        ids = [i["id"] for i in r["items"]]
        self.doc.write_text(self.doc.read_text().replace("Quick start", "Quick start!!"))
        out = self.app.apply(ids)
        self.assertTrue(out["conflicts"])

    def test_unknown_ids_are_ignored(self):
        self.app.analyze(DIFF, [str(self.doc)])
        self.assertEqual(self.app.apply(["999"])["applied"], 0)

    def test_empty_diff_and_missing_docs_give_clear_errors(self):
        with self.assertRaises(ValueError):
            self.app.analyze("   ", [str(self.doc)])
        with self.assertRaises(ValueError):
            self.app.analyze(DIFF, ["no/such/folder"])


if __name__ == "__main__":
    unittest.main()
