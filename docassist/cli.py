"""Command line entry point: python -m docassist analyze --diff change.diff --docs docs README.md"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from .diff import analyze_diff
from .docs import load_docs
from .matcher import find_affected, undocumented
from .proposer import Proposal, propose


def render_report(changes, findings, proposals, missing) -> str:
    out = ["## docassist report", ""]
    out.append(f"Detected **{len(changes)}** symbol change(s); "
               f"**{len(findings)}** documentation section(s) may be stale.")
    out.append("")
    if not findings:
        out.append("No existing documentation references the changed symbols.")
    for p in proposals:
        sec = p.finding.section
        out.append(f"### `{sec.path}` - {sec.heading}")
        out.append(f"_Why:_ {p.note}")
        if p.changed:
            out.append("")
            out.append("```diff")
            out.append(p.unified_diff().rstrip())
            out.append("```")
        out.append("")
    if missing:
        out.append("### Possibly undocumented additions")
        for c in missing:
            out.append(f"- `{c.name}` in `{c.path}`")
        out.append("")
    return "\n".join(out)


def apply_proposals(proposals: list[Proposal], interactive: bool) -> int:
    """Write accepted proposals to disk. Applies bottom-up so line indices stay valid."""
    by_file: dict[str, list[Proposal]] = defaultdict(list)
    for p in proposals:
        if not p.changed:
            continue
        if interactive:
            print(p.unified_diff())
            if input(f"Apply this change ({p.note})? [y/N] ").strip().lower() != "y":
                continue
        by_file[p.finding.section.path].append(p)
    applied = 0
    for path, props in by_file.items():
        lines = Path(path).read_text(encoding="utf-8").split("\n")
        for p in sorted(props, key=lambda x: x.finding.section.start, reverse=True):
            s = p.finding.section
            lines[s.start:s.end] = p.new_lines
            applied += 1
        Path(path).write_text("\n".join(lines), encoding="utf-8")
    return applied


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="docassist")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="find docs made stale by a diff")
    a.add_argument("--diff", help="unified diff file (default: stdin, or `git diff` with --git)")
    a.add_argument("--git", metavar="RANGE", help="use `git diff RANGE`, e.g. origin/main...HEAD")
    a.add_argument("--docs", nargs="+", default=["README.md", "docs"], help="markdown files/dirs")
    a.add_argument("--backend", choices=["auto", "heuristic", "llm"], default="auto")
    a.add_argument("--out", help="write the markdown report here instead of stdout")
    a.add_argument("--html", metavar="FILE", help="also write a styled HTML report, e.g. report.html")
    a.add_argument("--open", action="store_true", help="open the HTML report in your browser (use with --html)")
    a.add_argument("--apply", action="store_true", help="write proposed edits to the docs")
    a.add_argument("--review", action="store_true", help="like --apply but ask y/N for each change")
    a.add_argument("--fail-on-stale", action="store_true", help="exit 1 if stale docs are found (CI gate)")
    s = sub.add_parser("serve", help="run the local web app (paste a diff, review and apply fixes in the browser)")
    s.add_argument("--docs", nargs="+", default=["README.md", "docs"], help="markdown files/dirs")
    s.add_argument("--diff", help="optional diff file to pre-fill the page")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-open", action="store_true", help="do not open the browser automatically")
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        from .server import serve
        return serve(args.docs, args.diff, args.port, not args.no_open)

    if args.git:
        diff_text = subprocess.run(["git", "diff", args.git], capture_output=True, text=True, check=True).stdout
    elif args.diff:
        diff_text = Path(args.diff).read_text(encoding="utf-8")
    else:
        diff_text = sys.stdin.read()

    changes = analyze_diff(diff_text)
    sections = load_docs(args.docs)
    findings = find_affected(changes, sections)
    proposals = propose(findings, args.backend)
    report = render_report(changes, findings, proposals, undocumented(changes, sections))

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    else:
        print(report)
    if args.html:
        from .htmlreport import render_html
        Path(args.html).write_text(
            render_html(changes, findings, proposals, undocumented(changes, sections)), encoding="utf-8")
        print(f"HTML report written to {args.html}", file=sys.stderr)
        if args.open:
            import webbrowser
            webbrowser.open(Path(args.html).resolve().as_uri())
    if args.apply or args.review:
        n = apply_proposals(proposals, interactive=args.review)
        print(f"\nApplied {n} change(s).", file=sys.stderr)
    return 1 if (args.fail_on_stale and findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
