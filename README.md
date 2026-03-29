# XRAY MCP - Progressive Code Intelligence for AI Assistants

[![Python](https://img.shields.io/badge/Python-3.10+-green)](https://python.org) [![MCP](https://img.shields.io/badge/MCP-Compatible-purple)](https://modelcontextprotocol.io) [![ast-grep](https://img.shields.io/badge/Powered_by-ast--grep-orange)](https://ast-grep.github.io)

## ❌ Without XRAY

AI assistants struggle with codebase understanding. You get:

- ❌ "I can't see your code structure"
- ❌ "I don't know what depends on this function"
- ❌ Generic refactoring advice without impact analysis
- ❌ No understanding of symbol relationships

## ✅ With XRAY

XRAY gives AI assistants code navigation capabilities. Add `use XRAY tools` to your prompt:

```txt
Analyze the UserService class and show me what would break if I change the authenticate method. use XRAY tools
```

```txt
Find all functions that call validate_user and show their dependencies. use XRAY tools
```

XRAY provides three focused tools:

- 🗺️ **Map** (`explore_repo`) - See project structure with symbol skeletons
- 🔍 **Find** (`find_symbol`) - Locate functions and classes with fuzzy search
- 💥 **Impact** (`what_breaks`) - Find where a symbol is referenced

## 🚀 Quick Install

### Modern Install with uv (Recommended)

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install XRAY
git clone https://github.com/srijanshukla18/xray.git
cd xray
uv tool install .
```

### Automated Install with uv

For the quickest setup, this script automates the `uv` installation process.

```bash
curl -fsSL https://raw.githubusercontent.com/srijanshukla18/xray/main/install.sh | bash
```

### Generate Config

```bash
# Get config for your tool
python mcp-config-generator.py cursor local_python
python mcp-config-generator.py claude docker  
python mcp-config-generator.py vscode source
```

## Language Support

XRAY uses [ast-grep](https://ast-grep.github.io), a tree-sitter powered structural search tool, providing accurate parsing for:
- **Python** - Functions, classes, methods, async functions
- **JavaScript** - Functions, classes, arrow functions, imports
- **TypeScript** - All JavaScript features plus interfaces, type aliases
- **Go** - Functions, structs, interfaces, methods

ast-grep ensures structural accuracy - it understands code syntax, not just text patterns.

## The XRAY Workflow - Progressive Discovery

### 1. Map - Start Simple, Then Zoom In
```python
# First: Get the big picture (directories only)
tree = explore_repo("/path/to/project")
# Returns:
# /path/to/project/
# ├── src/
# ├── tests/
# ├── docs/
# └── config/

# Then: Zoom into areas of interest with full details
tree = explore_repo("/path/to/project", focus_dirs=["src"], include_symbols=True)
# Returns:
# /path/to/project/
# └── src/
#     ├── auth.py
#     │   ├── class AuthService: # Handles user authentication
#     │   ├── def authenticate(username, password): # Validates user credentials
#     │   └── def logout(session_id): # Ends user session
#     └── models.py
#         ├── class User(BaseModel): # User account model
#         └── ... and 3 more

# Or: Limit depth for large codebases
tree = explore_repo("/path/to/project", max_depth=2, include_symbols=True)
```

### 2. Find - Locate Specific Symbols
```python
# Find symbols matching "authenticate" (fuzzy search)
symbols = find_symbol("/path/to/project", "authenticate")
# Returns list of exact symbol objects with name, type, path, line numbers
```

### 3. Impact - See What Would Break
```python
# Find where authenticate_user is used
symbol = symbols[0]  # From find_symbol
result = what_breaks(symbol)
# Returns: {"references": [...], "total_count": 12, 
#          "note": "Found 12 potential references based on text search..."}
```


## Architecture

```
FastMCP Server (mcp_server.py)
    ↓
Core Engine (src/xray/core/)
    └── indexer.py      # Orchestrates ast-grep for structural analysis
    ↓
ast-grep (external binary)
    └── Tree-sitter powered structural search
```

**Stateless design** - No database, no persistent index. Each operation runs fresh ast-grep queries for real-time accuracy.

## Why ast-grep?

Traditional grep searches text. ast-grep searches code structure:

- **grep**: Finds "authenticate" in function names, variables, comments, strings
- **ast-grep**: Finds only `def authenticate()` or `function authenticate()` definitions

This structural approach provides clean, accurate results essential for reliable code intelligence.

## Performance Characteristics

- **Startup**: Fast - launches ast-grep subprocess
- **File tree**: Python directory traversal
- **Symbol search**: Runs multiple ast-grep patterns, speed depends on codebase size
- **Impact analysis**: Name-based search across all files
- **Memory**: Minimal - no persistent state

## What Makes This Practical

1. **Progressive Discovery** - Start with directories, add symbols only where needed
2. **Smart Caching** - Symbol extraction cached per git commit for instant re-runs
3. **Flexible Focus** - Use `focus_dirs` to zoom into specific parts of large codebases
4. **Enhanced Symbols** - See function signatures and docstrings, not just names
5. **Based on tree-sitter** - ast-grep provides accurate structural analysis

XRAY helps AI assistants avoid information overload while providing deep code intelligence where needed.

## Stateless Design

XRAY performs on-demand structural analysis using ast-grep. There's no database to manage, no index to build, and no state to maintain. Each query runs fresh against your current code.

## Hosted deployment

A hosted deployment is available on [Fronteir AI](https://fronteir.ai/mcp/srijanshukla18-xray).

## Getting Started

1. **Install**: See [`getting_started.md`](getting_started.md) for modern installation
2. **Map the terrain**: `explore_repo("/path/to/project")`
3. **Find your target**: `find_symbol("/path/to/project", "UserService")`
4. **Assess impact**: `what_breaks(symbol)`

## The XRAY Philosophy

XRAY bridges the gap between simple text search and complex LSP servers:

- **More than grep** - Matches code syntax patterns, not just text
- **Less than LSP** - No language servers or complex setup
- **Practical for AI** - Provides structured data about code relationships

A simple tool that helps AI assistants navigate codebases more effectively than text search alone.

## Architectural Journey & Design Rationale

The current implementation of XRAY is the result of a rigorous evaluation of multiple code analysis methodologies. My journey involved prototyping and assessing several distinct approaches, each with its own set of trade-offs. Below is a summary of the considered architectures and the rationale for my final decision.

1.  **Naive Grep-Based Analysis**: I initially explored a baseline approach using standard `grep` for symbol identification. While expedient, this method proved fundamentally inadequate due to its inability to differentiate between syntactical constructs and simple text occurrences (e.g., comments, strings, variable names). The high signal-to-noise ratio rendered it impractical for reliable code intelligence.

2.  **Tree-Sitter Native Integration**: A direct integration with `tree-sitter` was evaluated to leverage its powerful parsing capabilities. However, this path was fraught with significant implementation complexities, including intractable errors within the parser generation and binding layers. The maintenance overhead and steep learning curve for custom grammar development were deemed prohibitive for a lean, multi-language tool.

3.  **Language Server Protocol (LSP)**: I considered leveraging the Language Server Protocol for its comprehensive, standardized approach to code analysis. This was ultimately rejected due to the excessive operational burden it would impose on the end-user, requiring them to install, configure, and manage separate LSPs for each language in their environment. This friction conflicted with my goal of a lightweight, zero-configuration user experience.

4.  **Comby-Based Structural Search**: `Comby` was explored for its structural search and replacement capabilities. Despite its promising feature set, I encountered significant runtime instability and idiosyncratic behavior that undermined its reliability for mission-critical code analysis. The tool's performance and consistency did not meet my stringent requirements for a production-ready system.

5.  **ast-grep as the Core Engine**: My final and current architecture is centered on `ast-grep`. This tool provides the optimal balance of structural awareness, performance, and ease of integration. By leveraging `tree-sitter` internally, it offers robust, syntactically-aware code analysis without the complexities of direct `tree-sitter` integration or the overhead of LSPs. Its reliability and rich feature set for structural querying made it the unequivocal choice for XRAY's core engine.

---

# Getting Started with XRAY - Modern Installation with uv

XRAY is a minimal-dependency code intelligence system that enhances AI assistants' understanding of codebases. This guide shows how to install and use XRAY with the modern `uv` package manager.

## Prerequisites

- Python 3.10 or later
- [uv](https://docs.astral.sh/uv/) - Fast Python package manager

### Installing uv

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or with pip
pip install uv
```

## Installation Options

### Option 1: Automated Install (Easiest)

For the quickest setup, use the one-line installer from the `README.md`. This will handle everything for you.

```bash
curl -fsSL https://raw.githubusercontent.com/srijanshukla18/xray/main/install.sh | bash
```

### Option 2: Quick Try with uvx (Recommended for Testing)

Run XRAY directly without installation using `uvx`:

```bash
# Clone the repository
git clone https://github.com/srijanshukla18/xray.git
cd xray

# Run XRAY directly with uvx
uvx --from . xray-mcp
```

### Option 3: Install as a Tool (Recommended for Regular Use)

Install XRAY as a persistent tool:

```bash
# Clone and install
git clone https://github.com/srijanshukla18/xray.git
cd xray

# Install with uv
uv tool install .

# Now you can run xray-mcp from anywhere
xray-mcp
```

### Option 4: Development Installation

For contributing or modifying XRAY:

```bash
# Clone the repository
git clone https://github.com/srijanshukla18/xray.git
cd xray

# Create and activate virtual environment with uv
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in editable mode
uv pip install -e .

# Run the server
python -m xray.mcp_server
```

## Configure Your AI Assistant

After installation, configure your AI assistant to use XRAY:

### Using the MCP Config Generator (Recommended)

For easier configuration, use the `mcp-config-generator.py` script located in the XRAY repository. This script can generate the correct JSON configuration for various AI assistants and installation methods.

To use it:

1.  Navigate to the XRAY repository root:
    ```bash
    cd /path/to/xray
    ```
2.  Run the script with your desired tool and installation method. For example, to get the configuration for Claude Desktop with an installed `xray-mcp` script:
    ```bash
    python mcp-config-generator.py claude installed_script
    ```
    Or for VS Code with a local Python installation:
    ```bash
    python mcp-config-generator.py vscode local_python
    ```
    The script will print the JSON configuration and instructions on where to add it.

    Available tools: `cursor`, `claude`, `vscode`
    Available methods: `local_python`, `docker`, `source`, `installed_script` (method availability varies by tool)

### Manual Configuration (Advanced)

If you prefer to configure manually, here are examples for common AI assistants:

#### Claude CLI (Claude Code)

For Claude CLI users, simply run:

```bash
claude mcp add xray xray-mcp -s local
```

Then verify it's connected:

```bash
claude mcp list | grep xray
```

#### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "xray": {
      "command": "uvx",
      "args": ["--from", "/path/to/xray", "xray-mcp"]
    }
  }
}
```

Or if installed as a tool:

```json
{
  "mcpServers": {
    "xray": {
      "command": "xray-mcp"
    }
  }
}
```

#### Cursor

Settings → Cursor Settings → MCP → Add new global MCP server:

```json
{
  "mcpServers": {
    "xray": {
      "command": "xray-mcp"
    }
  }
}
```

## Minimal Dependencies

One of XRAY's best features is its minimal dependency profile. You don't need to install a suite of language servers. XRAY uses:

- **ast-grep**: A single, fast binary for structural code analysis.
- **Python**: For the server and core logic.

This means you can start using XRAY immediately after installation with no complex setup!

## Verify Installation

### 1. Check XRAY is accessible

```bash
# If installed as tool
xray-mcp --version

# If using uvx
uvx --from /path/to/xray xray-mcp --version
```

### 2. Test basic functionality

Create a test file `test_xray.py`:

```python
def hello_world():
    print("Hello from XRAY test!")

def calculate_sum(a, b):
    return a + b

class Calculator:
    def multiply(self, x, y):
        return x * y
```

### 3. In your AI assistant, test these commands:

```
Build the index for the current directory. use XRAY tools
```

Expected: Success message with files indexed

```
Find all functions containing "hello". use XRAY tools
```

Expected: Should find `hello_world` function

```
What would break if I change the multiply method? use XRAY tools
```

Expected: Impact analysis showing any dependencies

## Usage Examples

Once configured, use XRAY by adding "use XRAY tools" to your prompts:

```
# Index a codebase
"Index the src/ directory for analysis. use XRAY tools"

# Find symbols
"Find all classes that contain 'User' in their name. use XRAY tools"

# Impact analysis
"What breaks if I change the authenticate method in UserService? use XRAY tools"

# Dependency tracking
"What does the PaymentProcessor class depend on? use XRAY tools"

# Location queries
"What function is defined at line 125 in main.py? use XRAY tools"
```

## Troubleshooting

### uv not found

Make sure uv is in your PATH:

```bash
# Add to ~/.bashrc or ~/.zshrc
export PATH="$HOME/.cargo/bin:$PATH"
```

### Permission denied

On macOS/Linux, you might need to make the script executable:

```bash
chmod +x ~/.local/bin/xray-mcp
```

### Python version issues

XRAY requires Python 3.10+. Check your version:

```bash
python --version

# If needed, install Python 3.10+ with uv
uv python install 3.10
```

### MCP connection issues

1. Check XRAY is running: `xray-mcp --test`
2. Verify your MCP config JSON is valid
3. Restart your AI assistant after config changes

## Advanced Configuration

### Custom Database Location

Set the `XRAY_DB_PATH` environment variable:

```bash
export XRAY_DB_PATH="$HOME/.xray/databases"
```

### Debug Mode

Enable debug logging:

```bash
export XRAY_DEBUG=1
```

## What's Next?

1. **Index your first repository**: In your AI assistant, ask it to "Build the index for my project. use XRAY tools"

2. **Explore the tools**:
   - `build_index` - Visual file tree of your repository
   - `find_symbol` - Fuzzy search for functions, classes, and methods
   - `what_breaks` - Find what code depends on a symbol (reverse dependencies)
   - `what_depends` - Find what a symbol depends on (calls and imports)
   
   Note: Results may include matches from comments or strings. The AI assistant will intelligently filter based on context.

3. **Read the documentation**: Check out the [README](README.md) for detailed examples and API reference

## Why XRAY Uses a Minimal Dependency Approach

XRAY is designed for simplicity and ease of use. It relies on:

- **ast-grep**: A powerful and fast single-binary tool for code analysis.
- **Python**: For its robust standard library and ease of scripting.

This approach avoids the complexity of setting up and managing multiple language servers, while still providing accurate, structural code intelligence.

## Benefits of Using uv

- **10-100x faster** than pip for installations
- **No virtual environment hassles** - uv manages everything
- **Reproducible installs** - uv.lock ensures consistency
- **Built-in Python management** - install any Python version
- **Global tool management** - like pipx but faster

Happy coding with XRAY! 🚀
