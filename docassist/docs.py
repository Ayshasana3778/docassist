"""Index markdown documentation into heading-delimited sections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


@dataclass
class Section:
    path: str
    heading: str
    start: int  # 0-based line index of the heading (or 0 for preamble)
    end: int    # exclusive
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def split_sections(path: str, text: str) -> list[Section]:
    lines = text.split("\n")
    sections: list[Section] = []
    start, heading = 0, "(top)"
    in_fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else _HEADING.match(line)
        if m:
            if i > start:
                sections.append(Section(path, heading, start, i, lines[start:i]))
            start, heading = i, m.group(2)
    sections.append(Section(path, heading, start, len(lines), lines[start:]))
    return sections


def load_docs(targets: list[str]) -> list[Section]:
    """Load sections from files or directories (markdown only)."""
    files: list[Path] = []
    for t in targets:
        p = Path(t)
        if p.is_dir():
            files.extend(sorted(p.rglob("*.md")))
        elif p.is_file():
            files.append(p)
    sections: list[Section] = []
    for f in files:
        sections.extend(split_sections(str(f), f.read_text(encoding="utf-8")))
    return sections
