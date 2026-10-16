#!/usr/bin/env bash
# XRAY MCP server installer.
# Usage: curl -fsSL https://raw.githubusercontent.com/srijanshukla18/xray/main/install.sh | bash
#    or: ./install.sh   (from a clone, installs that checkout)

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if ! command -v uv &>/dev/null; then
    if [[ "${OSTYPE:-}" == msys* || "${OSTYPE:-}" == cygwin* ]]; then
        echo -e "${RED}✗${NC} Install uv first: powershell -c \"irm https://astral.sh/uv/install.ps1 | iex\""
        exit 1
    fi
    echo -e "${YELLOW}→${NC} Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
echo -e "${GREEN}✓${NC} uv $(uv --version | cut -d' ' -f2)"

# Install the checkout this script lives in, if run from one; otherwise from GitHub.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/pyproject.toml" ]] && grep -q '^name = "xray"' "$SCRIPT_DIR/pyproject.toml"; then
    SOURCE="$SCRIPT_DIR"
else
    SOURCE="git+https://github.com/srijanshukla18/xray"
fi

echo -e "${YELLOW}→${NC} Installing XRAY from $SOURCE..."
uv tool install --force --reinstall "$SOURCE"
uv tool update-shell >/dev/null 2>&1 || true
export PATH="$HOME/.local/bin:$PATH"

if ! command -v xray-mcp &>/dev/null; then
    echo -e "${RED}✗${NC} xray-mcp is not on PATH. Open a new shell, or add ~/.local/bin to PATH."
    exit 1
fi

echo -e "${GREEN}✓${NC} XRAY installed: $(command -v xray-mcp)"
echo
echo "Register it with your MCP client:"
echo "  Claude Code:  claude mcp add xray -s user -- xray-mcp"
echo "  Others:       {\"mcpServers\": {\"xray\": {\"command\": \"xray-mcp\"}}}"
