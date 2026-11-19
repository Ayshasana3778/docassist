# docassist

Finds documentation that a code change has made stale, and proposes reviewable fixes.

```
code diff -> symbol changes -> affected doc sections -> proposed edits -> human review -> apply / PR comment
```

Zero dependencies (Python 3.10+ standard library only).

## Try it

```bash
python -m docassist analyze --diff demo/change.diff --docs demo/docs
python -m docassist analyze --git origin/main...HEAD --docs README.md docs --review   # y/N per edit
python -m unittest discover -s tests -v
```

## How it works

1. **diff.py** parses a unified diff and extracts symbols (functions, classes, constants, CLI flags,
   env vars). Removed/added symbols with near-identical signatures are paired as **renames**; same
   name with a different signature is **modified**; the rest are **removed** or **added**.
2. **docs.py** splits markdown into heading-delimited sections (fenced code is respected).
3. **matcher.py** flags a section only if it mentions a renamed/removed/modified symbol (word-boundary
   match, so `fetch` does not hit `fetch_user`). Added symbols are reported separately as
   "possibly undocumented".
4. **proposer.py** has two backends:
   - *heuristic* (offline, deterministic): applies renames, leaves an HTML comment marker for removals
     and signature changes so a human decides.
   - *llm*: set `ANTHROPIC_API_KEY` and it asks Claude to rewrite only the stale section. On any API
     failure it falls back to the heuristic backend.
5. **cli.py** renders a markdown report, optionally applies edits (`--apply`, or `--review` to confirm
   each one), and can fail CI with `--fail-on-stale`.

## GitHub Action

`action.yml` runs on pull requests, writes the report to the job summary and posts it as a sticky PR
comment. Add `anthropic-api-key` to enable LLM rewrites.

## Design decisions

- **Human in the loop.** The tool proposes; it never silently edits. Removals are flagged, not guessed.
- **Precision over recall.** A noisy bot gets muted, so only sections that actually name a changed
  symbol are flagged.
- **Graceful degradation.** Works with no API key and no network.

## Limitations (be upfront about these in interviews)

- Detection is name-based, so prose that describes behaviour without naming the symbol is missed.
- Symbol extraction is regex-based, not a real parser; it covers Python, JS/TS, Go and Rust patterns.
- The bundled eval has only 6 labeled cases (100% precision/recall). It is a regression test, not a
  benchmark. To make a real claim, label 50+ diffs from a real repo and report the numbers.

## Ideas to make it yours

- Use `tree-sitter` instead of regexes for symbol extraction.
- Embed doc sections and match semantically to catch docs that never name the symbol.
- Open an actual docs PR via the GitHub API instead of a comment.
- Evaluate on real merged PRs from an open-source project and report precision/recall, latency, cost.
