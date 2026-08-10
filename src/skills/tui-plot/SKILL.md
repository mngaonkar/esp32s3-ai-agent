---
name: tui-plot
description: Draw text-mode (TUI-style) charts on the board using block
  characters from CSV files or numeric series. Use when the user asks for a
  terminal graph, ASCII/Unicode plot, text chart, sparkline, or to visualize
  a CSV under /tmp without a real GUI.
version: 1.0.0
---

# Text-mode (TUI) graphs on this board

This board has **no graphical GUI library** (no matplotlib, no framebuffer
chart API for the web page). What it *can* do is **TUI-style plots**: charts
made of monospaced characters that look fine in:

- the serial console
- the web chat (monospace bubbles)
- any host terminal that pastes the tool output

That is "TUI drawing" in the practical sense for MicroPython on ESP32.

## What is *not* available on-device

| Want | On this agent |
|------|----------------|
| ncurses / full-screen TUI | No (`curses` not on MicroPython) |
| Interactive mouse TUI | No |
| PNG/SVG chart files | Not by default (heavy); prefer text |
| Host GUI window | Needs a program on the laptop, not a skill alone |

For interactive host TUIs, copy CSV off the board and use something like
`plotext` or `rich` on the computer. This skill covers **on-board** text graphs.

## How to plot

### From a CSV (common after temp-monitor-plot)

    run_script("/skills/tui-plot/scripts/plot_csv.py", {
        "path": "/tmp/mcu_temp.csv",
        "x_col": 0,
        "y_col": 1,
        "title": "MCU temp C",
        "height": 12,
        "width": 48,
        "style": "bars"   // or "line" or "both"
    })

CSV may have a header row; the script skips non-numeric first lines.

### Styles

- `bars` — vertical bars with block chars (`▁▂▃▄▅▆▇█`)
- `line` — polyline with `·` / `*` on a grid
- `both` — bars plus a min/max summary line

### After temp monitoring

1. Load `temp-monitor-plot` and run its logger, **or**
2. If `/tmp/mcu_temp.csv` already exists, call `tui-plot` on that path.

Do not re-sample temperature in this skill unless the user only asked to re-draw
an existing CSV.

## Reporting

Paste the script output (or the plot file if written) into your reply inside a
fenced code block so alignment is preserved. Mention min/max/avg when present
in `result`.

## Limits

- Width/height stay small so chat and serial stay readable (defaults ~48×12).
- Long series are downsampled; detail is approximate.
- Unicode block characters need a font that has them (most modern UIs do).
