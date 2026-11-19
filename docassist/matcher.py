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


def find_affected(changes: list[SymbolChange], sections: list[Section]) -> list[Finding]:
    findings: list[Finding] = []
    for sec in sections:
        text = sec.text
        hit = [c for c in changes if _WEIGHTS[c.kind] > 0 and _mentions(text, c.name)]
        if hit:
            findings.append(Finding(sec, hit, sum(_WEIGHTS[c.kind] for c in hit)))
    findings.sort(key=lambda f: (-f.score, f.section.path, f.section.start))
    return findings


def undocumented(changes: list[SymbolChange], sections: list[Section]) -> list[SymbolChange]:
    """Newly added public symbols that no doc mentions yet."""
    corpus = "\n".join(s.text for s in sections)
    return [c for c in changes
            if c.kind == "added" and not c.name.startswith("_") and not _mentions(corpus, c.name)]
