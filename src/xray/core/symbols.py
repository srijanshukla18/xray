"""Symbol extraction with ast-grep (tree-sitter), plus a per-file mtime cache.

Uses ast-grep's in-process Python binding rather than the CLI: the CLI's JSON output
repeats every matched node's full text, which reached ~1GB on a 20k-file repo. Large
batches fan out to worker processes because tree-sitter parsing is CPU-bound and the
binding holds the GIL.

explore_repo, find_symbol and read_interface all read from the same extracted data,
so they can never disagree with each other.
"""

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ast_grep_py import SgRoot

# File extension -> ast-grep language id.
LANGUAGE_MAP = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
}

# Bump whenever extraction output changes so stale caches are discarded.
CACHE_VERSION = 4

# Definition node kind -> symbol type, per language.
_JS_KINDS = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "class",
    "method_definition": "method",
    "variable_declarator": "function",  # only when the value is a function, see _extract
}
_TS_KINDS = {
    **_JS_KINDS,
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
    "internal_module": "namespace",
}
DEFINITION_KINDS = {
    "python": {"function_definition": "function", "class_definition": "class"},
    "javascript": _JS_KINDS,
    "typescript": _TS_KINDS,
    "tsx": _TS_KINDS,
    "go": {"function_declaration": "function", "method_declaration": "method",
           "type_spec": "type", "type_alias": "type"},
}

# Identifier node kinds per language, used to find references.
IDENTIFIER_KINDS = {
    "python": ["identifier"],
    "javascript": ["identifier", "property_identifier", "shorthand_property_identifier",
                   "shorthand_property_identifier_pattern"],
    "go": ["identifier", "field_identifier", "type_identifier"],
}
IDENTIFIER_KINDS["typescript"] = IDENTIFIER_KINDS["javascript"] + ["type_identifier"]
IDENTIFIER_KINDS["tsx"] = IDENTIFIER_KINDS["typescript"]

_FUNCTION_VALUES = {"arrow_function", "function_expression"}
_PARALLEL_MIN = 200  # below this many files, worker start-up costs more than it saves
_CHUNK = 250


def language_of(rel: str) -> Optional[str]:
    return LANGUAGE_MAP.get(os.path.splitext(rel)[1].lower())


def _read(root: str, rel: str) -> Optional[str]:
    try:
        with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def map_files(fn: Callable[..., dict], root: str, rels: List[str], *args) -> dict:
    """Run fn(root, chunk, *args) over rels, fanning out to worker processes for large batches.

    Workers are plain `python -m xray.core.symbols` subprocesses rather than
    multiprocessing, which would re-import the caller's __main__ under spawn.
    """
    if len(rels) < _PARALLEL_MIN:
        return fn(root, rels, *args)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        filter(None, [str(Path(__file__).resolve().parents[2]), os.environ.get("PYTHONPATH")]))}

    def run(chunk: List[str]) -> dict:
        job = json.dumps({"fn": fn.__name__, "root": root, "rels": chunk, "args": list(args)})
        result = subprocess.run([sys.executable, "-m", "xray.core.symbols"], input=job,
                                capture_output=True, text=True, env=env)
        if result.returncode != 0:
            raise RuntimeError(f"xray worker failed: {result.stderr.strip()[-500:]}")
        return json.loads(result.stdout)

    chunks = [rels[i:i + _CHUNK] for i in range(0, len(rels), _CHUNK)]
    merged: dict = {}
    with ThreadPoolExecutor(min(8, os.cpu_count() or 4)) as pool:
        for part in pool.map(run, chunks):
            merged.update(part)
    return merged


# --- definitions -------------------------------------------------------------

_PY_DOCSTRING = re.compile(r'\s*[rRuUbB]*("""|\'\'\'|"|\')(.*?)\1', re.DOTALL)
_MAX_SIG = 160
_MAX_DOC = 80


def extract_symbols(root: str, rels: List[str]) -> Dict[str, List[dict]]:
    """Worker: symbols for each readable file in rels."""
    out = {}
    for rel in rels:
        text = _read(root, rel)
        lang = language_of(rel)
        if text is not None and lang:
            out[rel] = _extract(text, lang)
    return out


def _extract(text: str, lang: str) -> List[dict]:
    kinds = DEFINITION_KINDS[lang]
    lines = text.splitlines()
    symbols = []
    for node in SgRoot(text, lang).root().find_all(any=[{"kind": k} for k in kinds]):
        name_node = node.field("name")
        if name_node is None:
            continue
        kind = node.kind()
        label = kinds[kind]
        if kind == "variable_declarator":
            value = node.field("value")
            if value is None or value.kind() not in _FUNCTION_VALUES:
                continue
        if kind == "type_spec":
            type_kind = (node.field("type") or name_node).kind()
            label = {"struct_type": "struct", "interface_type": "interface"}.get(type_kind, "type")

        rng = node.range()
        start, end = rng.start.index, rng.end.index
        name = name_node.text()
        line_start = text.rfind("\n", 0, start) + 1
        sig_end = None
        if lang == "go" and label in ("struct", "interface"):
            signature = f"type {name} {label}"
        else:
            if label == "type":
                sig_end = _line_end(text, start, end)
            else:
                sig_end = _signature_end(text, name_node.range().end.index, end, lang)
            signature = _clean_signature(text[line_start:sig_end])
            if lang == "go" and label == "type" and not signature.startswith("type "):
                signature = "type " + signature  # member of a grouped `type ( ... )` block

        if lang == "python":
            doc = _python_doc(text[sig_end + 1:sig_end + 4001]) if sig_end is not None and sig_end < end else ""
        else:
            doc = _comment_doc(lines, rng.start.line)

        symbols.append({
            "name": name,
            "type": label,
            "start_line": rng.start.line + 1,  # ast-grep lines are 0-based
            "end_line": rng.end.line + 1,
            "signature": signature,
            "doc": doc,
            "_start": start,
            "_end": end,
        })
    return _nest(symbols)


def _nest(symbols: List[dict]) -> List[dict]:
    """Order by position, attach parent/depth from range containment, and drop
    definitions local to a function (closures, callbacks): they aren't part of any API."""
    symbols.sort(key=lambda s: (s["_start"], -s["_end"]))
    stack: List[dict] = []
    kept = []
    for s in symbols:
        while stack and stack[-1]["_end"] < s["_end"]:
            stack.pop()
        parent = stack[-1] if stack else None
        s["_local"] = bool(parent and (parent["_local"] or parent["type"] in ("function", "method")))
        if s["type"] == "function" and parent and parent["type"] == "class":
            s["type"] = "method"
        stack.append(s)
        if not s["_local"]:
            s["parent"] = parent["name"] if parent else None
            s["depth"] = len(stack) - 1
            kept.append(s)
    for s in kept:
        del s["_start"], s["_end"], s["_local"]
    return kept


def _signature_end(text: str, pos: int, end: int, lang: str) -> int:
    """Offset where a definition's header ends: the body's `{` (or `:` in Python), or
    just past `=>` for arrow functions. Skips brackets and string literals."""
    depth, quote, i = 0, None, pos
    while i < end:
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif depth == 0:
            if lang == "python":
                if c == ":":
                    return i
            elif c == "{":
                return i
            elif c == "=" and text.startswith(">", i + 1):
                return i + 2
        i += 1
    return _line_end(text, pos, end)


def _line_end(text: str, pos: int, end: int) -> int:
    newline = text.find("\n", pos, end)
    return end if newline == -1 else newline


def _clean_signature(raw: str) -> str:
    sig = " ".join(raw.split())
    sig = re.sub(r"\(\s+", "(", sig)
    sig = re.sub(r",?\s+\)", ")", sig)
    sig = sig.rstrip(" {:=;").rstrip()
    return sig if len(sig) <= _MAX_SIG else sig[:_MAX_SIG - 1] + "…"


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip().lstrip("*").strip()
        if line and not line.startswith("@"):
            return line if len(line) <= _MAX_DOC else line[:_MAX_DOC - 1] + "…"
    return ""


def _python_doc(after_colon: str) -> str:
    m = _PY_DOCSTRING.match(after_colon)
    return _first_line(m.group(2)) if m else ""


def _comment_doc(lines: List[str], line_idx: int) -> str:
    """The comment block immediately above line_idx (0-based), skipping decorators."""
    i = line_idx - 1
    while i >= 0 and lines[i].strip().startswith("@"):
        i -= 1
    if i < 0:
        return ""
    stripped = lines[i].strip()
    if stripped.startswith("//"):
        start = i
        while start - 1 >= 0 and lines[start - 1].strip().startswith("//"):
            start -= 1
        return _first_line("\n".join(l.strip()[2:] for l in lines[start:i + 1]))
    if stripped.endswith("*/"):
        start = i
        while start >= 0 and "/*" not in lines[start]:
            start -= 1
        if start < 0:
            return ""
        block = "\n".join(lines[start:i + 1])
        return _first_line(block[block.index("/*") + 2:block.rindex("*/")])
    return ""


# --- references --------------------------------------------------------------

def find_identifier_lines(root: str, rels: List[str], name: str) -> Dict[str, List[int]]:
    """Worker: 1-based lines where an identifier node is exactly `name`.

    Matching on identifier node kinds is what excludes comments and string literals.
    """
    pattern = "^" + re.escape(name) + "$"
    out = {}
    for rel in rels:
        text = _read(root, rel)
        lang = language_of(rel)
        if text is None or not lang or name not in text:
            continue
        rule = {"regex": pattern, "any": [{"kind": k} for k in IDENTIFIER_KINDS[lang]]}
        found = sorted({n.range().start.line + 1 for n in SgRoot(text, lang).root().find_all(**rule)})
        if found:
            out[rel] = found
    return out


# --- cache -------------------------------------------------------------------

class SymbolIndex:
    """Lazily extracted symbols for files under one root.

    Held in memory and persisted to SQLite (one row per file) so a restart doesn't
    re-parse the repo. A file is re-extracted only when its mtime or size changes.
    """

    def __init__(self, root: Path):
        self.root = root
        self._root_str = str(root)
        self._lock = threading.Lock()
        self._files: Dict[str, Tuple[Tuple[int, int], List[dict]]] = {}
        self._db: Optional[sqlite3.Connection] = None
        cache_home = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
        key = hashlib.sha256(self._root_str.encode()).hexdigest()[:16]
        self.cache_file = cache_home / "xray" / f"{key}.sqlite"
        try:
            self._open()
        except sqlite3.Error:
            self._db = None  # the cache is an optimisation; work in memory only

    def _open(self) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.cache_file, check_same_thread=False)
        db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        version = db.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
        if version != (str(CACHE_VERSION),):
            db.execute("DROP TABLE IF EXISTS files")
            db.execute("INSERT OR REPLACE INTO meta VALUES ('version', ?)", (str(CACHE_VERSION),))
        db.execute("CREATE TABLE IF NOT EXISTS files "
                   "(rel TEXT PRIMARY KEY, mtime_ns INTEGER, size INTEGER, symbols TEXT)")
        db.commit()
        for rel, mtime, size, syms in db.execute("SELECT rel, mtime_ns, size, symbols FROM files"):
            self._files[rel] = ((mtime, size), json.loads(syms))
        self._db = db

    def _persist(self, updated: List[str], removed: List[str]) -> None:
        if not self._db:
            return
        try:
            self._db.executemany(
                "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?)",
                [(rel, *self._files[rel][0], json.dumps(self._files[rel][1])) for rel in updated],
            )
            self._db.executemany("DELETE FROM files WHERE rel = ?", [(rel,) for rel in removed])
            self._db.commit()
        except sqlite3.Error:
            pass

    def symbols_for(self, rel_paths: List[str], prune: bool = False) -> Dict[str, List[dict]]:
        """Symbols for each supported file in rel_paths, re-extracting only changed files.

        prune=True drops cache entries for files not in rel_paths (pass the full file list).
        """
        with self._lock:
            stale, stamps = [], {}
            for rel in rel_paths:
                if not language_of(rel):
                    continue
                try:
                    st = os.stat(os.path.join(self._root_str, rel))
                except OSError:
                    continue
                stamps[rel] = (st.st_mtime_ns, st.st_size)
                entry = self._files.get(rel)
                if not entry or tuple(entry[0]) != stamps[rel]:
                    stale.append(rel)

            if stale:
                for rel, syms in map_files(extract_symbols, self._root_str, stale).items():
                    self._files[rel] = (stamps[rel], syms)

            removed = [rel for rel in self._files if rel not in stamps] if prune else []
            for rel in removed:
                del self._files[rel]
            if stale or removed:
                self._persist([rel for rel in stale if rel in self._files], removed)
            return {rel: self._files[rel][1] for rel in stamps if rel in self._files}


_WORKERS = {f.__name__: f for f in (extract_symbols, find_identifier_lines)}

if __name__ == "__main__":
    job = json.load(sys.stdin)
    json.dump(_WORKERS[job["fn"]](job["root"], job["rels"], *job["args"]), sys.stdout)
