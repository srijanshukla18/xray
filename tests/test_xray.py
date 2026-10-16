import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from xray.core import symbols as symbols_mod
from xray.core.files import list_files
from xray.core.indexer import XRayIndexer

SAMPLES = Path(__file__).parent.parent / "test_samples"


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path_factory.mktemp("cache")))


@pytest.fixture
def samples(tmp_path):
    root = tmp_path / "samples"
    shutil.copytree(SAMPLES, root)
    return XRayIndexer(str(root))


def write(root: Path, files: dict):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


# --- find_symbol -------------------------------------------------------------

@pytest.mark.parametrize("query,name,type_,file,line", [
    ("fetch_data", "fetch_data", "function", "test.py", 38),
    ("DataProcessor", "DataProcessor", "class", "test.py", 9),
    ("async_fetch", "async_fetch", "function", "test.py", 43),
    ("fetchData", "fetchData", "function", "test.js", 12),
    ("BaseService", "BaseService", "class", "test.ts", 23),
    ("UserRole", "UserRole", "type", "test.ts", 13),
    ("NewUserService", "NewUserService", "function", "test.go", 68),
    ("Service", "Service", "interface", "test.go", 19),
])
def test_find_symbol_every_language_with_1_based_lines(samples, query, name, type_, file, line):
    top = samples.find_symbol(query)[0]
    assert (top["name"], top["type"], Path(top["path"]).name, top["start_line"]) == (name, type_, file, line)


def test_find_symbol_methods_know_their_class(samples):
    top = samples.find_symbol("UserService.addUser")[0]
    assert (top["name"], top["parent"], top["type"]) == ("addUser", "UserService", "method")


def test_find_symbol_ignores_case_and_separators(samples):
    assert samples.find_symbol("data processor")[0]["name"] == "DataProcessor"


def test_find_symbol_drops_junk_matches(samples):
    assert samples.find_symbol("zzqqxx") == []


# --- read_interface ----------------------------------------------------------

def test_read_interface_shows_nested_signatures_with_lines(samples):
    out = samples.read_interface("test.py")
    assert " 9  class DataProcessor" in out
    assert "14    def process(self, items: List[str]) -> List[str]  # Process a list of items." in out
    assert "38  def fetch_data(url: str) -> Dict[str, any]  # Fetch data from a URL." in out


def test_read_interface_hides_local_functions(tmp_path):
    write(tmp_path, {"m.py": (
        "def outer():\n"
        "    def helper():\n"
        "        class Local: pass\n"
        "    return helper\n"
        "class Api:\n"
        "    def call(self):\n"
        "        cb = lambda: 1\n"
    ), "m.js": "function outer() {\n  const cb = () => 1;\n}\nconst top = () => 2;\n"})
    ix = XRayIndexer(str(tmp_path))
    assert ix.read_interface("m.py").splitlines()[1:] == ["1  def outer()", "5  class Api", "6    def call(self)"]
    assert ix.read_interface("m.js").splitlines()[1:] == ["1  function outer()", "4  const top = () =>"]


def test_read_interface_refuses_paths_outside_root(samples, tmp_path):
    (tmp_path / "secret.py").write_text("def leaked(): pass\n")
    with pytest.raises(ValueError, match="outside the project root"):
        samples.read_interface("../secret.py")
    with pytest.raises(ValueError, match="outside the project root"):
        samples.read_interface(str(tmp_path / "secret.py"))


def test_read_interface_rejects_unsupported_files(samples):
    (samples.root_path / "notes.txt").write_text("hi")
    with pytest.raises(ValueError, match="Unsupported"):
        samples.read_interface("notes.txt")


# --- what_breaks -------------------------------------------------------------

def test_what_breaks_finds_code_refs_not_comments_or_strings(tmp_path):
    write(tmp_path, {
        "lib.py": "def charge(amount):\n    return amount\n",
        "app.py": (
            "from lib import charge\n"
            "# charge is mentioned in a comment\n"
            "msg = 'charge in a string'\n"
            "total = charge(10)\n"
        ),
        "web.js": "import { charge } from './lib';\napi.charge(5);\n",
    })
    result = XRayIndexer(str(tmp_path)).what_breaks("charge", path="lib.py", line=1)
    found = {(Path(r["file"]).name, r["line"]) for r in result["references"]}
    assert found == {("app.py", 1), ("app.py", 4), ("web.js", 1), ("web.js", 2)}
    assert result["definitions"] == [{"path": str(tmp_path.resolve() / "lib.py"), "line": 1}]
    assert "warning" not in result


def test_what_breaks_warns_about_same_named_definitions(samples):
    result = samples.what_breaks("User", path="test.py", line=29)
    assert len(result["definitions"]) > 1
    assert "other definition" in result["warning"]


def test_what_breaks_truncates(samples):
    result = samples.what_breaks("User", limit=2)
    assert len(result["references"]) == 2
    assert result["total_references"] > 2 and "truncated" in result


def test_what_breaks_rejects_non_identifiers(samples):
    with pytest.raises(ValueError):
        samples.what_breaks("rm -rf")


# --- explore_repo / file discovery ------------------------------------------

def test_gitignore_is_respected_without_substring_false_positives(tmp_path):
    write(tmp_path, {
        ".gitignore": "env\n*.log\nsecret/\n",
        "environment.py": "",
        "env/x.py": "",
        "app.log": "",
        "secret/key.py": "",
        "src/main.py": "",
    })
    assert list_files(tmp_path) == [".gitignore", "environment.py", "src/main.py"]


def test_gitignore_via_git_including_nested_ignores(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git not installed")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    write(tmp_path, {
        ".gitignore": "*.log\n",
        "pkg/.gitignore": "generated.py\n",
        "pkg/generated.py": "",
        "pkg/real.py": "",
        "debug.log": "",
        "node_modules/dep/index.js": "",
    })
    assert list_files(tmp_path) == [".gitignore", "pkg/.gitignore", "pkg/real.py"]


def test_explore_repo_depth_collapses_dirs_with_counts(tmp_path):
    write(tmp_path, {"a/b/c.py": "", "a/b/d.py": "", "a/e.py": "", "z/one.py": "", "top.py": ""})
    out = XRayIndexer(str(tmp_path)).explore_repo(max_depth=1)
    assert out.splitlines()[1:] == ["├── a/ (3 files)", "├── z/ (1 file)", "└── top.py"]


def test_explore_repo_focus_and_symbols(samples):
    write(samples.root_path, {"other/skip.py": "def skip(): pass\n"})
    out = samples.explore_repo(include_symbols=True, focus_dirs=["."], max_symbols_per_file=2)
    assert "test.go" in out and "... and" in out
    out = samples.explore_repo(include_symbols=True, focus_dirs=["other"])
    assert "def skip()" in out and "test.go" not in out


def test_explore_repo_unknown_focus_dir_errors(samples):
    with pytest.raises(ValueError, match="No files"):
        samples.explore_repo(focus_dirs=["nope"])


# --- cache -------------------------------------------------------------------

def test_cache_only_reextracts_changed_files(tmp_path, monkeypatch):
    write(tmp_path, {"a.py": "def one(): pass\n", "b.py": "def two(): pass\n"})
    scanned = []
    real_extract = symbols_mod.extract_symbols

    def spy(root, rels):
        scanned.append(sorted(rels))
        return real_extract(root, rels)

    monkeypatch.setattr(symbols_mod, "extract_symbols", spy)
    XRayIndexer(str(tmp_path)).find_symbol("one")
    (tmp_path / "b.py").write_text("def two_changed(): pass\n")
    fresh = XRayIndexer(str(tmp_path))  # new instance: must load the cache from disk
    assert fresh.find_symbol("two_changed")[0]["name"] == "two_changed"
    assert scanned == [["a.py", "b.py"], ["b.py"]]


# --- MCP protocol ------------------------------------------------------------

def test_tools_over_mcp_protocol(samples):
    from fastmcp import Client
    from fastmcp.exceptions import ToolError
    from xray.mcp_server import mcp

    root = str(samples.root_path)

    async def scenario():
        async with Client(mcp) as client:
            tools = {t.name for t in await client.list_tools()}
            assert tools == {"explore_repo", "find_symbol", "read_interface", "what_breaks"}

            # LLMs often send numbers and booleans as strings.
            tree = await client.call_tool("explore_repo", {"root_path": root, "max_depth": "1",
                                                           "include_symbols": "true"})
            assert "class DataProcessor" in tree.content[0].text

            found = await client.call_tool("find_symbol", {"root_path": root, "query": "fetch_data"})
            top = json.loads(found.content[0].text)[0]
            assert top["start_line"] == 38

            broke = await client.call_tool("what_breaks", {"root_path": root, "name": "fetch_data",
                                                           "path": top["path"], "line": top["start_line"]})
            assert {r["line"] for r in json.loads(broke.content[0].text)["references"]} == {46, 63}

            with pytest.raises(ToolError, match="outside the project root"):
                await client.call_tool("read_interface", {"root_path": root, "file_path": "/etc/passwd"})

    asyncio.run(scenario())


def test_worker_processes_match_in_process_results(samples, monkeypatch):
    serial_symbols = samples.find_symbol("User", limit=50)
    serial_refs = samples.what_breaks("User")

    monkeypatch.setattr(symbols_mod, "_PARALLEL_MIN", 1)
    monkeypatch.setattr(symbols_mod, "_CHUNK", 2)  # several workers for five files
    fresh = XRayIndexer(str(samples.root_path))
    fresh.index._files.clear()  # force re-extraction through the workers
    assert fresh.find_symbol("User", limit=50) == serial_symbols
    assert fresh.what_breaks("User") == serial_refs
