# XRAY

**An MCP server that lets coding agents see a codebase's shape — layout, signatures, definitions, references — without reading whole files.**

[![Python](https://img.shields.io/badge/Python-3.11+-green)](https://python.org) [![MCP](https://img.shields.io/badge/MCP-Compatible-purple)](https://modelcontextprotocol.io) [![ast-grep](https://img.shields.io/badge/Powered_by-ast--grep-orange)](https://ast-grep.github.io)

## Why

Coding agents already have grep, glob and file reads. Where they burn context is:

- **Reading a 1,500-line file to learn three function signatures.** `read_interface` returns the file's API — every class, method, function and type with its signature, one-line doc and line number — so the agent reads only the lines it needs.
- **Grepping a name and wading through comments, strings and partial matches.** `find_symbol` returns definitions only, ranked, fuzzy. `what_breaks` returns identifier references with comments and string literals excluded.

| | grep / rg | XRAY | LSP |
|---|---|---|---|
| Setup | none | `uv tool install` | a server per language |
| Finds definitions only | ✗ | ✓ | ✓ |
| Skips comments & strings | ✗ | ✓ | ✓ |
| File API without the bodies | ✗ | ✓ | partial (document symbols) |
| Type-aware references | ✗ | ✗ (name-based) | ✓ |

XRAY sits between the two: syntax-aware via tree-sitter, zero per-language setup, and honest about not resolving types.

## Install

```bash
uv tool install git+https://github.com/srijanshukla18/xray
```

Then register the `xray-mcp` command with your client.

**Claude Code**

```bash
claude mcp add xray -s user -- xray-mcp
```

**Claude Desktop, Cursor, VS Code, others** — add to the client's MCP config:

```json
{ "mcpServers": { "xray": { "command": "xray-mcp" } } }
```

To run without installing: `uvx --from git+https://github.com/srijanshukla18/xray xray-mcp`.

There is also `install.sh`, which installs uv if needed and then runs the command above.

## Tools

All paths in results are absolute. `root_path` is the project directory.

### `explore_repo(root_path, max_depth=None, include_symbols=False, focus_dirs=None, max_symbols_per_file=5)`

Directory tree honouring `.gitignore` (via `git ls-files`, or a `.gitignore` parser outside git). Directories cut off by `max_depth` show their file count. Output is capped at 1,000 lines.

```
explore_repo("/home/me/xray", max_depth=2)

/home/me/xray/
├── src/
│   └── xray/ (6 files)
├── tests/
│   ├── __init__.py
│   └── test_xray.py
├── pyproject.toml
└── README.md
```

`focus_dirs` takes paths relative to the root; with `include_symbols=True` each file lists its signatures:

```
explore_repo("/home/me/xray", focus_dirs=["src/xray/core"], include_symbols=True, max_symbols_per_file=3)

/home/me/xray/
└── src/
    └── xray/
        └── core/
            ├── files.py
            │   ├── def list_files(root: Path) -> List[str]  # Return POSIX paths, relative to root, of every non-ignored…
            │   ├── def _in_excluded_dir(rel: str) -> bool
            │   ├── def _git_files(root: Path)  # Tracked + untracked-but-not-ignored files, or None if root isn't in…
            │   └── ... and 1 more
            ...
```

### `find_symbol(root_path, query, limit=10)`

Fuzzy search over definitions. Case and separators are ignored (`"user service"` finds `UserService`), a `Class.method` query matches methods by their class, and an exact spelling wins ties.

```json
find_symbol("/home/me/xray", "symbols for")

[{
  "name": "symbols_for", "type": "method", "parent": "SymbolIndex",
  "path": "/home/me/xray/src/xray/core/symbols.py", "start_line": 357, "end_line": 385,
  "signature": "def symbols_for(self, rel_paths: List[str], prune: bool = False) -> Dict[str, List[dict]]"
}]
```

### `read_interface(root_path, file_path)`

A file's API, nested by scope, with line numbers. Functions defined inside other functions are left out — they're not part of the interface. Paths outside `root_path` are refused.

```
read_interface("/home/me/xray", "src/xray/core/indexer.py")

src/xray/core/indexer.py (13 symbols; left column is the line number)
 17  def _norm(text: str) -> str
 21  class XRayIndexer
 22    def __init__(self, root_path: str)
 28    def _rel(self, path: str) -> str  # Resolve a user-supplied path to a POSIX path relative to root, refusing…
105    def find_symbol(self, query: str, limit: int = 10) -> List[Dict[str, Any]]
134    def read_interface(self, file_path: str) -> str
...
```

### `what_breaks(root_path, name, path=None, line=None, limit=50)`

Every identifier spelled exactly `name`, excluding comments, string literals and the definitions themselves (which are listed separately). Pass the `path` and `line` of the definition you mean, and XRAY warns when other definitions share the name.

```json
what_breaks("/home/me/xray", "list_files", path="src/xray/core/files.py", line=18, limit=2)

{
  "symbol": "list_files",
  "total_references": 7,
  "files": 2,
  "references": [
    {"file": "/home/me/xray/src/xray/core/indexer.py", "line": 9,
     "text": "from xray.core.files import list_files\nfrom xray.core.symbols import ..."},
    {"file": "/home/me/xray/src/xray/core/indexer.py", "line": 50,
     "text": ") -> str:\n    files = list_files(self.root_path)\n    if focus_dirs:"}
  ],
  "definitions": [{"path": "/home/me/xray/src/xray/core/files.py", "line": 18}],
  "note": "Name-based: every identifier spelled exactly like this, excluding comments and strings. ...",
  "truncated": "showing first 2 of 7; raise limit to see more"
}
```

**It is name-based, not type-aware.** `what_breaks("save")` finds every `.save` in the repo, not just the one on your class. Use it as a precise grep, not as a compiler.

## Languages

| Language | Extensions | Extracted |
|---|---|---|
| Python | `.py` `.pyi` | functions, async functions, classes, methods; first line of docstrings |
| JavaScript | `.js` `.jsx` `.mjs` `.cjs` | functions, generators, classes, methods, `const f = () =>` / `function` expressions |
| TypeScript | `.ts` `.tsx` `.mts` `.cts` | JavaScript's set plus interfaces, type aliases, enums, namespaces, abstract classes |
| Go | `.go` | functions, methods, structs, interfaces, other type declarations |

For non-Python languages the doc is the first line of the `//` or `/** */` comment directly above the definition.

## How it works

- **Files**: `git ls-files --cached --others --exclude-standard`, so nested `.gitignore`s, negations and global excludes all behave exactly as in git. Dependency and build directories (`node_modules`, `vendor`, `.venv`, `dist`, …) are always skipped.
- **Parsing**: [ast-grep](https://ast-grep.github.io)'s Python binding (tree-sitter grammars). One pass per file extracts every definition; `explore_repo`, `find_symbol` and `read_interface` all read that same data.
- **Cache**: `~/.cache/xray/<hash-of-root>.sqlite` (honours `XDG_CACHE_HOME`), one row per file keyed on mtime and size. Only changed files are re-parsed; the cache survives server restarts.
- **Large repos**: batches of 200+ files are spread over up to 8 worker processes.

Measured on a 21,000-file Go/TS repo (Apple M-series, 10 cores): first `find_symbol` 8 s (builds the cache), later calls ~1 s, `what_breaks` ~2 s.

## Development

```bash
git clone https://github.com/srijanshukla18/xray && cd xray
uv sync
uv run pytest
```

`test_samples/` holds one file per language; the tests assert exact names and line numbers against them, and drive the tools through a real MCP client.

## Uninstall

```bash
uv tool uninstall xray && rm -rf ~/.cache/xray
```

or run `uninstall.sh`.

## Design notes

Approaches tried before settling on this one:

1. **grep** — can't tell a definition from a comment or a string.
2. **Raw tree-sitter bindings** — grammar and binding build problems across platforms.
3. **LSP** — precise, but asks users to install and run a language server per language.
4. **Comby** — unstable for this workload.
5. **ast-grep CLI** — correct, but its JSON repeats each matched node's full text; on a 20k-file repo that was ~1 GB of output per index. The in-process binding gives the same parser without the serialisation.
