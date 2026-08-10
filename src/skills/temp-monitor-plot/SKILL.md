---
name: temp-monitor-plot
description: Sample the ESP32-S3 MCU die temperature over a period (default 60s),
  save a CSV log, and print a simple text plot of the trace. Use when the user
  asks to monitor MCU temperature for a minute, log die temperature over time,
  capture a temperature trace, or plot chip temperature.
version: 1.1.0
---

# MCU temperature monitor + text plot

Samples **die temperature** (`esp32.mcu_temperature`), not ambient room temp.
Normal under WiFi load is often ~40–60 C.

## Run it

Prefer the bundled script (one tool round, accurate timing):

    run_script("/skills/temp-monitor-plot/scripts/log_temp.py",
               {"seconds": 60, "interval_ms": 1000})

Optional args:

| arg | default | meaning |
|-----|---------|---------|
| `seconds` | 60 | total duration (capped at 300) |
| `interval_ms` | 1000 | time between samples (min 200) |
| `csv_path` | `/tmp/mcu_temp.csv` | where to write CSV |
| `plot_path` | `/tmp/mcu_temp_plot.txt` | text plot file |

Do **not** call `board_status` once per second from the model — that wastes
dozens of LLM rounds. Always use the script.

## What you get

- CSV: `elapsed_s,temperature_c`
- Text plot: ASCII sparkline-style chart of the same samples
- `result` dict: min/max/avg, sample count, paths

Report min, max, average, paths, and paste the plot in a fenced code block.
For a richer redraw of an existing CSV, load the `tui-plot` skill and run
`plot_csv.py` on the CSV path.

If the user wants a PNG or interactive GUI chart, say the board only does
text/TUI plots; they can copy the CSV to a host for a full graph.

## Trigger examples

- "Monitor MCU temperature for 1 minute"
- "Log die temp for 30 seconds and plot it"
- "Temperature trace while idle"
