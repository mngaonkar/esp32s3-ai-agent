# Text-mode chart from a CSV file.
# args: path, x_col, y_col, title, height, width, style (bars|line|both), out_path
import os

path = args.get("path") or "/tmp/mcu_temp.csv"
x_col = int(args.get("x_col", 0))
y_col = int(args.get("y_col", 1))
title = args.get("title") or "plot"
height = int(args.get("height", 12))
width = int(args.get("width", 48))
style = (args.get("style") or "both").lower()
out_path = args.get("out_path")  # optional

if height < 4:
    height = 4
if height > 30:
    height = 30
if width < 16:
    width = 16
if width > 72:
    width = 72

BLOCKS = " ▁▂▃▄▅▆▇█"


def _load_csv(p):
    rows = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) <= max(x_col, y_col):
                continue
            try:
                x = float(parts[x_col])
                y = float(parts[y_col])
            except ValueError:
                continue  # header or junk
            rows.append((x, y))
    return rows


try:
    series = _load_csv(path)
except OSError as exc:
    result = {"error": "cannot read %s: %s" % (path, exc)}
    print(result["error"])
else:
    if len(series) < 2:
        result = {"error": "need at least 2 numeric rows in %s" % path}
        print(result["error"])
    else:
        # downsample to width columns
        n = len(series)
        cols = []
        for c in range(width):
            i0 = int(c * n / width)
            i1 = max(i0 + 1, int((c + 1) * n / width))
            chunk = series[i0:i1]
            ys = [y for _, y in chunk]
            cols.append(sum(ys) / len(ys))

        ymin = min(cols)
        ymax = max(cols)
        span = ymax - ymin if ymax != ymin else 1.0

        lines = []
        lines.append("%s  (n=%d from %s)" % (title, n, path))
        lines.append("min=%.3g  max=%.3g  avg=%.3g" % (
            min(y for _, y in series),
            max(y for _, y in series),
            sum(y for _, y in series) / n,
        ))

        if style in ("bars", "both"):
            # one row of vertical bar characters
            bar = []
            for v in cols:
                # 0..8 index into BLOCKS
                lvl = int(round((v - ymin) / span * 8))
                if lvl < 0:
                    lvl = 0
                if lvl > 8:
                    lvl = 8
                bar.append(BLOCKS[lvl])
            lines.append("bars: " + "".join(bar))

        if style in ("line", "both"):
            # height rows, y axis up
            grid = [[" " for _ in range(width)] for _ in range(height)]
            for c, v in enumerate(cols):
                row = int(round((v - ymin) / span * (height - 1)))
                r = height - 1 - row
                grid[r][c] = "*"
            # connect simple vertical gaps
            prev = None
            for c, v in enumerate(cols):
                row = height - 1 - int(round((v - ymin) / span * (height - 1)))
                if prev is not None:
                    r0, r1 = prev, row
                    if r0 > r1:
                        r0, r1 = r1, r0
                    for r in range(r0, r1 + 1):
                        if grid[r][c] == " ":
                            grid[r][c] = "·"
                prev = row
            # axis labels
            lines.append("%8.2f ┤" % ymax + "".join(grid[0]))
            for r in range(1, height - 1):
                lines.append("         │" + "".join(grid[r]))
            lines.append("%8.2f ┤" % ymin + "".join(grid[height - 1]))
            x0, x1 = series[0][0], series[-1][0]
            lines.append("         └" + "─" * width)
            lines.append("          %g" % x0 + " " * max(1, width - 12) + "%g" % x1)

        plot = "\n".join(lines)
        print(plot)

        if out_path:
            parent = out_path.rsplit("/", 1)[0]
            if parent and parent != "/":
                parts = [p for p in parent.split("/") if p]
                cur = ""
                for p in parts:
                    cur += "/" + p
                    try:
                        os.mkdir(cur)
                    except OSError:
                        pass
            with open(out_path, "w") as f:
                f.write(plot)
                f.write("\n")

        result = {
            "path": path,
            "points": n,
            "min": min(y for _, y in series),
            "max": max(y for _, y in series),
            "avg": sum(y for _, y in series) / n,
            "style": style,
            "out_path": out_path,
        }
