import tempfile
import unittest
from pathlib import Path

from docassist.cli import apply_proposals
from docassist.diff import analyze_diff
from docassist.docs import load_docs, split_sections
from docassist.matcher import find_affected, undocumented
from docassist.proposer import heuristic_propose

ROOT = Path(__file__).resolve().parent.parent
DIFF = (ROOT / "demo" / "change.diff").read_text()
DOCS = str(ROOT / "demo" / "docs")


def kinds(changes):
    return {(c.kind, c.name) for c in changes}


class DiffTests(unittest.TestCase):
    def test_classifies_rename_modify_remove_add(self):
        got = kinds(analyze_diff(DIFF))
        self.assertIn(("renamed", "make_client"), got)
        self.assertIn(("modified", "retry_call"), got)
        self.assertIn(("removed", "MAX_RETRIES"), got)
        self.assertIn(("added", "export_report"), got)

    def test_rename_records_new_name(self):
        c = next(c for c in analyze_diff(DIFF) if c.name == "make_client")
        self.assertEqual(c.new_name, "create_client")

    def test_cli_flag_and_env_var_detected(self):
        diff = ("--- a/cli.py\n+++ b/cli.py\n@@ -1 +1 @@\n"
                "-p.add_argument('--timeout')\n+p.add_argument('--deadline')\n")
        self.assertIn(("renamed", "--timeout"), kinds(analyze_diff(diff)))


class DocTests(unittest.TestCase):
    def test_sections_ignore_headings_in_code_fences(self):
        text = "# A\n```\n# not a heading\n```\n## B\nbody"
        self.assertEqual([s.heading for s in split_sections("x.md", text)], ["A", "B"])


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.changes = analyze_diff(DIFF)
        self.sections = load_docs([DOCS])

    def test_only_sections_mentioning_changed_symbols_flagged(self):
        flagged = {f.section.heading for f in find_affected(self.changes, self.sections)}
        self.assertEqual(flagged, {"Quick start", "Configuration", "Retries"})

    def test_unrelated_section_not_flagged(self):
        flagged = {f.section.heading for f in find_affected(self.changes, self.sections)}
        self.assertNotIn("Changelog", flagged)

    def test_substring_does_not_false_match(self):
        diff = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-def fetch(x):\n+def get(x):\n"
        secs = split_sections("d.md", "# T\nCalls `fetch_user` and `prefetch`.")
        self.assertEqual(find_affected(analyze_diff(diff), secs), [])

    def test_undocumented_addition_reported(self):
        names = [c.name for c in undocumented(self.changes, self.sections)]
        self.assertEqual(names, ["export_report"])


class ProposeTests(unittest.TestCase):
    def test_rename_rewrites_reference(self):
        f = next(f for f in find_affected(analyze_diff(DIFF), load_docs([DOCS]))
                 if f.section.heading == "Quick start")
        p = heuristic_propose(f)
        self.assertIn("create_client(api_key", p.unified_diff())
        self.assertNotIn("make_client", "\n".join(p.new_lines))

    def test_apply_writes_file(self):
        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "u.md"
            doc.write_text((ROOT / "demo/docs/usage.md").read_text())
            f = find_affected(analyze_diff(DIFF), load_docs([str(doc)]))
            n = apply_proposals([heuristic_propose(x) for x in f], interactive=False)
            self.assertEqual(n, 3)
            self.assertIn("create_client", doc.read_text())


class EvalTests(unittest.TestCase):
    """Labeled mini-benchmark: report precision/recall so the README can quote real numbers."""

    CASES = [  # (diff, doc, expected_flagged)
        ("--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-def load(p):\n+def read(p):\n",
         "# A\nUse `load` here.", True),
        ("--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-def load(p):\n+def read(p):\n",
         "# A\nUse `loader` here.", False),
        ("--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-RATE_LIMIT = 5\n+RATE_CAP = 5\n",
         "# A\nSet RATE_LIMIT to tune it.", True),
        ("--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-def go(a):\n+def go(a, b):\n",
         "# A\nCall `go` to start.", True),
        ("--- a/m.py\n+++ b/m.py\n@@ -0,0 +1 @@\n+def brand_new():\n",
         "# A\nCall `go` to start.", False),
        ("--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-def go(a):\n+def go(a, b):\n",
         "# A\nNothing relevant.", False),
    ]

    def test_precision_recall(self):
        tp = fp = fn = 0
        for diff, doc, expected in self.CASES:
            got = bool(find_affected(analyze_diff(diff), split_sections("d.md", doc)))
            tp += got and expected
            fp += got and not expected
            fn += (not got) and expected
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        print(f"\n[eval] cases={len(self.CASES)} precision={precision:.2f} recall={recall:.2f}")
        self.assertEqual((precision, recall), (1.0, 1.0))


if __name__ == "__main__":
    unittest.main()
