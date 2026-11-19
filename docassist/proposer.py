"""Turn findings into proposed documentation edits.

Two backends share one interface:
  * heuristic - deterministic, offline; handles renames and flags everything else
  * llm       - asks Claude to rewrite the section (needs ANTHROPIC_API_KEY)
"""

from __future__ import annotations

import difflib
import json
import os
import re
import urllib.request
from dataclasses import dataclass

from .matcher import Finding


@dataclass
class Proposal:
    finding: Finding
    new_lines: list[str]
    note: str  # one-line rationale shown to the reviewer

    @property
    def changed(self) -> bool:
        return self.new_lines != self.finding.section.lines

    def unified_diff(self) -> str:
        sec = self.finding.section
        return "".join(difflib.unified_diff(
            [l + "\n" for l in sec.lines], [l + "\n" for l in self.new_lines],
            fromfile=f"a/{sec.path}", tofile=f"b/{sec.path}", n=2))


def heuristic_propose(f: Finding) -> Proposal:
    lines = list(f.section.lines)
    notes: list[str] = []
    for c in f.changes:
        pat = re.compile(rf"(?<![\w-]){re.escape(c.name)}(?![\w-])")
        if c.kind == "renamed" and c.new_name:
            lines = [pat.sub(c.new_name, l) for l in lines]
            notes.append(f"`{c.name}` renamed to `{c.new_name}`")
        elif c.kind == "removed":
            marker = f"<!-- docassist: `{c.name}` was removed in this change; update or delete this reference -->"
            if marker not in lines:
                lines.append(marker)
            notes.append(f"`{c.name}` removed - needs a human decision")
        elif c.kind == "modified":
            marker = (f"<!-- docassist: signature of `{c.name}` changed to: "
                      f"`{(c.new_sig or '').strip()}` - verify this section -->")
            if marker not in lines:
                lines.append(marker)
            notes.append(f"`{c.name}` signature changed")
    return Proposal(f, lines, "; ".join(notes))


def _call_claude(prompt: str, model: str) -> str:
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({"model": model, "max_tokens": 2000,
                         "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"content-type": "application/json", "anthropic-version": "2023-06-01",
                 "x-api-key": os.environ["ANTHROPIC_API_KEY"]},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)["content"][0]["text"]


def llm_propose(f: Finding, model: str = "claude-sonnet-5-5") -> Proposal:
    changes = "\n".join(
        f"- {c.kind}: {c.name}" + (f" -> {c.new_name}" if c.new_name else "")
        + (f"\n    old: {c.old_sig}" if c.old_sig else "")
        + (f"\n    new: {c.new_sig}" if c.new_sig else "") for c in f.changes)
    prompt = (
        "A code change made this documentation section stale. Rewrite ONLY the section so it "
        "matches the code. Keep the author's tone and structure; change as little as possible. "
        "Do not invent behaviour that the changes below do not show. Return only the revised "
        "markdown, no commentary.\n\n"
        f"Code changes:\n{changes}\n\nSection ({f.section.path}):\n{f.section.text}")
    out = _call_claude(prompt, model).strip("\n")
    return Proposal(f, out.split("\n"), "LLM rewrite - review carefully")


def propose(findings: list[Finding], backend: str = "auto") -> list[Proposal]:
    use_llm = backend == "llm" or (backend == "auto" and os.environ.get("ANTHROPIC_API_KEY"))
    out = []
    for f in findings:
        if use_llm:
            try:
                out.append(llm_propose(f))
                continue
            except Exception as e:  # network/API failure: degrade, don't crash a PR check
                p = heuristic_propose(f)
                p.note += f" (LLM unavailable: {type(e).__name__})"
                out.append(p)
                continue
        out.append(heuristic_propose(f))
    return out
