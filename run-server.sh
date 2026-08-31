#!/bin/sh
# Launcher for MCP Inspector / any MCP host.
# Resolves everything to absolute paths so it works regardless of the host's
# working directory or PATH (GUI-launched hosts get a minimal PATH).

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# --- workshop settings ----------------------------------------------------
# Edit these here: MCP hosts sanitize the environment before spawning the
# server, so variables exported in your own shell do NOT reach it.

export MCP_DEMO_LOG="${MCP_DEMO_LOG:-$DIR/mcp-demo.log}"
export MCP_DEMO_LOG_PAYLOAD="${MCP_DEMO_LOG_PAYLOAD:-full}"   # full | compact | none
export MCP_DEMO_LOG_TRUNCATE="${MCP_DEMO_LOG_TRUNCATE:-0}"     # 1 = fresh logfile on every run
export MCP_DEMO_LOG_STDERR="${MCP_DEMO_LOG_STDERR:-headers}"   # headers | full | off
                                                               # -> mirrored to the Inspector's server console
# --------------------------------------------------------------------------

for candidate in /opt/homebrew/bin/uv /usr/local/bin/uv "$HOME/.local/bin/uv" "$(command -v uv 2>/dev/null)"; do
    if [ -x "$candidate" ]; then
        UV="$candidate"
        break
    fi
done

if [ -z "$UV" ]; then
    echo "run-server.sh: could not find 'uv' -- install it or edit this script." >&2
    exit 127
fi

exec "$UV" run --quiet "$DIR/server.py"
