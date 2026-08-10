---
name: write-skill
description: Create or update a skill from a user description, or save a
  procedure you just used so future turns can reuse it. Use when the user asks
  to teach the board something, add a skill, remember a workflow, or when you
  finished a multi-step task that is worth keeping and no existing skill covers
  it. On errors, reason and retry until the skill works.
version: 3.1.0
---

# Creating and saving skills

Skills are how this board remembers procedures. A skill is live for the next
message as soon as `SKILL.md` is written -- no reflash.

    /skills/<name>/SKILL.md          required instructions
    /skills/<name>/scripts/*.py      optional code for loops / timing

## Core rule: reason, act, fix -- do not bail

When creating or testing a skill, **errors are normal**. You have many tool
rounds (up to about 50 per turn). Use them.

**Never stop at the first failure** with only an apology. On every error:

1. **Read** the tool/script error carefully (path, errno, HTTP status, refusal
   text from `write_file`).
2. **Reason** about the cause (bad path, invalid frontmatter, missing
   dependency, wrong pin, network, full flash, script bug).
3. **Change** one concrete thing (edit script, fix YAML, different URL, free
   space with `delete_file`, load the hardware skill, etc.).
4. **Retry** the same goal (write / run_script / end-to-end check).
5. Repeat until **success** or you hit a true hard limit (board cannot do it,
   tool rounds exhausted, or the same fix failed 3+ times with no new info).

Only then explain to the user what blocked you and what you tried.

Bail-out patterns that are **wrong**:

- "write_file failed so I stopped"
- "the script raised, here is the traceback" (with no edit + re-run)
- Declaring the skill done while the last test still failed

## When to create a skill

### A. User asked for one (description-driven)

The user describes what the skill should do.

1. Load this skill (you already did).
2. `list_skills` once -- if something close exists, **edit it** instead of
   duplicating.
3. Plan: name, trigger phrases, tools/scripts, feasibility on **this** board.
4. If another skill owns the hardware (`led`, `camera`, …), load it and reuse
   its approach.
5. Implement and **iterate until tests pass** (see loop below).
6. Tell the user the skill name and one example trigger phrase.

### B. Worth keeping (opportunistic)

After a multi-step task **succeeded**, no existing skill covers it, and it is
likely to be asked again -- save a skill and mention `Saved skill name`.

Do not skill-ify one-off chat or a single trivial tool call.

## Implementation loop (until success)

Stay in this loop while authoring; do not narrate every micro-step to the user
until you are done or truly stuck.

1. **Draft** under `/tmp/<name>/` for scripts when behaviour is non-trivial.
2. **`run_script`** (or run the tool sequence the skill will prescribe).
3. If fail → diagnose → `write_file` fix → go to 2.
4. When the draft works: `write_file` `/skills/<name>/SKILL.md` (valid
   frontmatter; `name` == directory name).
5. Copy proven scripts to `/skills/<name>/scripts/` (SKILL.md must exist first).
6. One final check: catalog lists it; optional re-run on the final path.
7. If `write_file` **Refused**, fix the content/path from the message and
   write again -- do not abandon the skill.

You may call several independent tools in one model round. Do not re-load
write-skill or re-list skills every iteration.

## Format

**Name:** lowercase, hyphenated, matches directory.

**Description:** what + when + user phrases (~500 chars). Only name +
description stay in the system prompt.

    ---
    name: example-name
    description: What it does and when to use it, including user phrases.
    version: 1.0.0
    ---

    # Title
    Steps, tools, judgement for a future agent turn...

**Scripts** get `args`, `cfg`, `machine`, `time`, `tool`:

    tool("led_set", {"state": True})

No `import led`. Prefer `tool(...)`.

## This board

- LED: `led_set` `{"state": true/false}` on `cfg["led_pin"]` (active-low).
  Not RGB / neopixel.
- Reuse camera / sysinfo / search skills for those domains.
- Only real tools and hardware. If impossible (e.g. PDM mic under MicroPython),
  say so after checking -- that is a hard stop, not a first-error bail.

## Fix or replace

- Overwrite paths to update; bump `version`.
- `delete_file` `/skills/<name>` removes a whole skill and reloads the catalog.
- Prefer fixing in place over deleting unless the design was wrong.

## Done when

- Last test succeeded (script and/or tool sequence).
- Catalog includes the skill.
- User gets name + trigger phrase (or a one-line opportunistic save note).
