"""XRAY's four operations: explore_repo, find_symbol, read_interface, what_breaks."""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz

from xray.core.files import list_files
from xray.core.symbols import LANGUAGE_MAP, SymbolIndex, find_identifier_lines, language_of, map_files, read_source

MAX_TREE_LINES = 1000
_IDENTIFIER = re.compile(r"^[A-Za-z_$][\w$]*$")
_NORMALIZE = re.compile(r"[\s_\-.]+")


def _norm(text: str) -> str:
    return _NORMALIZE.sub("", text.lower())


class XRayIndexer:
    def __init__(self, root_path: str):
        self.root_path = Path(root_path).resolve()
        self.index = SymbolIndex(self.root_path)

    # --- helpers -------------------------------------------------------------

    def _rel(self, path: str) -> str:
        """Resolve a user-supplied path to a POSIX path relative to root, refusing escapes."""
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = self.root_path / target
        target = target.resolve()
        if not target.is_relative_to(self.root_path):
            raise ValueError(f"'{path}' is outside the project root {self.root_path}")
        return target.relative_to(self.root_path).as_posix()

    def _abs(self, rel: str) -> str:
        return str(self.root_path / rel)

    # --- explore_repo --------------------------------------------------------

    def explore_repo(
        self,
        max_depth: Optional[int] = None,
        include_symbols: bool = False,
        focus_dirs: Optional[List[str]] = None,
        max_symbols_per_file: int = 5,
    ) -> str:
        files = list_files(self.root_path)
        if focus_dirs:
            prefixes = [self._rel(d).rstrip("/") for d in focus_dirs]
            files = [f for f in files if any(p in ("", ".") or f == p or f.startswith(p + "/") for p in prefixes)]
            if not files:
                raise ValueError(f"No files found under focus_dirs={focus_dirs}")

        tree: Dict[str, Any] = {"dirs": {}, "files": [], "count": 0}
        for rel in files:
            node = tree
            node["count"] += 1
            *parts, _ = rel.split("/")
            for part in parts:
                node = node["dirs"].setdefault(part, {"dirs": {}, "files": [], "count": 0})
                node["count"] += 1
            node["files"].append(rel)

        symbols: Dict[str, List[dict]] = {}
        if include_symbols:
            visible = [f for f in files if max_depth is None or f.count("/") < max_depth]
            symbols = self.index.symbols_for(visible)

        lines = [f"{self.root_path}/"]
        self._render(tree, "", 1, max_depth, symbols, max_symbols_per_file, lines)
        if len(lines) > MAX_TREE_LINES:
            lines = lines[:MAX_TREE_LINES]
            lines.append(f"... truncated at {MAX_TREE_LINES} lines; narrow with max_depth or focus_dirs")
        return "\n".join(lines)

    def _render(self, node, prefix, depth, max_depth, symbols, max_symbols, lines):
        entries = [("d", name, child) for name, child in sorted(node["dirs"].items(), key=lambda kv: kv[0].lower())]
        entries += [("f", rel.rsplit("/", 1)[-1], rel) for rel in sorted(node["files"], key=str.lower)]
        for i, (kind, name, item) in enumerate(entries):
            if len(lines) > MAX_TREE_LINES:
                return
            last = i == len(entries) - 1
            connector, extension = ("└── ", "    ") if last else ("├── ", "│   ")
            if kind == "d":
                if max_depth is not None and depth >= max_depth:
                    lines.append(f"{prefix}{connector}{name}/ ({item['count']} file{'' if item['count'] == 1 else 's'})")
                else:
                    lines.append(f"{prefix}{connector}{name}/")
                    self._render(item, prefix + extension, depth + 1, max_depth, symbols, max_symbols, lines)
            else:
                lines.append(prefix + connector + name)
                file_symbols = symbols.get(item, [])
                shown = file_symbols[:max_symbols]
                rows = ["  " * s["depth"] + _describe(s) for s in shown]
                if len(file_symbols) > max_symbols:
                    rows.append(f"... and {len(file_symbols) - max_symbols} more")
                for j, row in enumerate(rows):
                    lines.append(prefix + extension + ("└── " if j == len(rows) - 1 else "├── ") + row)

    # --- find_symbol ---------------------------------------------------------

    def find_symbol(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        q = _norm(query)
        if not q:
            raise ValueError("query must not be empty")
        all_symbols = self.index.symbols_for(list_files(self.root_path), prune=True)

        scored = []
        for rel, syms in all_symbols.items():
            for s in syms:
                score = _score(q, _norm(s["name"]))
                if s["parent"]:
                    score = max(score, _score(q, _norm(s["parent"] + s["name"])))
                if s["name"] == query.strip():
                    score += 2  # exact spelling beats a normalized tie (fetch_data vs fetchData)
                elif s["name"].lower() == query.strip().lower():
                    score += 1
                if score >= 60:
                    scored.append((-score, len(s["name"]), rel, s["start_line"], s))

        scored.sort(key=lambda t: t[:4])
        return [
            {"name": s["name"], "type": s["type"], "path": self._abs(rel),
             "start_line": s["start_line"], "end_line": s["end_line"],
             "signature": s["signature"], "parent": s["parent"]}
            for _, _, rel, _, s in scored[:limit]
        ]

    # --- read_interface ------------------------------------------------------

    def read_interface(self, file_path: str) -> str:
        rel = self._rel(file_path)
        if not (self.root_path / rel).is_file():
            raise ValueError(f"'{file_path}' is not a file")
        if not language_of(rel):
            supported = ", ".join(sorted(LANGUAGE_MAP))
            raise ValueError(f"Unsupported file type '{Path(rel).suffix}'. Supported: {supported}")
        syms = self.index.symbols_for([rel]).get(rel, [])
        if not syms:
            return f"{rel}: no functions, classes or types found"
        width = len(str(syms[-1]["start_line"]))
        out = [f"{rel} ({len(syms)} symbols; left column is the line number)"]
        out += [f"{s['start_line']:>{width}}  {'  ' * s['depth']}{_describe(s)}" for s in syms]
        return "\n".join(out)

    # --- what_breaks ---------------------------------------------------------

    def what_breaks(
        self,
        name: str,
        path: Optional[str] = None,
        line: Optional[int] = None,
        limit: int = 50,
        context_lines: int = 1,
    ) -> Dict[str, Any]:
        name = name.strip().rsplit(".", 1)[-1]
        if not _IDENTIFIER.match(name):
            raise ValueError(f"'{name}' is not a valid identifier")
        supported = [rel for rel in list_files(self.root_path) if language_of(rel)]
        lines_by_file = map_files(find_identifier_lines, str(self.root_path), supported, name)

        # Definition sites are identifiers too; report them separately.
        definitions = sorted(
            (rel, s["start_line"])
            for rel, syms in self.index.symbols_for(list(lines_by_file)).items()
            for s in syms if s["name"] == name
        )
        definition_set = set(definitions)
        hits = sorted((rel, ln) for rel, lns in lines_by_file.items() for ln in lns
                      if (rel, ln) not in definition_set)

        file_lines: Dict[str, List[str]] = {}
        references = []
        for rel, ln in hits[:limit]:
            if rel not in file_lines:
                file_lines[rel] = (read_source(str(self.root_path), rel) or "").splitlines()
            src = file_lines[rel]
            lo, hi = max(0, ln - 1 - context_lines), min(len(src), ln + context_lines)
            references.append({"file": self._abs(rel), "line": ln, "text": _dedent(src[lo:hi])})

        result: Dict[str, Any] = {
            "symbol": name,
            "total_references": len(hits),
            "files": len({rel for rel, _ in hits}),
            "references": references,
            "definitions": [{"path": self._abs(rel), "line": ln} for rel, ln in definitions],
            "note": "Name-based: every identifier spelled exactly like this, excluding comments and "
                    "strings. Not type-aware, so same-named symbols elsewhere are included.",
        }
        if len(hits) > limit:
            result["truncated"] = f"showing first {limit} of {len(hits)}; raise limit to see more"
        target = (self._rel(path), line) if path and line else None
        others = [d for d in definitions if d != target] if target else []
        if target and others:
            result["warning"] = (f"{len(others)} other definition(s) named '{name}' exist; "
                                 "some references may belong to them")
        return result


def _describe(symbol: dict) -> str:
    return symbol["signature"] + (f"  # {symbol['doc']}" if symbol["doc"] else "")


def _score(query: str, candidate: str) -> float:
    if candidate == query:
        return 100
    if candidate.startswith(query):
        return 90
    if query in candidate:
        return 80
    # Typo tolerance. The cutoff lets rapidfuzz bail out early on hopeless candidates.
    return fuzz.ratio(query, candidate, score_cutoff=80) * 0.75


def _dedent(lines: List[str]) -> str:
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    cut = min(indents) if indents else 0
    return "\n".join(l[cut:].rstrip() for l in lines)
