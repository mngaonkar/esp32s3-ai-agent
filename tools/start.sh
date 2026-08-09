#!/usr/bin/env bash
# Start the agent detached on the board and report its web address.
#
# Resets the board, which makes MicroPython auto-run /main.py. The agent then
# runs on its own -- no host process attached -- so you can unplug USB and it
# keeps serving. This script only watches the boot log long enough to print
# the URL, then exits.
set -euo pipefail

cd "$(dirname "$0")/.."

# Auto-detect: the node name changes when the board re-enumerates
# (usbmodem1101 vs usbmodem101), so do not hardcode it.
PORT="${PORT:-$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)}"
if [[ -z "$PORT" ]]; then echo "no /dev/cu.usbmodem* found - is the board plugged in?" >&2; exit 1; fi
MPR="${MPR:-.venv/bin/mpremote}"

echo "==> resetting $PORT to start the agent"
"$MPR" connect "$PORT" reset >/dev/null 2>&1 || true
sleep 2

.venv/bin/python - "$PORT" <<'PY'
import re
import sys
import time

import serial

port = sys.argv[1]
deadline = time.time() + 40
text = ""

# The port re-enumerates after a reset; retry until it comes back.
ser = None
while time.time() < deadline and ser is None:
    try:
        ser = serial.Serial(port, 115200, timeout=1)
    except Exception:
        time.sleep(0.5)

if ser is None:
    print("!! could not reopen %s" % port)
    raise SystemExit(1)

while time.time() < deadline:
    try:
        text += ser.read(4096).decode("utf-8", "replace")
    except Exception:
        break
    if "web chat at" in text or "no network" in text:
        break

ser.close()

for line in text.splitlines():
    if any(k in line for k in ("[wifi]", "[boot]", "[skills]")):
        print("   " + line.strip())

match = re.search(r"web chat at (http://\S+)", text)
if match:
    print("\n==> agent running detached. Web chat: %s" % match.group(1))
    print("    Serial chat: tools/console.sh   (Ctrl-] to detach)")
else:
    print("\n!! agent did not report a web address; check tools/console.sh")
PY
