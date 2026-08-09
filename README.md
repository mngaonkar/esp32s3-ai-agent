# esp32s3-agent

An AI agent that runs **on** an ESP32-S3, not on a host talking to one. It calls
an OpenAI-compatible endpoint for inference, executes tool calls against its own
hardware, and is extended at runtime with **Anthropic-style Skills** written to
its filesystem — no reflash to add a capability.

Written in MicroPython so a skill is a text file you copy over USB.

## Hardware

**Seeed XIAO ESP32S3 Sense**, identified from the vendor firmware's own board
definition:

| | |
|---|---|
| MCU | ESP32-S3 (QFN56) rev v0.2, dual core @ 240 MHz |
| PSRAM | 8 MB embedded octal (AP, 3V3) |
| Flash | 8 MB quad |
| USB | native USB-Serial/JTAG |
| Camera | **OV3660** on the Sense board — SCCB `0x3C`, chip id `0x3660` |
| User LED | single yellow LED on **GPIO21**, **active-LOW** (not addressable) |
| Microphone | I2S on GPIO41/42 |
| SD slot | SPI on GPIO7/8/9/21 |
| MAC | `10:b4:1d:e9:06:c4` |

Firmware: **[micropython-camera-API](https://github.com/cnadler86/micropython-camera-API)
v0.6.2** (MicroPython v1.27.0, `ESP32_GENERIC_S3-SPIRAM_OCT`).

Two hardware notes that cost real debugging time, both verified:

- The camera is an **OV3660, not the OV2640** this board usually ships with.
  Seeed's recommended MicroPython build compiles in an OV2640-only detection
  path and rejects this sensor outright, which is also why the vendor firmware
  logged `Failed to detect camera sensor with address=30`. The generic
  camera-API build detects it correctly.
- The LED is a **plain active-LOW LED**, not a WS2812. Driving it with the
  neopixel driver leaves the line resting low, which on an active-low LED means
  permanently *on*. GPIO48 is a camera data pin, not an LED.

The octal PSRAM is what makes this practical: **~8.3 MB of free heap**, so
conversation history, TLS buffers and JSON payloads are never the constraint.
Filesystem is 6 MB.

### The microphone cannot be used from MicroPython

The Sense board's mic is a **PDM** microphone, and `machine.I2S` implements
only standard I2S. From the `machine.I2S` maintainer:

> "The PDM protocol is not supported by MicroPython. It is not possible to use
> the `machine.I2S` class with a PDM microphone."
> — [micropython discussion #16048](https://github.com/orgs/micropython/discussions/16048)

The ESP32-S3 *hardware* has a PDM-to-PCM converter on I2S0 and ESP-IDF exposes
it, but MicroPython does not; the docs list only `I2S.RX` and `I2S.TX`, and
[PR #14176](https://github.com/micropython/micropython/pull/14176), which adds
`PDM_RX`, was never merged.

Clocking the mic with a standard I2S receiver *does* return data, and it is
tempting to decimate that bitstream in software. It does not work: a standard
I2S receiver cannot align to PDM framing, so the output is noise with only
weak correlation to sound, and no amount of filtering fixes it.
`agent/audio.py` keeps that attempt for reference with `audio_enabled`
defaulting to `False`, so the agent advertises no recording tools.

To record audio you would need to build MicroPython with PR #14176 applied,
or use ESP-IDF/Arduino, or CircuitPython (`audiobusio.PDMIn`).

## Quick start

Flash one image, answer three questions, done. No file copying, no per-file
tooling.

```bash
python3 -m venv .venv && .venv/bin/pip install esptool mpremote

# 1. put the board in download mode:
#    hold BOOT, tap RESET (or replug USB), keep BOOT held ~3s, release
tools/flash.sh

# 2. power-cycle WITHOUT holding BOOT (unplug, wait 5s, replug)

# 3. finish setup over the console
tools/console.sh
```

On first boot the board has no configuration, so it asks for the only things
it cannot work out for itself:

```
==============================================
  First-time setup
==============================================
WiFi network name: silverblaze
WiFi password: ********
OpenAI API key: ********

Optional -- press Enter to skip:
Model [gpt-4o-mini]:
Tavily API key (enables web search):

Saved to /config.json. Starting the agent...

[wifi] connected, ip=10.0.0.172 rssi=-50
[skills] loaded 6: camera, led, netscan, sysinfo, websearch, write-skill
[boot] web chat at http://10.0.0.172:80/
```

**Three answers are required** — network, password, API key. Everything else
has a working default and can be changed later in the web **Config** screen,
so setup stays short enough that nobody skips it.

Then open the printed address. Note that first boot needs a serial console
attached, since that is where the questions are asked.

### Building the image yourself

`dist/` ships a prebuilt image; rebuild it after changing any agent code:

```bash
.venv/bin/python tools/build_image.py
```

It packs `src/` and `certs/` into a littlefs filesystem, verifies every file
re-reads byte-identical, and merges it with the MicroPython firmware into one
8 MB image flashable at offset 0. **`config.json` is deliberately excluded**,
so the image carries no credentials and is safe to share — a new board runs
first-boot setup instead.

## Developing

For iterating on the agent, push individual files over USB instead of
reflashing:

```bash
python3 -m venv .venv && .venv/bin/pip install esptool mpremote

cp config.example.json config.json     # fill in wifi + api_key (+ tavily_api_key)
tools/deploy.sh --config               # push code, skills, certs and config
tools/deploy.sh                        # code only, leaves config.json alone
```

`config.json` is gitignored and is only pushed when you pass `--config`, so
credentials never ride along with a routine code deploy.

## Running it

```bash
tools/start.sh      # start the agent; prints its web address
tools/console.sh    # optional: join the serial chat console
```

`start.sh` resets the board, which makes MicroPython auto-run `/main.py`. The
agent then runs **detached** — no host process attached, so you can close the
terminal or unplug USB from the computer and it keeps serving, as long as it
still has power.

```
==> resetting /dev/cu.usbmodem1101 to start the agent
   [wifi] connected, ip=10.0.0.172 rssi=-50
   [boot] clock synced
   [skills] loaded 6: camera, led, netscan, sysinfo, websearch, write-skill
   [boot] web chat at http://10.0.0.172:80/
```

It needs roughly 15–20 s after reset to associate, sync NTP and bind the
server.

**Stopping it.** `Ctrl-C` in the serial console interrupts `main.py` and drops
to the REPL — the web server goes down with it. Detach with **`Ctrl-]`**
instead to leave the agent running. `mpremote exec ...` also interrupts a
running agent, so re-run `tools/start.sh` afterwards.

If the web page does not load, the agent is almost certainly not running.
Check with `curl -m 5 -o /dev/null -w '%{http_code}\n' http://<board-ip>/`;
`000` means nothing is listening, and `tools/start.sh` fixes it.

## Using it

Two interfaces share one thread; whichever receives input first drives the
agent.

**Serial console**

```
> how's the board doing?
[tool] Skill {"name":"sysinfo"}
[tool] board_status {}
The board is doing well. It has been up for about 20 minutes, with 8.2 MB of
free heap memory, which is healthy. The WiFi signal strength is strong at
-46 dBm. The internal temperature is 50°C, which is normal under load.
(5.1s, heap free 8205584)
```

Commands: `/reset` clears history, `/skills` reindexes and lists,
`/info` dumps diagnostics, `/quit` drops to the REPL.

**Web chat** — open the address `start.sh` printed. Same agent, same skills,
same conversation history, usable from a phone on the same network.

The UI is a Matrix-style terminal: black ground, phosphor green (`#00ff41`),
monospace throughout, with a blinking cursor on the status line.

Replies are rendered as markdown: headings, **bold**, *italic*, `inline code`,
fenced code blocks, bullet and numbered lists, tables, links, rules and
blockquotes. The renderer is ~50 lines of JavaScript inlined in the page —
the board serves this on a LAN that may have no route to the internet, so a
CDN library is not an option. Model output is HTML-escaped before any markdown
is applied, so a reply containing `<script>` renders as text.

Both interfaces share one thread, so whichever gets input first drives the
agent; a request in flight blocks the other until it finishes.

## Settings screen

The **Config** tab in the web UI edits `/config.json` on the board — WiFi,
model and keys, search, agent limits, TLS, LED pin and web port — grouped and
validated.

Most changes apply **immediately**: saving rebuilds the LLM and Tavily clients
against the new values, and the agent loop reads prompt and iteration settings
from the live config object. Only `wifi_ssid`, `wifi_password` and `web_port`
need a reboot; those are labelled "requires restart" in the form, and a
**Restart board** button is provided. A save that mixes both kinds reports them
separately — "Applied now: … Restart required for: …" — rather than calling the
whole thing pending.

The field schema lives in `agent/settings.py`, not in the page's JavaScript, so
there is one definition of what is editable and what a legal value is. Bad
input is rejected per field with a message next to it, and **nothing is written
unless every field validates**, so a rejected form cannot half-apply.

**Secrets are never sent to the browser.** `api_key`, `tavily_api_key` and
`wifi_password` come back as empty with an `isSet` flag; the form shows
"•••• stored — leave blank to keep". Submitting a blank secret leaves the
stored value alone, so you can change the model without re-entering three keys.

> **The board's `config.json` becomes the source of truth.** Edits made in the
> web UI live only on the board — the repo copy does not change, and the two
> will drift. `tools/deploy.sh` alone never touches it, but
> `tools/deploy.sh --config` **overwrites the board's copy and discards those
> edits**. Pull the current values from `http://<board-ip>/api/config` before
> pushing config if you are unsure.

**Security.** The config screen is unauthenticated, like the chat. Anyone who
can reach the board on the network can change its settings — including pointing
`base_url` at another host. Withholding secrets from the browser limits the
damage, but treat this as a device for a trusted LAN, not one to expose.

## How skills work

A skill is a directory with a `SKILL.md` whose YAML frontmatter carries a
`name` and a `description`:

```
/skills/led/
    SKILL.md
    scripts/blink.py
```

```markdown
---
name: led
description: Control the board's onboard RGB LED and GPIO pins. Use for any
  request about the light, colours, or driving a pin high or low.
---

# Onboard LED control
...instructions the model follows...
```

Loading follows Anthropic's **progressive disclosure** model, which is what
makes a large skill library affordable on a microcontroller:

| Level | What loads | When |
|---|---|---|
| 1 | `name` + `description` only | always, in the system prompt |
| 2 | full `SKILL.md` body | when the model calls `Skill(name)` |
| 3 | bundled `scripts/`, `references/` | via `read_file` / `run_script` |

Only level 1 is resident. The four bundled skills cost **~313 tokens total**
at rest; their combined bodies are several thousand. Indexing reads only the
first 1536 bytes of each file, so a large skill body never enters RAM just to
be listed.

### Adding a skill

Drop a directory into `src/skills/` and run `tools/deploy.sh`. Or let the agent
write one itself — the `write-skill` skill teaches it the format, and
`write_file` reindexes the registry the moment a `SKILL.md` lands, so a new
skill is live for the very next message.

## Bundled skills

| Skill | Purpose |
|---|---|
| `sysinfo` | Heap/PSRAM, filesystem, die temp, RSSI, uptime. Includes `heap_watch.py` to distinguish a leak from churn. |
| `led` | Onboard RGB LED and raw GPIO, with a colour table and a `blink.py` for timed patterns. |
| `netscan` | AP survey, RSSI interpretation, and `channel_survey.py` which weights congestion by signal strength and recommends a non-overlapping channel. |
| `websearch` | Live web lookup via Tavily — when to search, how to phrase queries, and how to weigh Tavily's synthesised answer against its sources. |
| `write-skill` | How to author new skills. Lets the board extend itself at runtime. |

## Tools

`Skill`, `list_skills`, `list_dir`, `read_file`, `write_file`, `run_script`,
`board_status`, `wifi_scan`, `web_search`, `http_get`, `gpio_write`,
`led_set`.

`web_search` is registered only when `tavily_api_key` is set, so the model is
never offered a tool that is guaranteed to fail.

Skills supply *instructions*; tools supply *capability*. That split is why a new
skill needs no firmware change — it is new instructions over existing tools.

`run_script` executes a skill's bundled `.py` with `args`, `cfg`, `machine`,
`time` and `tool` in scope; it returns whatever the script prints plus its
`result` variable. Timed or looping hardware work belongs there rather than in
repeated tool calls, since each tool call is a full model round trip.

Scripts reuse existing capability through `tool(name, args)`:

```python
tool("led_set", {"r": 0, "g": 0, "b": 51})
```

That is deliberate. Without a supported way to call a tool from a script, models
invent one — `import led` — which raises at run time.

## Choosing a model

Using skills and driving hardware works fine on `gpt-4o-mini`. **Authoring**
skills needs `gpt-4o`: in testing, `gpt-4o-mini` repeatedly skipped the
`write-skill` skill and wrote malformed manifests and bare-`Pin` scripts, while
`gpt-4o` loaded `write-skill` first, checked `list_skills`, produced a valid
manifest, and reused the `led` skill's own blink script at the correct dimmed
brightness.

Skill authoring takes 8–10 tool rounds, which is why `max_tool_iterations`
defaults to 12.

## Layout

```
src/main.py              boot, then poll serial + web on one thread
src/agent/config.py      /config.json loading with defaults
src/agent/wifi.py        station bring-up, scan, RSSI
src/agent/httpc.py       HTTP/HTTPS client (chunked + Content-Length, CA verify)
src/agent/llm.py         OpenAI chat-completions client
src/agent/skills.py      frontmatter parser, registry, disclosure levels
src/agent/tools.py       tool schemas and handlers
src/agent/loop.py        agent loop: prompt -> tools -> observations -> answer
src/agent/web.py         non-blocking chat server + single-page UI
src/skills/<name>/       bundled skills
certs/openai_root.der    GTS Root R4, trust anchor for api.openai.com
```

## Implementation notes

**Why a hand-written HTTP client.** `urequests` mishandles chunked
transfer-encoding, which the OpenAI API uses for non-streamed responses.
`httpc.py` handles chunked bodies, `Content-Length` bodies and read-until-close.

**TLS.** `certs/roots.pem` is a trust bundle holding one root per upstream:

| Root | Anchors | Expires |
|---|---|---|
| GTS Root R4 | `api.openai.com` (leaf → GTS WE1 → R4) | 2036 |
| Amazon Root CA 1 | `api.tavily.com` (leaf → Amazon RSA 2048 M01 → CA 1) | 2038 |

MicroPython's mbedtls accepts a concatenated multi-cert PEM through
`load_verify_locations(cadata=...)`, so both hosts verify against one file —
confirmed on-device, not assumed. The bundle is loaded once at boot and shared
by the LLM and search clients rather than being parsed per client.

Verification needs a correct clock, so boot syncs NTP before the first request;
if NTP fails the log says so, because the resulting failure otherwise looks
like a network fault. Setting `verify_tls: false` keeps the session encrypted
but stops authenticating the peer.

To add another HTTPS upstream, append its root to `certs/roots.pem` and
redeploy — `tools/deploy.sh` copies every file in `certs/`.

**History trimming.** `history_limit` drops the oldest turns, but never cuts
between an assistant message carrying `tool_calls` and the `tool` messages
answering it — the API rejects that pairing if it is split.

**Getting skills to actually load.** Three things were needed before models
reliably used skills instead of bypassing them, each found by watching real
runs:

1. *No name collisions between a tool and a skill.* The diagnostics tool was
   originally called `sysinfo`, exactly matching the `sysinfo` skill — the
   model resolved the name straight to the tool and never read the skill, then
   dumped raw JSON the skill explicitly says not to dump. Renaming it
   `board_status` fixed it; the skill now loads first and the report follows
   its guidance.
2. *An explicit gating rule* in the system prompt: if a skill's description
   matches, calling `Skill` must be the first action. Before this, "turn the
   led red" went straight to `led_set(255,0,0)` at full brightness; after, it
   loads the skill and uses `(51,0,0)`, the 20% scaling the skill prescribes.
3. *Guardrails in `write_file` itself.* Prompt-level rules are ignored at the
   exact moment a tool looks sufficient, so the checks live in the tool:
   a loose `.py` under `/skills/` is refused, a bundled file without a
   `SKILL.md` is refused, and a `SKILL.md` missing frontmatter, `name`,
   `description`, a body, or with a name that disagrees with its directory is
   refused with the required template. Without these the model wrote files
   that registered nothing and then reported success.

The general lesson: structural guardrails enforce *form*, not *correctness*. A
validated manifest can still ship a broken script, so `write-skill` tells the
agent to execute a script before claiming it works.

**The LED is cleared at boot.** A WS2812 latches whatever appears on its data
line while the board resets, so it routinely powers up lit at a random colour.
Nothing else writes to it, so it would stay lit until the next LED command —
which reads as "the blink left the LED on" even though every blink path ends
with an off write. `clear_led()` runs once during boot, and the pin is created
as `Pin(n, OUT, value=0)` so the line is driven low the moment it becomes an
output rather than floating.

**MicroPython gotcha.** `dict(x)` fast-paths exact dicts only; on a dict
*subclass* it iterates as key/value pairs and raises `ValueError`. `Config`
is a subclass, so copies use a comprehension. Similarly `sys.stdout` is not
reassignable here, so `run_script` captures output by injecting `print` into
the script's globals rather than swapping global state.

## Backing up and restoring firmware

Any firmware on the board — this agent, a vendor application, anything — can be
captured as a whole-flash image and written back byte-for-byte. A full image
includes the bootloader, partition table, app and every data partition, so it
restores installed files and settings as well as code.

Set the port once:

```bash
PORT=/dev/cu.usbmodem1101
ESPTOOL=.venv/bin/esptool
```

### First: free the port

esptool talks to the ROM bootloader, and it cannot get there while an
application is driving USB. **Stop the agent before any flash operation** —
`Ctrl-C` in `tools/console.sh`, or just power-cycle the board and act before
`main.py` starts.

If you see `No serial data received` on repeated attempts, the board is not in
a state esptool can reach. Recover it physically: hold **BOOT**, tap **RESET**,
release BOOT — or hold BOOT while plugging USB in. Nothing over the wire fixes
this.

**Do not use `machine.bootloader()` or `mpremote bootloader` on this board.**
They do not produce the ROM download mode esptool needs. On this MicroPython
build the chip re-enumerates as `303a:4001` ("Espressif Device"), where the
REPL is gone, WiFi is gone, and esptool reports `No serial data received` — a
dead end that only a physical BOOT+RESET clears. Working download mode looks
like `303a:1001` ("USB JTAG_serial debug unit").

Check which one you have with:

```bash
ioreg -p IOUSB -l -w 0 | grep -E '"(idProduct|USB Product Name)"'
```

Note also that esptool cannot reset this board into download mode while
MicroPython is running — not even from an idle REPL. Use the physical BOOT
sequence whenever you need to flash.

### Find the flash size

```bash
$ESPTOOL --port $PORT flash-id
```

Read `Detected flash size:` from the output.

| Flash | Size argument |
|---|---|
| 4 MB | `0x400000` |
| 8 MB | `0x800000` |
| 16 MB | `0x1000000` |

### Back up

```bash
$ESPTOOL --port $PORT --baud 921600 read-flash 0 0x800000 backup/before-changes.bin
shasum -a 256 backup/before-changes.bin
```

Roughly 50 seconds for 8 MB. Keep the checksum — it is how you later prove the
image you are about to restore is the one you took.

### Restore

```bash
$ESPTOOL --port $PORT --baud 921600 write-flash --flash-size keep 0 backup/before-changes.bin
```

`--flash-size keep` matters: without it esptool may rewrite the image header's
flash-size field, so what lands is not what you captured. Add `--erase-all` to
wipe regions the image does not cover, which is worth doing when moving between
firmwares that use different partition layouts.

### Verify

```bash
$ESPTOOL --port $PORT verify-flash --flash-size keep 0 backup/before-changes.bin
```

A whole-flash verify only passes **immediately after flashing, before the
device has run**. Once it boots, the radio rewrites NVS and PHY calibration
data around `0x9000` — inside the verified range — and the digest no longer
matches, with or without `--flash-size detect`. That is normal, not
corruption. To check an application after it has been running, verify just its
partition:

```bash
# app at 0x10000: compare only that region
python3 -c "d=open('firmware.bin','rb').read(); open('/tmp/app.bin','wb').write(d[0x10000:])"
$ESPTOOL --port $PORT verify-flash --flash-size keep 0x10000 /tmp/app.bin
```

### Partial backups

Whole-flash images are simplest, but any region can be read on its own once you
know its offset and length from the partition table printed in the boot log:

```bash
# a 1.65 MB data partition at 0x660000
$ESPTOOL --port $PORT read-flash 0x660000 0x1a0000 backup/storage.bin
```

Note that ESP-IDF FATFS partitions normally use a wear-levelling layer, so a
raw region dump will not mount as a plain filesystem on a host — it restores
correctly to the same board, but it is not a browsable disk image.

### The image taken from this board

`backup/esp-claw-full-8MB.bin` (sha256 `a8f4ab40…`) is the 8 MB image captured
before MicroPython was flashed. Restoring it brings back the original
`edge_agent` / ESP-Claw application together with its installed skills, learned
memory and chat logs.
