#!/usr/bin/env bash
# Work out what the onboard LED is wired to.
#
# Run this while watching the board. It walks four phases, announcing each on
# stdout as it happens, then asks what you saw. Nothing is written to config --
# it only probes.
#
#   tools/led_probe.sh            probe GPIO48 as data, GPIO21 as gate
#   DATA=38 GATE=21 tools/...     probe other pins
set -euo pipefail
cd "$(dirname "$0")/.."

# Auto-detect: the node name changes when the board re-enumerates
# (usbmodem1101 vs usbmodem101), so do not hardcode it.
PORT="${PORT:-$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)}"
if [[ -z "$PORT" ]]; then echo "no /dev/cu.usbmodem* found - is the board plugged in?" >&2; exit 1; fi
MPR="${MPR:-.venv/bin/mpremote}"
DATA="${DATA:-48}"
GATE="${GATE:-21}"

cat <<EOF
=== LED probe ===
Watch the board. Four phases, about 10 seconds each:

  A  GPIO$GATE HIGH, blinking WS2812 data on GPIO$DATA
  B  GPIO$GATE LOW,  blinking WS2812 data on GPIO$DATA
  C  GPIO$DATA idle, plain on/off toggle of GPIO$GATE
  D  everything driven low (LED should end dark)

Starting in 3 seconds...
EOF
sleep 3

"$MPR" connect "$PORT" exec "
import time, machine, neopixel

DATA = $DATA
GATE = $GATE

gate = machine.Pin(GATE, machine.Pin.OUT, value=0)
np = neopixel.NeoPixel(machine.Pin(DATA, machine.Pin.OUT, value=0), 1)

def blink(n, ms):
    for _ in range(n):
        np[0] = (0, 0, 160); np.write(); time.sleep_ms(ms)
        np[0] = (0, 0, 0);   np.write(); time.sleep_ms(ms)

print('A: GATE(%d) HIGH + data blink on %d' % (GATE, DATA))
gate.value(1); blink(10, 500)

print('B: GATE(%d) LOW + data blink on %d' % (GATE, DATA))
gate.value(0); blink(10, 500)

print('C: plain toggle of GATE(%d), data idle' % GATE)
np[0] = (0, 0, 0); np.write()
for _ in range(10):
    gate.value(1); time.sleep_ms(500)
    gate.value(0); time.sleep_ms(500)

print('D: all low')
gate.value(0)
for _ in range(2):
    np[0] = (0, 0, 0); np.write(); time.sleep_ms(2)
print('done')
"

cat <<'EOF'

=== what did you see? ===
  A and B both blinked   -> GATE pin is unrelated; keep led_pin as the data pin.
  only A blinked         -> GATE is a power/enable line and must be held HIGH.
  only C blinked         -> GATE drives a plain (non-addressable) LED.
  nothing blinked        -> wrong data pin; retry with DATA=38 or DATA=21.
  LED lit after D        -> tell me; the off write is not latching.
EOF
