#!/usr/bin/env bash
# Attach to the agent's serial chat console.
#
# The agent is already running on the board (see tools/start.sh); this just
# joins its console. Type a message and press enter.
#
#   Ctrl-]   detach and leave the agent running
#   Ctrl-C   INTERRUPT the agent -- it stops and the web server goes down.
#            Run tools/start.sh to bring it back.
set -euo pipefail
cd "$(dirname "$0")/.."
# Auto-detect: the node name changes when the board re-enumerates
# (usbmodem1101 vs usbmodem101), so do not hardcode it.
PORT="${PORT:-$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)}"
if [[ -z "$PORT" ]]; then echo "no /dev/cu.usbmodem* found - is the board plugged in?" >&2; exit 1; fi
echo "attaching to $PORT -- Ctrl-] to detach, Ctrl-C stops the agent"
exec "${MPR:-.venv/bin/mpremote}" connect "$PORT" repl
