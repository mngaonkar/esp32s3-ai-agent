# Sample MCU die temperature, write CSV + text plot.
# args: seconds, interval_ms, csv_path, plot_path
import time

try:
    import esp32
except ImportError:
    result = {"error": "esp32.mcu_temperature not available on this build"}
    print(result["error"])
else:
    seconds = float(args.get("seconds", 60))
    interval_ms = int(args.get("interval_ms", 1000))
    csv_path = args.get("csv_path") or "/tmp/mcu_temp.csv"
    plot_path = args.get("plot_path") or "/tmp/mcu_temp_plot.txt"

    if seconds <= 0:
        seconds = 60
    if seconds > 300:
        seconds = 300
    if interval_ms < 200:
        interval_ms = 200

    n = max(2, int(seconds * 1000 / interval_ms) + 1)
    samples = []  # (elapsed_s, temp_c)
    t0 = time.ticks_ms()

    print("sampling %d points over ~%gs (interval %d ms)" % (n, seconds, interval_ms))
    for i in range(n):
        elapsed = time.ticks_diff(time.ticks_ms(), t0) / 1000.0
        try:
            temp = round(esp32.mcu_temperature(), 2)
        except Exception as exc:
            result = {"error": "mcu_temperature failed: %s" % exc}
            print(result["error"])
            samples = None
            break
        samples.append((round(elapsed, 2), temp))
        print("t=%.1fs  temp=%.2f C" % (elapsed, temp))
        if i + 1 < n:
            # stay close to wall-clock interval
            target = t0 + (i + 1) * interval_ms
            delay = time.ticks_diff(target, time.ticks_ms())
            if delay > 0:
                time.sleep_ms(delay)

    if samples:
        # parents under /tmp
        for path in (csv_path, plot_path):
            if "/" in path:
                parent = path.rsplit("/", 1)[0]
                if parent and parent != "/":
                    try:
                        import os
                        parts = [p for p in parent.split("/") if p]
                        cur = ""
                        for p in parts:
                            cur += "/" + p
                            try:
                                os.mkdir(cur)
                            except OSError:
                                pass
                    except Exception:
                        pass

        with open(csv_path, "w") as f:
            f.write("elapsed_s,temperature_c\n")
            for el, te in samples:
                f.write("%s,%s\n" % (el, te))

        temps = [t for _, t in samples]
        tmin = min(temps)
        tmax = max(temps)
        tavg = round(sum(temps) / len(temps), 2)
        span = tmax - tmin if tmax != tmin else 1.0

        # text plot: 40 cols wide, one row per sample (or thinned)
        width = 40
        max_rows = 40
        step = max(1, (len(samples) + max_rows - 1) // max_rows)
        lines = []
        lines.append("MCU die temp (C)  min=%s max=%s avg=%s" % (tmin, tmax, tavg))
        lines.append("each * is a sample; x-axis is relative within min..max")
        lines.append("min" + "-" * (width - 6) + "max")
        for i in range(0, len(samples), step):
            el, te = samples[i]
            pos = int(round((te - tmin) / span * (width - 1)))
            row = [" "] * width
            row[pos] = "*"
            lines.append("%6.1fs |%s| %.2f" % (el, "".join(row), te))
        lines.append("CSV: %s" % csv_path)
        plot_text = "\n".join(lines)

        with open(plot_path, "w") as f:
            f.write(plot_text)
            f.write("\n")

        print(plot_text)
        result = {
            "samples": len(samples),
            "seconds": round(samples[-1][0], 2),
            "min_c": tmin,
            "max_c": tmax,
            "avg_c": tavg,
            "csv_path": csv_path,
            "plot_path": plot_path,
        }
