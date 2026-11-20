"""Decide which documentation sections are affected by which symbol changes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .diff import SymbolChange
from .docs import Section

# Added symbols can't make existing docs wrong, so they carry no weight.
_WEIGHTS = {"renamed": 3, "removed": 3, "modified": 2, "added": 0}


@dataclass
class Finding:
    section: Section
    changes: list[SymbolChange] = field(default_factory=list)
    score: int = 0


def _mentions(text: str, name: str) -> bool:
    # \b treats "-" as a boundary, so guard flags and env vars explicitly.
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text) is not None


_SPAN = re.compile(r"`([^`\n]+)`")


def _distinctive(name: str) -> bool:
    """Names unlikely to be ordinary English: snake_case, CamelCase, UPPER, flags."""
    return "_" in name or name.startswith("-") or not name.islower()


def _code_text(sec: Section) -> str:
    """Only the parts of a section that are code: fenced blocks and `inline spans`."""
    parts, in_fence = [], False
    for line in sec.lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif in_fence:
            parts.append(line)
        else:
            parts.extend(_SPAN.findall(line))
    return "\n".join(parts)


def _references(sec: Section, code: str, name: str) -> bool:
    # Plain lowercase words ("request", "send") must appear as code, not as prose.
    return _mentions(sec.text if _distinctive(name) else code, name)


def find_affected(changes: list[SymbolChange], sections: list[Section]) -> list[Finding]:
    findings: list[Finding] = []
    for sec in sections:
        code = _code_text(sec)
        hit = [c for c in changes if _WEIGHTS[c.kind] > 0 and _references(sec, code, c.name)]
        if hit:
            findings.append(Finding(sec, hit, sum(_WEIGHTS[c.kind] for c in hit)))
    findings.sort(key=lambda f: (-f.score, f.section.path, f.section.start))
    return findings


def undocumented(changes: list[SymbolChange], sections: list[Section]) -> list[SymbolChange]:
    """Newly added public symbols that no doc mentions yet."""
    corpus = "\n".join(s.text for s in sections)
    return [c for c in changes
            if c.kind == "added" and not c.name.startswith("_") and not _mentions(corpus, c.name)]
