"""File discovery that honours .gitignore exactly the way git does."""

import os
import subprocess
from pathlib import Path
from typing import List, Optional

import pathspec

# Directories that are noise for code navigation even when they are committed.
EXCLUDED_DIRS = {
    "node_modules", "vendor", "__pycache__", "venv", ".venv", "env",
    "target", "build", "dist", ".git", ".svn", ".hg", ".idea", ".vscode",
    ".xray", "site-packages", ".tox", ".pytest_cache", ".mypy_cache",
}


def list_files(root: Path) -> List[str]:
    """Return POSIX paths, relative to root, of every non-ignored file under root."""
    files = _git_files(root)
    if files is None:
        files = _walk_files(root)
    return sorted(f for f in files if not _in_excluded_dir(f) and _inside(root, f))


def _inside(root: Path, rel: str) -> bool:
    """Cheap listing filter: drop leaf symlinks that lead outside root. Neither git nor
    os.walk lists paths beneath a symlinked directory; the full check in
    resolve_inside runs before every read regardless."""
    path = os.path.join(root, rel)
    return not os.path.islink(path) or resolve_inside(str(root), rel) is not None


def resolve_inside(root: str, rel: str) -> Optional[str]:
    """Real path of root/rel, or None if any symlink along the way leads outside root.

    root must already be resolved. Called both when listing and right before every
    read, so a path swapped for a symlink in between is still refused.
    """
    real = os.path.realpath(os.path.join(root, rel))
    return real if real == root or real.startswith(root.rstrip(os.sep) + os.sep) else None


def _in_excluded_dir(rel: str) -> bool:
    return any(part in EXCLUDED_DIRS for part in rel.split("/")[:-1])


def _git_files(root: Path):
    """Tracked + untracked-but-not-ignored files, or None if root isn't in a git work tree."""
    try:
        result = subprocess.run(
            # A repo's own config can make git run arbitrary commands via core.fsmonitor.
            ["git", "-c", "core.fsmonitor=false", "ls-files", "-z", "--cached", "--others",
             "--exclude-standard"],
            cwd=root, capture_output=True, timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    paths = result.stdout.decode("utf-8", "surrogateescape").split("\0")
    # --cached includes files deleted from the work tree but not yet staged.
    base = str(root)
    return [p for p in paths if p and os.path.isfile(os.path.join(base, p))]


def _walk_files(root: Path) -> List[str]:
    """Fallback for non-git directories: walk, applying the root .gitignore."""
    spec = None
    gitignore = root / ".gitignore"
    if gitignore.is_file():
        spec = pathspec.GitIgnoreSpec.from_lines(gitignore.read_text(errors="replace").splitlines())

    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = [
            d for d in dirnames
            if d not in EXCLUDED_DIRS and not (spec and spec.match_file(rel_dir + d + "/"))
        ]
        for name in filenames:
            rel = rel_dir + name
            if not (spec and spec.match_file(rel)):
                files.append(rel)
    return files
