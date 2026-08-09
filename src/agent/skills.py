"""Anthropic-style Skills for the on-device agent.

A skill is a directory containing a SKILL.md file whose YAML frontmatter carries
at minimum a `name` and a `description`. Anything else in the directory --
scripts/, references/, assets/ -- is bundled context the model may pull in on
demand.

    /skills/led/
        SKILL.md
        scripts/blink.py

The format follows Anthropic's progressive disclosure model, which is what keeps
a large skill library affordable on a microcontroller:

    Level 1  name + description only, injected into the system prompt at boot.
             A few dozen tokens per skill.
    Level 2  the full SKILL.md body, loaded when the model calls the Skill tool
             because it decided the skill is relevant.
    Level 3  bundled files, read individually via read_file / run_script.

Only level 1 is resident. A board can therefore carry far more skill material
than would ever fit in a single context window.
"""

import os


def _is_dir(path):
    try:
        return os.stat(path)[0] & 0x4000 != 0
    except OSError:
        return False


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _strip_quotes(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_frontmatter(text):
    """Parse the leading `---` YAML block of a SKILL.md.

    Deliberately supports only the small subset skills actually use: scalar
    `key: value` pairs, inline `[a, b]` lists, and `- item` block lists. A full
    YAML parser is far too heavy for a microcontroller and buys nothing here.

    Returns (metadata_dict, body_text).
    """
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    block = text[text.find("\n", 3) + 1:end]
    body_start = text.find("\n", end + 1)
    body = text[body_start + 1:] if body_start != -1 else ""

    meta = {}
    current_key = None
    for raw in block.split("\n"):
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue

        if line.startswith((" ", "\t")) and line.strip().startswith("- "):
            if current_key:
                meta.setdefault(current_key, [])
                if isinstance(meta[current_key], list):
                    meta[current_key].append(_strip_quotes(line.strip()[2:].strip()))
            continue

        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        current_key = key

        if not value:
            meta[key] = []
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[key] = [
                _strip_quotes(p.strip()) for p in inner.split(",") if p.strip()
            ] if inner else []
        else:
            meta[key] = _strip_quotes(value)

    return meta, body


class Skill:
    def __init__(self, name, path, description, meta):
        self.name = name
        self.path = path
        self.description = description
        self.meta = meta

    def read(self):
        """Level 2: the full SKILL.md body."""
        with open(self.path + "/SKILL.md") as f:
            return parse_frontmatter(f.read())[1]

    def files(self, rel="", depth=0):
        """Level 3: bundled files available to read_file / run_script."""
        found = []
        base = self.path + ("/" + rel if rel else "")
        if depth > 3:
            return found
        try:
            entries = os.listdir(base)
        except OSError:
            return found
        for entry in entries:
            child_rel = (rel + "/" + entry) if rel else entry
            full = base + "/" + entry
            if entry == "SKILL.md" and not rel:
                continue
            if _is_dir(full):
                found.extend(self.files(child_rel, depth + 1))
            else:
                try:
                    size = os.stat(full)[6]
                except OSError:
                    size = 0
                found.append((child_rel, full, size))
        return found


class SkillRegistry:
    """Discovers skills and renders them for the model at each disclosure level."""

    def __init__(self, root="/skills"):
        self.root = root
        self.skills = {}
        self.discover()

    def discover(self):
        """Scan for skills, reading only frontmatter to keep boot cheap."""
        self.skills = {}
        if not _is_dir(self.root):
            print("[skills] no skills directory at %s" % self.root)
            return self.skills

        for entry in sorted(os.listdir(self.root)):
            path = self.root + "/" + entry
            manifest = path + "/SKILL.md"
            if not _is_dir(path) or not _exists(manifest):
                continue
            try:
                # Read a bounded prefix: frontmatter is always at the top, so a
                # large skill body never needs to be pulled into RAM to index it.
                with open(manifest) as f:
                    head = f.read(1536)
                meta, _ = parse_frontmatter(head)
            except Exception as exc:
                print("[skills] failed to index %s: %s" % (entry, exc))
                continue

            name = meta.get("name") or entry
            description = meta.get("description", "")
            if not description:
                print("[skills] %s has no description; skipping" % name)
                continue
            self.skills[name] = Skill(name, path, description, meta)

        print("[skills] loaded %d: %s" % (
            len(self.skills), ", ".join(sorted(self.skills)) or "none"))
        return self.skills

    def get(self, name):
        return self.skills.get(name)

    def catalog(self):
        """Level 1 text for the system prompt."""
        if not self.skills:
            return "(no skills installed)"
        lines = []
        for name in sorted(self.skills):
            lines.append("- %s: %s" % (name, self.skills[name].description))
        return "\n".join(lines)

    def render(self, name):
        """Level 2 payload returned by the Skill tool."""
        skill = self.get(name)
        if not skill:
            available = ", ".join(sorted(self.skills)) or "none"
            return "No skill named '%s'. Available skills: %s" % (name, available)

        try:
            body = skill.read()
        except Exception as exc:
            return "Failed to read skill '%s': %s" % (name, exc)

        out = ["# Skill: %s\n" % skill.name, body.strip()]
        bundled = skill.files()
        if bundled:
            out.append("\n\n## Bundled files")
            out.append(
                "Read these with read_file, or execute .py scripts with "
                "run_script, using the exact absolute paths below.")
            for rel, full, size in bundled:
                out.append("- %s (%d bytes) -> %s" % (rel, size, full))
        return "\n".join(out)
