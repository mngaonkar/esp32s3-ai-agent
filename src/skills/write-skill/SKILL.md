---
name: write-skill
description: Create a new skill for this agent, or edit an existing one, so the board gains a capability it did not have before. Use when the user asks you to teach the board something, remember a procedure, add a skill, or when you hit a task that no installed skill covers and the procedure is worth keeping.
version: 1.0.0
---

# Authoring new skills

This agent extends itself by writing skills to its own filesystem. A skill you
create here is live for the very next message -- no reflash, no reboot.

## What a skill is

A directory under `/skills/` containing `SKILL.md`:

    /skills/<name>/SKILL.md          instructions (required)
    /skills/<name>/scripts/*.py      code the agent can run (optional)

`SKILL.md` opens with YAML frontmatter, then markdown instructions:

    ---
    name: coffee-timer
    description: Time a pour-over brew with stage prompts. Use when the user
      asks to brew coffee or start a brew timer.
    version: 1.0.0
    ---

    # Coffee timer
    ...instructions...

Write it with `write_file` to the exact path `/skills/<name>/SKILL.md`. That
tool reindexes the registry automatically and reports back the new catalog, so
you can confirm registration in the same step.

## The description is the most important line

Only `name` and `description` stay resident in the system prompt. The body is
loaded solely when a description convinces the agent the skill is relevant --
so a vague description means a skill that is never used.

State **what it does and when to use it**, and include the words a user would
actually say. Compare:

- Weak: `description: Helps with the sensor.`
- Strong: `description: Read the BME280 temperature and humidity sensor over
  I2C and convert to Fahrenheit. Use when the user asks about temperature,
  humidity, or how warm the room is.`

Keep it under about 500 characters. `name` must be lowercase, hyphenated, and
match the directory name.

## Writing the body

Write instructions for a competent agent that has never seen this task, not
documentation for a human. Be specific about the parts that are not guessable
-- pin numbers, I2C addresses, unit conversions, thresholds, error handling --
and skip anything a capable model already knows.

Include judgement, not just steps: what a good result looks like, what to do
when a reading is out of range, when to stop and ask. Keep the body under a few
hundred lines; move bulk detail into separate files and reference them by path,
since they load only on demand.

Put anything involving loops, timing or many rapid hardware operations into
`scripts/*.py` rather than describing tool calls, because each tool call is a
full model round trip. Scripts receive `args`, `cfg`, `machine`, `time` and
`tool` already in scope, print freely, and return data by assigning to
`result`.

## Reuse hardware that another skill already documents

Never reinvent hardware access. If a skill already covers the hardware you
need, load it first and copy its documented approach exactly. The `led` skill
owns the RGB LED: it is a **neopixel** on `cfg["led_pin"]`, and a bare
`machine.Pin(n).value(1)` cannot produce a colour -- it will execute cleanly
and do nothing visible, which is worse than failing.

Inside a script, call an existing tool with `tool(name, args)`:

    tool("led_set", {"r": 0, "g": 0, "b": 51})

That is the only supported way to reuse capability from a script. There is no
importable module for a skill -- `import led` will raise `ImportError`. Prefer
`tool(...)` or an existing script over writing new low-level code, and only
write raw hardware code for hardware that no skill covers.

Before claiming a new skill works, actually exercise it with `run_script` and
check the output is what you expect. A script that runs without raising is not
the same as a script that did the right thing.

## Procedure

1. Check `list_skills` first -- if a close skill exists, edit it instead of
   adding a near-duplicate.
2. Choose a lowercase hyphenated name.
3. `write_file` the `SKILL.md`.
4. `write_file` any scripts under `scripts/`.
5. If you wrote a script, run it once with `run_script` to prove it executes.
6. Tell the user the skill name, what it does, and one example phrase that
   will trigger it.

## Constraints

Keep skills to what this hardware can actually do: the tools available to you,
2.4 GHz WiFi, GPIO, and roughly 6 MB of filesystem. Do not write a skill that
depends on a library that is not installed or a sensor that is not wired up. If
the user asks for something the board cannot do, say so instead of writing a
skill that will fail on first use.
