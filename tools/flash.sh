#!/usr/bin/env bash
# Flash the prebuilt agent image onto a board.
#
#   tools/flash.sh                    flash the newest image in dist/
#   tools/flash.sh path/to/image.bin  flash a specific one
#
# The board must be in ROM download mode first:
#   hold BOOT, tap RESET (or replug USB), keep BOOT held ~3s, release.
# It is in download mode when it shows up as "USB JTAG_serial debug unit".
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)}"
if [[ -z "$PORT" ]]; then echo "no /dev/cu.usbmodem* found - is the board plugged in?" >&2; exit 1; fi
ESPTOOL="${ESPTOOL:-.venv/bin/esptool}"

IMAGE="${1:-}"
if [[ -z "$IMAGE" ]]; then
  IMAGE=$(ls -t dist/esp32s3-agent-*.bin 2>/dev/null | head -1 || true)
fi
if [[ -z "$IMAGE" || ! -f "$IMAGE" ]]; then
  echo "no image found. Build one with: .venv/bin/python tools/build_image.py" >&2
  exit 1
fi

echo "==> image: $IMAGE ($(du -h "$IMAGE" | cut -f1))"
echo "==> port : $PORT"

if ! "$ESPTOOL" --port "$PORT" --connect-attempts 2 chip-id >/dev/null 2>&1; then
  cat >&2 <<'EOF'
!! Cannot reach the ROM bootloader.

   Put the board in download mode and try again:
     1. hold BOOT
     2. tap RESET, or unplug and replug USB
     3. keep BOOT held ~3 seconds, then release

   Check with:
     ioreg -p IOUSB -l -w 0 | grep -E '"(idProduct|USB Product Name)"'
   Download mode reports "USB JTAG_serial debug unit" (0x1001).
EOF
  exit 1
fi

echo "--> erasing"
"$ESPTOOL" --port "$PORT" --baud 921600 erase-flash >/dev/null

echo "--> writing"
"$ESPTOOL" --port "$PORT" --baud 921600 write-flash -z 0x0 "$IMAGE"

cat <<'EOF'

==> done.

Now power-cycle the board WITHOUT holding BOOT (unplug, wait 5s, replug),
then attach the console to finish setup:

    tools/console.sh

It will ask for your WiFi name, WiFi password and API key, then print the
web chat address.
EOF
