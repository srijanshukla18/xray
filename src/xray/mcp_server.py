"""XRAY MCP server: compact code maps and symbol lookup for AI coding agents."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from xray import __version__
from xray.core.indexer import XRayIndexer

mcp = FastMCP(
    "xray",
    version=__version__,
    instructions=(
        "Read a codebase's shape without reading its code. Typical flow: explore_repo for "
        "layout, find_symbol to locate a definition, read_interface to see a file's API "
        "with line numbers, what_breaks before renaming or changing a signature."
    ),
)

_indexers: Dict[str, XRayIndexer] = {}


def _indexer(root_path: str) -> XRayIndexer:
    path = Path(os.path.expanduser(root_path)).resolve()
    if not path.is_dir():
        raise ToolError(f"root_path '{root_path}' is not a directory")
    key = str(path)
    if key not in _indexers:
        _indexers[key] = XRayIndexer(key)
    return _indexers[key]


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (ValueError, RuntimeError, OSError) as e:
        raise ToolError(str(e)) from e


@mcp.tool
def explore_repo(
    root_path: str,
    max_depth: Optional[int] = None,
    include_symbols: bool = False,
    focus_dirs: Optional[List[str]] = None,
    max_symbols_per_file: int = 5,
) -> str:
    """Directory tree of a project (respects .gitignore), optionally with each file's
    function/class signatures and one-line docs.

    Start with max_depth=2 and no symbols; then pass focus_dirs (paths relative to
    root, e.g. ["src/api"]) with include_symbols=True. Directories cut off by max_depth
    show their file count. Output is capped at 1000 lines.
    """
    return _run(_indexer(root_path).explore_repo, max_depth, include_symbols, focus_dirs, max_symbols_per_file)


@mcp.tool
def find_symbol(root_path: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Fuzzy-find function, method, class, interface, struct and type definitions by name.

    Matches ignore case and separators ("user service" finds UserService;
    "UserService.add" finds its add* methods). Returns name, type, path, start_line,
    end_line, signature and parent (enclosing class), best match first.
    """
    return _run(_indexer(root_path).find_symbol, query, limit)


@mcp.tool
def read_interface(root_path: str, file_path: str) -> str:
    """A file's API without its implementation: every class, function, method and
    type signature with line numbers and one-line docs, nested by scope.

    Use instead of reading a whole file when you only need to know how to call it.
    file_path may be absolute or relative to root_path.
    """
    return _run(_indexer(root_path).read_interface, file_path)


@mcp.tool
def what_breaks(
    root_path: str,
    name: str,
    path: Optional[str] = None,
    line: Optional[int] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """Every code reference to an identifier, excluding comments, strings and its
    definitions. Run before renaming or changing a signature.

    Name-based, not type-aware: same-named symbols elsewhere also match. Pass the
    path and line of the definition you mean (from find_symbol) to be warned when
    other definitions share the name.
    """
    return _run(_indexer(root_path).what_breaks, name, path, line, limit)


def main():
    mcp.run(show_banner=False)


if __name__ == "__main__":
    main()
