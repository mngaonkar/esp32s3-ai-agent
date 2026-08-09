---
name: websearch
description: Look things up on the live internet with Tavily - current events, news, weather, prices, product specs, datasheets, pinouts, library documentation, or any fact that may have changed since training. Use whenever the user asks about something recent, something external to this board, or anything you are not confident is still accurate.
version: 1.0.0
---

# Web search

## When to search

Search when the answer depends on the outside world or on anything that may
have changed: news, weather, prices, releases, versions, datasheets, pinouts,
API documentation. Also search when you are simply unsure — a wrong confident
answer about a pin number can damage hardware.

Do **not** search for things the board already knows about itself. Heap,
temperature, WiFi signal, uptime and the filesystem come from the `sysinfo`
and `netscan` skills. Searching for those wastes several seconds of radio time
and returns worse information than the hardware itself.

## Running a search

`web_search` takes a `query` and optionally `max_results` (1-10, default 5),
`topic`, and `days`.

Write queries as keywords, not as the user's sentence. "ESP32-S3 GPIO48
neopixel voltage" beats "can you tell me what voltage the neopixel on my
board's pin 48 wants?".

For recent events pass `topic: "news"`, optionally with `days` to bound the
window:

    web_search(query="esp32 security advisory", topic="news", days=30)

Each search takes roughly two to five seconds. Prefer one well-chosen query
over several narrow ones, and raise `max_results` rather than searching again
with a slightly different phrasing.

## Reading the results

The response has an `Answer:` line — Tavily's own synthesis — followed by
numbered sources with URLs and snippets.

Treat the `Answer` as a starting point, not as verified truth. When the
snippets disagree with it, trust the snippets and say so. When sources
disagree with each other, report the disagreement rather than silently
choosing one.

Snippets are truncated. If a snippet is clearly cut off mid-fact and the
detail matters, fetch that one URL with `http_get` to read more.

## Reporting

Answer the question first in your own words, then cite which source it came
from — the site name is enough, with the URL only if the user would need it.
Do not paste the raw result block back to the user.

If the search returns nothing useful, say so plainly and say what you tried.
Do not fall back to guessing from memory while implying it came from the web.

## Hardware lookups

This board is an **ESP32-S3** with 8 MB octal PSRAM running MicroPython. When
looking up pinouts, peripherals or library APIs, include "ESP32-S3" and
"MicroPython" in the query — ESP32, ESP32-C3 and Arduino answers are common
and frequently wrong for this board.

Before acting on a pin number found online, confirm it against the board's own
configuration where possible; `cfg["led_pin"]` is authoritative for the LED,
not a datasheet for a similar-looking devkit.
