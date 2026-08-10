# An AI Agent That Runs *On* an ESP32-S3 (Not On Your Laptop)

*Chat with a board on your LAN. It can blink its LED, check its own health, take a photo, and load new skills from its own filesystem — written in MicroPython.*

---

Most “ESP32 + AI” projects put the brain on a PC or cloud worker and use the microcontroller as a dumb sensor. This one flips that around.

**esp32s3-ai-agent** is an AI agent that runs **on** a Seeed XIAO ESP32S3 Sense. It calls an OpenAI-compatible API for reasoning, but the tool loop, skills, web UI, and hardware control all live on the board.

**Repo:** [https://github.com/mngaonkar/esp32s3-ai-agent](https://github.com/mngaonkar/esp32s3-ai-agent)

---

## The idea in one picture

```
Phone / laptop browser  ──HTTP──►  ESP32-S3 agent
                                      │
                                      ├─ skills (instructions on flash)
                                      ├─ tools (LED, camera, WiFi, files…)
                                      └─ HTTPS ──►  OpenAI-compatible API
```

You open a page on your local network. You type a message. The board:

1. Builds a system prompt that lists available **skills** (name + short description only)
2. Calls the model with **tools**
3. Runs tool calls on real hardware
4. Returns a reply — and stays running even if you unplug USB (as long as it has power and Wi‑Fi)

That split is intentional:

| Layer | Role |
|--------|------|
| **Skills** | How to use *this* board (pin polarity, how to report heap, when to search…) |
| **Tools** | Capability (`led_set`, `board_status`, `take_photo`, …) |
| **Model** | Decides what to do next |

New skills are folders with a `SKILL.md` on the board’s filesystem. No reflash to add a procedure.

---

## What it looks like

The web UI is a small Matrix-style chat served **from the board** — no cloud frontend.

### Empty chat

![ESP32-S3 Agent web chat, empty](docs/medium/01-web-chat.png)

### A real turn (skill + tool + answer)

![Agent loads sysinfo skill, calls board_status, replies with heap and Wi-Fi](docs/medium/02-chat-reply.png)

Here the model first loaded the `sysinfo` skill, then called `board_status`, then answered in plain language (~8 MB free heap, strong RSSI, die temperature). That progressive skill loading is the same idea as Anthropic-style skills: don’t stuff every instruction into the prompt up front.

### Config on the device

![Config screen with Wi-Fi, model dropdown, API settings](docs/medium/03-config.png)

Secrets stay on the board (the UI shows “stored — leave blank to keep”). The **Model** field can load a dropdown from `GET /v1/models` when the API key works. Wi‑Fi and port changes need a restart; most other settings apply live.

> **Screenshots** were taken against a live board on the LAN (`http://<board-ip>/`). When you publish on Medium, upload the PNGs under `docs/medium/` as article images (Medium does not resolve GitHub-relative paths in the web editor the same way).

---

## Hardware

| | |
|--|--|
| Board | **Seeed XIAO ESP32S3 Sense** |
| Extras that matter | 8 MB octal **PSRAM**, camera (OV3660 on this unit), user LED, Wi‑Fi |
| Runtime | **MicroPython** (camera-capable build) |

PSRAM is what makes conversation history, TLS, and JSON practical on a microcontroller. Without it, this class of agent is a fight with the heap.

**Trust model:** the web UI and chat API are unauthenticated. Treat the board as a **trusted-LAN** device, not something to put on the public internet.

---

## Quick deploy from GitHub

### What you need

- XIAO ESP32S3 Sense (or similar ESP32-S3 + PSRAM + USB)
- USB cable that carries data
- Python 3 on your computer
- Wi‑Fi and an OpenAI-compatible API key

### 1. Clone

```bash
git clone https://github.com/mngaonkar/esp32s3-ai-agent.git
cd esp32s3-ai-agent

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install esptool mpremote
```

### 2. Flash the image

Put the board in **download mode**: hold **BOOT**, tap **RESET** (or hold BOOT while plugging USB), wait a few seconds, release BOOT.

```bash
tools/flash.sh
```

That writes a prebuilt image (MicroPython + agent filesystem). Credentials are **not** in the image.

### 3. First-time setup over serial

Power-cycle **without** holding BOOT, then:

```bash
tools/console.sh
```

On first boot the board asks only for what it cannot guess:

- Wi‑Fi SSID  
- Wi‑Fi password  
- API key  

Optional: model, Tavily key (web search). Everything else has defaults and can be changed later in **Config**.

When setup finishes you should see something like:

```text
[wifi] connected, ip=10.0.0.x
[skills] loaded …
[boot] web chat at http://10.0.0.x:80/
```

### 4. Open the chat

On a phone or laptop on the **same Wi‑Fi**, open the printed URL.

Or from the host:

```bash
tools/start.sh    # reset + print the web address again
```

### Day-to-day development (no full reflash)

```bash
# edit code under src/, then:
tools/deploy.sh              # push code + skills; leaves /config.json alone
tools/deploy.sh --config     # also overwrite board config from local config.json
tools/start.sh
```

---

## Try these prompts

| You say | What it tends to do |
|---------|---------------------|
| “How is the board doing?” | Load `sysinfo` → `board_status` |
| “Blink the LED three times” | Load `led` → `run_script` blink |
| “Take a photo” | Load `camera` → `take_photo` (web can show the image) |
| “What’s the weather in …?” | `web_search` if Tavily is configured |

Or hit the same agent over REST:

```bash
curl -s -X POST "http://<board-ip>/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"In one sentence, what board are you on?"}'
```

History is **one shared conversation** on the device (web, serial, and REST share it) until reboot or a reset.

---

## How skills work (without the deep dive)

A skill is a directory on the board:

```text
/skills/led/SKILL.md
/skills/led/scripts/blink.py
```

- **Level 1** — name + description always in the system prompt (cheap)  
- **Level 2** — full `SKILL.md` when the model calls `Skill("led")`  
- **Level 3** — scripts/files via `read_file` / `run_script`  

That’s how you keep a library of capabilities without stuffing megabytes of instructions into every API call.

Bundled examples include `sysinfo`, `led`, `camera`, `netscan`, `websearch`, and `write-skill` (so the agent can author new skills onto its own flash).

---

## What this is *not*

- Not a cloud agent that merely *talks about* an ESP32  
- Not a full Discord/NFS/video stack on-device (those need bridges or other firmware)  
- Not secure on an untrusted network (no login on the web UI)

It *is* a small, honest on-device agent loop: tools, skills, LAN chat, OpenAI-compatible backend.

---

## Links

- **GitHub:** [mngaonkar/esp32s3-ai-agent](https://github.com/mngaonkar/esp32s3-ai-agent)  
- **MicroPython camera firmware used upstream:** [cnadler86/micropython-camera-API](https://github.com/cnadler86/micropython-camera-API)  
- Screenshots for this article: `docs/medium/` in the repo  

---

## Closing

If you already own an ESP32-S3 Sense and an API key, you can go from clone → flash → chat in a single sitting. The interesting part is not “LLM on a microcontroller” as a demo — it’s that **skills and tools live next to the metal**, so the model can operate *this* board with instructions that stay on flash and grow without a reflash.

Clone it, flash it, open the green terminal on your LAN, and ask the board how it’s doing.

---

*Article source: `ARTICLE.md` in the project repo. Images: `docs/medium/01-web-chat.png`, `02-chat-reply.png`, `03-config.png`.*
