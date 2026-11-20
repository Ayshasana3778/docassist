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

## Evaluation on real repositories

`eval/evaluate.py` replays a repo's recent commits. For each commit that changes code, it runs docassist
against the docs as they were *before* the commit and compares the flagged doc files with the doc files the
developer actually edited in that same commit (a proxy for ground truth).

```bash
git clone https://github.com/encode/httpx ../httpx
py eval/evaluate.py ../httpx --docs README.md docs --n 200
```

It prints precision/recall and writes `eval_results.csv` with a blank `human_verdict` column so flagged
sections can be reviewed by hand. Commits where docassist flagged a doc the developer did *not* edit are
the interesting ones: they are either false alarms or docs that really went stale.

Caveat: "doc edited in the same commit" is an imperfect label. Developers sometimes edit docs for unrelated
reasons or forget to edit them, so treat the numbers as an estimate and confirm with manual review.

### Results (last 1,000 commits of each repo, doc-file level)

| Repo | Version | Precision | Recall | False-positive files |
|---|---|---|---|---|
| httpx | v1 (first version) | 0.32 | 0.26 | 81 |
| httpx | v2 (current) | 0.40 | 0.20 | 45 |
| starlette | v1 (first version) | 0.14 | 0.10 | 116 |
| starlette | v2 (current) | 0.16 | 0.06 | 62 |

**What the first evaluation revealed.** On the first 200 httpx commits, v1 flagged 154 doc sections, and
94 of them came from a single commit that only added type hints. Three fixes in v2:

1. Signature comparison ignores type annotations and spacing, so typing-only edits are not "changes".
2. Plain lowercase names such as `request` or `send` must appear as code (backticks or code blocks) in
   the docs; they no longer match ordinary prose.
3. A symbol removed from one file but added elsewhere in the same diff is treated as moved, not deleted.

Result: about 45% fewer false-positive files on both repositories, at the cost of lower recall. httpx was
used to find these problems; starlette was not, and it shows the same direction of change with much lower
absolute precision, so these gains should not be read as a general accuracy claim.

## Design decisions

- **Human in the loop.** The tool proposes; it never silently edits. Removals are flagged, not guessed.
- **Precision over recall.** A noisy bot gets muted, so only sections that actually name a changed
  symbol are flagged.
- **Graceful degradation.** Works with no API key and no network.

## Limitations (be upfront about these in interviews)

- Detection is name-based, so prose that describes behaviour without naming the symbol is missed.
- Symbol extraction is regex-based, not a real parser; it covers Python, JS/TS, Go and Rust patterns.
- Precision is low on real projects (0.16 to 0.40 above). Many doc edits are prose that never names the
  changed function, so recall is low too (0.06 to 0.20).
- The ground truth ("doc edited in the same commit") is a proxy, not a manual label.
- The 6 cases in `tests/` are a regression test, not a benchmark.

## Ideas to make it yours

- Use `tree-sitter` instead of regexes for symbol extraction.
- Embed doc sections and match semantically to catch docs that never name the symbol.
- Open an actual docs PR via the GitHub API instead of a comment.
- Evaluate on real merged PRs from an open-source project and report precision/recall, latency, cost.
