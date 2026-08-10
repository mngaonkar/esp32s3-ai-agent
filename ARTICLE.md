# An AI Agent That Runs *On* an ESP32-S3 (Not On Your Laptop)

*Chat with a board on your LAN. It blinks its own LED, checks its own health, takes a photo and describes what it sees, logs temperature as a text chart, and writes new skills onto its own flash — all in MicroPython.*

![ESP32-S3 Agent web chat running on a phone browser](https://raw.githubusercontent.com/mngaonkar/esp32s3-ai-agent/master/docs/medium/01-web-chat.png)

Most "ESP32 + AI" projects put the brain on a PC or a cloud worker and use the microcontroller as a dumb sensor. This one flips that around.

**esp32s3-ai-agent** is an AI agent that runs **on** a Seeed XIAO ESP32S3 Sense. It calls an OpenAI-compatible API for reasoning, but the tool loop, the skills, the web UI, and the hardware control all live on the board.

Code: [github.com/mngaonkar/esp32s3-ai-agent](https://github.com/mngaonkar/esp32s3-ai-agent)

## The idea in one picture

```text
Phone / laptop browser  ──HTTP──►  ESP32-S3 agent
                                      │
                                      ├─ skills (instructions on flash)
                                      ├─ tools (LED, camera, files, search…)
                                      └─ HTTPS ──►  OpenAI-compatible API
```

You open a page on your local network. You type a message. The board:

1. Builds a system prompt that lists the available **skills** — name and one-line description only.
2. Calls the model with **tools**.
3. Runs those tool calls against real hardware, and retries on failure inside a generous tool-round budget.
4. Returns a reply as **text**, which the web UI renders as markdown, code fences, and inline photos.

The split between the three layers is the whole design:

**Skills** are how to use *this* board — which pin the LED is on, how to report free heap, how to draw a plot in text.

**Tools** are raw capability — `led_set`, `board_status`, `take_photo`, `analyze_photo`, `write_file`, `delete_file`, `run_script`, `web_search`, and friends.

**The model** decides what to do next.

New skills are just folders with a `SKILL.md` in them on the board's filesystem. No reflash to add a procedure. The agent can also **author skills itself**, either when you describe one or when it finishes a multi-step task worth remembering.

## What it looks like

The web UI is a small Matrix-green chat page served **from the board**. There is no cloud frontend.

Here is a real turn — the model loads the `sysinfo` skill, calls `board_status`, then answers in plain language:

![The agent loads the sysinfo skill, calls board_status, and replies with heap and Wi-Fi details](https://raw.githubusercontent.com/mngaonkar/esp32s3-ai-agent/master/docs/medium/02-chat-reply.png)

That two-step is deliberate. Progressive skill loading follows the Anthropic-style skills pattern: don't stuff every instruction into the prompt up front, let the model pull in the full text only when it decides the skill is relevant. On a device with a few hundred KB of usable prompt budget, that isn't an elegance argument — it's the difference between working and not.

Configuration lives on the device too:

![Config screen with Wi-Fi, model dropdown, and API settings](https://raw.githubusercontent.com/mngaonkar/esp32s3-ai-agent/master/docs/medium/03-config.png)

A few details worth calling out:

- Secrets stay on the board. Saved fields show "stored — leave blank to keep".
- **Model** becomes a dropdown, populated from `GET {base_url}/models` when the key works. If that call fails, it falls back to a plain text field with a hint.
- The CA bundle path is read-only in the UI. Change it through a deployed `config.json`.
- Wi-Fi settings and the web port need a restart. Almost everything else applies live.
- **Max tool rounds** defaults to **50**, so skill authoring and fix-and-retry loops have room to actually finish.

## The hardware

The board is a **Seeed XIAO ESP32S3 Sense**. It works for this because it has 8 MB of octal **PSRAM**, a camera (an OV3660 on my unit), a user LED on GPIO21 wired active-low, and Wi-Fi.

The runtime is **MicroPython**, specifically a camera-capable build from [cnadler86/micropython-camera-API](https://github.com/cnadler86/micropython-camera-API).

PSRAM is the part that matters most. Conversation history, a TLS session, and JSON parsing of tool-call responses are not things you fit in 512 KB of SRAM. With 8 MB behind them, they're routine.

Two honest limitations. The onboard **PDM microphone is not supported** — MicroPython has no PDM RX, so audio recording was tried and then removed rather than left half-working. And the **trust model is a trusted LAN**: the web UI and the chat API have no authentication at all. Do not put this on the public internet.

## Deploying it

You need a XIAO ESP32S3 Sense (or a similar ESP32-S3 with PSRAM), a USB cable that actually carries data, Python 3, Wi-Fi, and an OpenAI-compatible API key.

**1. Clone and install dependencies.**

```bash
git clone https://github.com/mngaonkar/esp32s3-ai-agent.git
cd esp32s3-ai-agent

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

The pinned set is small: `esptool` to talk to the ROM bootloader, `mpremote` for day-to-day file pushes, and `littlefs-python` to build the board's filesystem on your machine.

**2. Build the image.**

```bash
python3 tools/build_image.py
```

This packs two things into one flashable binary in `dist/`: the camera-capable MicroPython firmware, and a LittleFS image containing `main.py`, the `agent/` modules, every skill under `skills/`, and the CA bundle. `config.json` is deliberately left out, so the image carries no credentials and is safe to hand to someone else.

**3. Flash it.**

Put the board in download mode first: hold **BOOT**, tap **RESET** (or hold BOOT while plugging in USB), keep BOOT held for about three seconds, then release. macOS shows it as "USB JTAG_serial debug unit" when it's ready.

```bash
tools/flash.sh                    # newest image in dist/
tools/flash.sh dist/esp32s3-agent-1.0.0.bin   # or a specific one
```

That erases the chip and writes the whole image at offset 0 — firmware and filesystem in a single pass. A new board needs nothing else: no per-file copying, no Python tooling on the device side.

**4. First-time setup over serial.**

Setup is still console-based; there's no captive portal yet. Power-cycle *without* holding BOOT, then:

```bash
tools/console.sh
```

On first boot the board asks only for what it cannot guess: Wi-Fi SSID, Wi-Fi password, and an API key. Model name and a Tavily key for web search are optional. Everything else has a default and can be changed later from the web Config tab once you're online.

When setup finishes you should see something like this:

```text
[wifi] connected, ip=10.0.0.x
[skills] loaded …
[boot] web chat at http://10.0.0.x:80/
```

**5. Open the chat.**

From a phone or laptop on the same Wi-Fi, open that URL. `tools/start.sh` resets the board and prints the address again if you lost it.

Serial and web share a single agent — a small console reader thread keeps the web server responsive while you're typing at the REPL.

After that, day-to-day changes don't need a reflash:

```bash
tools/deploy.sh              # push code + skills; leaves /config.json alone
tools/deploy.sh --config     # also overwrite board config from local config.json
tools/start.sh
```

## Things worth asking it

**"How is the board doing?"** loads `sysinfo` and calls `board_status` — heap, PSRAM, filesystem, die temperature, Wi-Fi signal, uptime.

**"Blink the LED three times."** loads `led`, then runs a blink script through `run_script`.

**"Take a photo."** loads `camera` and calls `take_photo`. The web UI shows the image inline.

**"What do you see?"** calls `analyze_photo`. Photos land on flash as 24-bit BMP, which no vision endpoint accepts, so the board converts BMP to PNG and base64-encodes it into a data URL — a small pure-MicroPython PNG encoder, because there's no PIL out here.

**"Monitor MCU temperature for one minute."** loads `temp-monitor-plot`, which samples the die temperature into a CSV under `/tmp` and prints a text plot of the trace.

**"What's the weather in Fremont?"** calls `web_search`, if a Tavily key is configured.

**"Teach the board a skill that…"** loads `write-skill`, then drafts, tests, iterates on its own errors, and saves the result under `/skills/`.

The same agent is reachable over REST:

```bash
curl -s -X POST "http://<board-ip>/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"In one sentence, what board are you on?"}'
```

There is one shared conversation on the device. Web, serial, and REST all append to the same history until you reboot or reset it.

## How skills work

A skill is a directory on the board:

```text
/skills/led/SKILL.md
/skills/led/scripts/blink.py
```

It loads in three levels. **Level 1** is the name and description, always present in the system prompt. **Level 2** is the full `SKILL.md` body, pulled in when the model calls `Skill("name")`. **Level 3** is the scripts and data files, reached through `read_file` and `run_script`.

Eight skills ship in the repo:

- **`sysinfo`** — heap, PSRAM, filesystem, die temperature, Wi-Fi, uptime.
- **`led`** — onboard LED and general GPIO guidance, including the fact that this LED is single-colour and active-low.
- **`camera`** — take photos, list them, show them in the web UI, describe them with the vision model.
- **`netscan`** — Wi-Fi survey, channel congestion, reachability checks.
- **`websearch`** — when and how to use Tavily.
- **`temp-monitor-plot`** — sample MCU die temperature into CSV plus a text plot.
- **`tui-plot`** — redraw a CSV as a text-mode chart for chat or serial.
- **`write-skill`** — how the agent creates and updates skills.

## The agent grows its own skill list

This is the part I find most interesting to watch.

Describe a skill and the agent plans it, writes `/skills/<name>/SKILL.md`, and puts any scripts under `/tmp` first, then moves them into the skill folder once they run. After a multi-step task that worked and looks likely to recur, it may save a skill on its own initiative without being asked.

When something fails, it's expected to read the actual error, change something, and retry — which is why the tool-round budget defaults to 50 rather than the usual handful. `delete_file` lets it remove a failed skill directory under `/skills/` and reload the catalog, so a bad draft isn't permanent.

Filesystem writes are fenced to `/skills/`, `/tmp/`, `/photos/`, and `/audio/`. The agent cannot overwrite firmware paths, however creative it gets.

One thing to set expectations on: there is no curses or LVGL TUI on this image. "Graphs" are formatted text in code fences, which the web UI renders as monospaced markdown. If you want a real plot, take the CSV to a host machine.

## What this is not

It is not a cloud agent that merely *talks about* an ESP32. It is not phone-only first-boot setup — serial is still required once. It is not onboard PDM mic recording, a Discord gateway, NFS, or H.264 streaming. And it is not secure on an untrusted network, because the web UI has no login.

What it *is*: a small on-device agent loop with real tools, progressive skill loading, LAN chat plus REST, an OpenAI-compatible backend, and a skill library that can grow on flash.

## Closing

If you already own an ESP32-S3 Sense and an API key, clone → flash → serial setup → chat fits in one sitting.

The interesting part isn't that a microcontroller can talk to an LLM — plenty of projects do that. It's that the skills and the tools live next to the metal, so the model can operate *this specific board* and teach itself new procedures without anyone reflashing it.

Clone it, flash it, answer three questions on the console, open the green terminal on your LAN, and ask the board how it's doing.

**Repo:** [mngaonkar/esp32s3-ai-agent](https://github.com/mngaonkar/esp32s3-ai-agent)
**Camera firmware upstream:** [cnadler86/micropython-camera-API](https://github.com/cnadler86/micropython-camera-API)

---
