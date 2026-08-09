# Sample free heap over time to distinguish a leak from normal churn.
# args: {"samples": int (default 5), "interval_ms": int (default 500)}
import gc
import time

samples = int(args.get("samples", 5))
interval = int(args.get("interval_ms", 500))

readings = []
for i in range(max(2, min(samples, 20))):
    gc.collect()
    readings.append(gc.mem_free())
    if i < samples - 1:
        time.sleep_ms(interval)

drift = readings[-1] - readings[0]
print("samples (bytes free): %s" % readings)
print("drift over window   : %+d bytes" % drift)

result = {
    "readings": readings,
    "drift_bytes": drift,
    "min_free": min(readings),
    "verdict": "leaking" if drift < -20000 else "stable",
}
