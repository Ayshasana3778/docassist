"""Evaluate docassist on the real history of a git repository.

Idea: in a well-maintained project, when a developer changes code AND updates a doc file in the
same commit, that is evidence the doc was affected by the code change. We replay recent commits,
run docassist on each code diff against the docs as they were *before* the commit, and compare
the doc files it flags with the doc files the developer actually edited.

Usage (from the docassist project folder):
    git clone https://github.com/encode/httpx ../httpx
    py eval/evaluate.py ../httpx --docs README.md docs --n 100

Outputs:
    eval_results.csv  - every flagged section, with a blank `human_verdict` column for manual review
    (printed)         - precision / recall and the supporting counts
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docassist.diff import analyze_diff  # noqa: E402
from docassist.docs import split_sections  # noqa: E402
from docassist.matcher import find_affected  # noqa: E402

CODE_EXT = (".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java")


def git(repo: str, *args: str) -> str:
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, check=True)
    return out.stdout.decode("utf-8", errors="replace")


def commit_files(repo: str, sha: str) -> list[str]:
    return [l for l in git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).splitlines() if l]


def under(path: str, targets: list[str]) -> bool:
    p = path.replace("\\", "/")
    return any(p == t or p.startswith(t.rstrip("/") + "/") for t in (x.replace("\\", "/") for x in targets))


def docs_at(repo: str, rev: str, targets: list[str]):
    sections = []
    for path in git(repo, "ls-tree", "-r", "--name-only", rev).splitlines():
        if path.endswith(".md") and under(path, targets):
            sections.extend(split_sections(path, git(repo, "show", f"{rev}:{path}")))
    return sections


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", help="path to a local git clone")
    ap.add_argument("--docs", nargs="+", default=["README.md", "docs"], help="markdown files/dirs inside the repo")
    ap.add_argument("--n", type=int, default=100, help="how many recent non-merge commits to replay")
    ap.add_argument("--out", default="eval_results.csv")
    args = ap.parse_args()

    shas = git(args.repo, "rev-list", "--no-merges", f"-n{args.n}", "HEAD").split()

    used = 0            # commits that touched code
    with_doc_edit = 0   # ...and also edited a tracked doc file (ground truth exists)
    tp = fp = fn = 0    # file-level counts on commits with ground truth
    flagged_no_edit = 0 # commits where we flagged docs but the dev edited none (maybe a true catch)
    rows = []

    for sha in shas:
        try:
            parent = git(args.repo, "rev-parse", f"{sha}^").strip()
        except subprocess.CalledProcessError:
            continue  # root commit
        files = commit_files(args.repo, sha)
        if not any(f.endswith(CODE_EXT) for f in files):
            continue
        subject = git(args.repo, "log", "-1", "--format=%s", sha).strip()
        diff = git(args.repo, "diff", "--no-color", "-U0", parent, sha, "--", *[f for f in files if f.endswith(CODE_EXT)])
        sections = docs_at(args.repo, parent, args.docs)
        findings = find_affected(analyze_diff(diff), sections)
        flagged = {f.section.path for f in findings}
        truth = {f for f in files if f.endswith(".md") and under(f, args.docs)}
        used += 1

        if truth:
            with_doc_edit += 1
            tp += len(flagged & truth)
            fp += len(flagged - truth)
            fn += len(truth - flagged)
        elif flagged:
            flagged_no_edit += 1

        for f in findings:
            rows.append({
                "commit": sha[:10], "subject": subject[:80], "doc_file": f.section.path,
                "section": f.section.heading,
                "symbols": "; ".join(f"{c.kind}:{c.name}" for c in f.changes),
                "dev_edited_this_doc": "yes" if f.section.path in truth else ("no-docs-edited" if not truth else "no"),
                "human_verdict": "",  # fill in: y = doc really was stale, n = false alarm
            })

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["commit", "subject", "doc_file", "section", "symbols",
                                           "dev_edited_this_doc", "human_verdict"])
        w.writeheader()
        w.writerows(rows)

    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    print(f"Commits replayed:                    {len(shas)}")
    print(f"  touching code:                     {used}")
    print(f"  ...that also edited a tracked doc: {with_doc_edit}   <- ground-truth commits")
    print(f"Doc-file level on ground-truth commits: TP={tp} FP={fp} FN={fn}")
    print(f"  precision = {precision:.2f}   recall = {recall:.2f}")
    print(f"Commits flagged but dev edited no doc: {flagged_no_edit}   <- review these in the CSV; each may be a real catch")
    print(f"Wrote {len(rows)} flagged sections to {args.out}")
    if with_doc_edit < 20:
        print("NOTE: fewer than 20 ground-truth commits - raise --n or pick a repo with more doc edits before quoting numbers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
