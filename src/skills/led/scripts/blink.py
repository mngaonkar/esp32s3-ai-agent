# Blink the onboard user LED without a model round trip per flash.
# args: times, on_ms, off_ms
import time

pin_no = cfg.get("led_pin")
if pin_no is None:
    result = {"error": "led_pin is not configured"}
else:
    active_low = cfg.get("led_active_low", True)
    on_level = 0 if active_low else 1
    off_level = 1 - on_level

    led = machine.Pin(int(pin_no), machine.Pin.OUT, value=off_level)

    times = max(1, min(20, int(args.get("times", 3))))
    on_ms = max(20, min(2000, int(args.get("on_ms", 200))))
    off_ms = max(20, min(2000, int(args.get("off_ms", 200))))

    for _ in range(times):
        led.value(on_level)
        time.sleep_ms(on_ms)
        led.value(off_level)
        time.sleep_ms(off_ms)

    print("blinked %d times on GPIO%s" % (times, pin_no))
    result = {"blinks": times, "pin": pin_no, "final_state": "off"}
