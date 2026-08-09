---
name: led
description: Control the board's onboard user LED and arbitrary GPIO pins - turn the light on or off, blink it a number of times, or pulse it as a visual notification, and drive any GPIO high or low. Use for any request about the light, the LED, blinking, or setting a pin.
version: 2.0.0
---

# Onboard user LED and GPIO control

## The LED on this board

This is a **Seeed XIAO ESP32S3 Sense**. Its user LED is a single yellow LED on
**GPIO21**, wired **active-LOW** — driving the pin low lights it. It is not an
addressable RGB LED and has no colour.

If the user asks for a colour ("turn the LED blue"), turn it on and tell them
plainly that this board's LED is single-colour. Do not silently pretend the
colour was applied.

The pin comes from `cfg["led_pin"]` and the polarity from
`cfg["led_active_low"]`. Read those; never hardcode a pin number, and never use
the `neopixel` driver here — it rests the line low between frames, which on an
active-low LED means permanently on.

## Turning it on and off

`led_set` takes `state`: `true` for on, `false` for off. That is the whole
interface.

## Blinking and patterns

Anything with timing must go through `run_script`, because each `led_set` call
costs a full model round trip — far too slow for a blink and wasteful of
tokens. Use `scripts/blink.py`:

    run_script("/skills/led/scripts/blink.py",
               {"times": 3, "on_ms": 200, "off_ms": 200})

It leaves the LED off when it finishes and caps at 20 blinks so a runaway
pattern cannot lock up the agent loop.

## Raw GPIO

`gpio_write` drives any pin high or low for relays, external LEDs or logic
lines. Confirm the pin number back to the user before acting.

Be careful which pin you touch on this board — many are already in use:

| Pins | Used by |
|---|---|
| 10, 39, 40, 13, 38, 47, 48, 11, 12, 14, 16, 18, 17, 15 | camera (XCLK, SCCB, PCLK, VSYNC, HREF, data) |
| 41, 42 | microphone (I2S) |
| 7, 8, 9, 21 | SD card (and 21 is the LED) |

Driving a camera or microphone pin can disturb that peripheral. If a user asks
for one of these, say what it is wired to first.
