"""Parse a unified diff and extract the symbols that changed."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

# One pattern per language family; each captures the symbol name in group "name".
_DEF_PATTERNS = [
    re.compile(r"^\s*(?:async\s+)?def\s+(?P<name>[A-Za-z_]\w*)\s*\("),          # python
    re.compile(r"^\s*class\s+(?P<name>[A-Za-z_]\w*)"),                           # python/js/ts/java
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)"),  # js/ts
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*="),  # js/ts
    re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(?P<name>[A-Za-z_]\w*)\s*\("),    # go
    re.compile(r"^\s*(?:pub\s+)?fn\s+(?P<name>[A-Za-z_]\w*)"),                   # rust
    re.compile(r"^(?P<name>[A-Z][A-Z0-9_]{2,})\s*="),                            # CONSTANTS
]
_FLAG = re.compile(r"""["'](?P<name>--[a-z][a-z0-9-]+)["']""")                   # CLI flags
_ENV = re.compile(r"""["'](?P<name>[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)["']""")       # ENV_VARS in strings


@dataclass
class Symbol:
    name: str
    signature: str  # the full source line, stripped


@dataclass
class FileChange:
    path: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


@dataclass
class SymbolChange:
    kind: str  # "renamed" | "removed" | "modified" | "added"
    name: str
    new_name: str | None = None
    old_sig: str | None = None
    new_sig: str | None = None
    path: str = ""


def parse_diff(text: str) -> list[FileChange]:
    """Split a unified diff into per-file lists of added/removed lines."""
    changes: list[FileChange] = []
    current: FileChange | None = None
    for line in text.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            if path == "/dev/null":
                continue
            current = FileChange(path=path)
            changes.append(current)
        elif line.startswith("--- "):
            continue  # old-side header; the "+++" line names the file
        elif current is None:
            continue
        elif line.startswith("+") and not line.startswith("+++"):
            current.added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            current.removed.append(line[1:])
    return changes


def extract_symbols(lines: list[str]) -> list[Symbol]:
    out: list[Symbol] = []
    for line in lines:
        for pat in _DEF_PATTERNS:
            m = pat.match(line)
            if m:
                out.append(Symbol(m.group("name"), line.strip()))
                break
        for pat in (_FLAG, _ENV):
            for m in pat.finditer(line):
                out.append(Symbol(m.group("name"), line.strip()))
    return out


_DUNDER = re.compile(r"^__\w+__$")
_BRACKETS = re.compile(r"\[[^\[\]]*\]")
_RETURN_ANN = re.compile(r"\s*->\s*[^:]*:\s*$")
_PARAM_ANN = re.compile(r":\s*[\w\.\|\"' ]+?(?=\s*[,=)]|\s*$)")


def normalize_sig(sig: str) -> str:
    """Drop type annotations and spacing so a pure typing/formatting edit is not a signature change."""
    s = sig.strip()
    if not re.match(r"^(async\s+)?def\s", s):
        return re.sub(r"\s+", " ", s)
    s = _RETURN_ANN.sub(":", s)
    while _BRACKETS.search(s):
        s = _BRACKETS.sub("", s)
    s = _PARAM_ANN.sub("", s)
    s = re.sub(r"\s+", "", s).replace(",)", ")")
    return s


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def diff_symbols(change: FileChange) -> list[SymbolChange]:
    """Classify each symbol in one file's diff as renamed / removed / modified / added."""
    old = extract_symbols(change.removed)
    new = extract_symbols(change.added)
    old_by_name = {s.name: s for s in old}
    new_by_name = {s.name: s for s in new}
    results: list[SymbolChange] = []

    for name, o in old_by_name.items():
        if _DUNDER.match(name):
            continue  # __init__, __repr__ ...: docs almost never mean these by name
        if name in new_by_name:
            n = new_by_name[name]
            if normalize_sig(o.signature) != normalize_sig(n.signature):
                results.append(SymbolChange("modified", name, old_sig=o.signature,
                                            new_sig=n.signature, path=change.path))

    gone = [s for n, s in old_by_name.items() if n not in new_by_name]
    fresh = [s for n, s in new_by_name.items() if n not in old_by_name]

    # Pair removed with added by signature similarity -> rename; leftovers are remove/add.
    used: set[str] = set()
    for o in gone:
        best, best_score = None, 0.0
        for n in fresh:
            if n.name in used:
                continue
            # Compare signatures with the names blanked so only the shape is compared.
            score = _similar(o.signature.replace(o.name, "_"), n.signature.replace(n.name, "_"))
            if score > best_score:
                best, best_score = n, score
        if best is not None and best_score >= 0.7:
            used.add(best.name)
            results.append(SymbolChange("renamed", o.name, new_name=best.name,
                                        old_sig=o.signature, new_sig=best.signature,
                                        path=change.path))
        else:
            results.append(SymbolChange("removed", o.name, old_sig=o.signature, path=change.path))
    for n in fresh:
        if n.name not in used:
            results.append(SymbolChange("added", n.name, new_sig=n.signature, path=change.path))
    return results


def analyze_diff(text: str) -> list[SymbolChange]:
    out: list[SymbolChange] = []
    for fc in parse_diff(text):
        out.extend(diff_symbols(fc))
    # A symbol "removed" from one file but added/modified in another was moved, not deleted.
    alive = {c.name for c in out if c.kind in ("added", "modified")}
    return [c for c in out if not (c.kind == "removed" and c.name in alive)]
