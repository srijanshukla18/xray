#!/usr/bin/env bash
# XRAY MCP server uninstaller. Usage: bash uninstall.sh

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if command -v uv &>/dev/null && uv tool uninstall xray 2>/dev/null; then
    echo -e "${GREEN}✓${NC} Removed the xray uv tool"
else
    echo -e "${YELLOW}!${NC} xray uv tool was not installed"
fi

CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/xray"
for dir in "$CACHE_DIR" "$HOME/.xray" "/tmp/.xray_cache"; do  # last two: pre-0.7 install/cache locations
    if [[ -d "$dir" ]]; then
        rm -rf "$dir"
        echo -e "${GREEN}✓${NC} Removed $dir"
    fi
done

if command -v xray-mcp &>/dev/null; then
    echo -e "${YELLOW}!${NC} xray-mcp is still on PATH at $(command -v xray-mcp) (installed some other way?)"
else
    echo -e "${GREEN}✓${NC} Uninstalled. Remove xray from your MCP client config too."
fi
