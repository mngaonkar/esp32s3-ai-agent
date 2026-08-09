---
name: sysinfo
description: Report or diagnose the board's own health - free heap and PSRAM, filesystem usage, CPU frequency and temperature, uptime, WiFi signal strength and MAC address. Use when the user asks how the board is doing, whether it is running out of memory, how strong the WiFi is, or for any hardware status report.
version: 1.0.0
---

# Board diagnostics

## Getting the numbers

Call `board_status` for the full snapshot. Every field is a raw number, so
convert before presenting: bytes to KB/MB, `uptime_s` to minutes or hours.

For a trend rather than a snapshot -- "is memory leaking?" -- run
`scripts/heap_watch.py` with `run_script`, passing `{"samples": 5, "interval_ms": 400}`.
It samples the heap repeatedly and reports the delta.

## Reading the results

This board is an ESP32-S3 with 8 MB of octal PSRAM, so `heap_free` is normally
in the millions of bytes. Judge against that baseline:

- **above ~4 MB free** - healthy, say so plainly and stop.
- **500 KB to 4 MB** - fine, but worth mentioning if the user asked about memory.
- **below ~200 KB** - genuinely low. Suggest `/reset` in the console to clear
  conversation history, which is the largest reclaimable allocation.

`mcu_temp_c` is the internal die temperature, not ambient. It reads well above
room temperature by design; 40-60 C is normal under WiFi load. Do not report it
as a room thermometer.

`wifi_rssi` is in dBm and always negative. Closer to zero is stronger:
-30 to -50 excellent, -50 to -67 good, -67 to -75 weak, below -80 unusable.
If the user is diagnosing dropouts and RSSI is below -75, say the signal is the
likely cause before suggesting anything else.

## Reporting

Lead with the answer to what was actually asked, then at most two or three
supporting numbers. Do not dump the whole JSON blob unless asked for everything.
