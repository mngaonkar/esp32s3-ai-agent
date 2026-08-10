"""Native tools exposed to the model as OpenAI function definitions.

Skills supply *instructions*; these tools supply *capability*. Anything a skill
tells the model to do ultimately runs through one of the handlers here, which is
what lets new skills be added at runtime without reflashing.
"""

import gc
import json
import machine
import os
import sys
import time

from . import camera as _camera
from . import httpc
from . import search as _search
from . import wifi
from .skills import parse_frontmatter


def _mkdirp(path):
    parts = [p for p in path.split("/") if p]
    cur = ""
    for part in parts[:-1]:
        cur += "/" + part
        try:
            os.mkdir(cur)
        except OSError:
            pass


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


def _validate_manifest(content, dir_name):
    """Return a problem description for a SKILL.md, or None when it is valid."""
    if not content.lstrip().startswith("---"):
        return "it has no YAML frontmatter block"
    meta, body = parse_frontmatter(content)
    if not meta.get("name"):
        return "the frontmatter has no 'name' field"
    if not meta.get("description"):
        return ("the frontmatter has no 'description' field, so the skill can "
                "never be selected")
    if meta["name"] != dir_name:
        return ("name '%s' does not match its directory '%s'; they must be "
                "identical" % (meta["name"], dir_name))
    if not body.strip():
        return "it has frontmatter but no instructions after it"
    return None


class ToolRegistry:
    """Holds tool schemas plus their handlers and dispatches model tool calls."""

    def __init__(self, cfg, skills, cadata=None):
        self.cfg = cfg
        self.skills = skills
        self._handlers = {}
        self._schemas = []
        self._np = None
        self.tavily = _search.TavilyClient(cfg, cadata)
        self.camera = _camera.CameraDevice(cfg)
        self.last_photo = None
        self._register_all()

    # ------------------------------------------------------------------ setup

    def add(self, name, description, properties, required, handler):
        self._schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        })
        self._handlers[name] = handler

    def schemas(self):
        return self._schemas

    def invoke(self, name, arguments):
        handler = self._handlers.get(name)
        if not handler:
            return "Error: no such tool '%s'" % name
        try:
            result = handler(arguments or {})
        except Exception as exc:
            return "Error: %s: %s" % (type(exc).__name__, exc)
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result)
        except Exception:
            return str(result)

    # --------------------------------------------------------------- handlers

    def _register_all(self):
        self.add(
            "Skill",
            "Load the full instructions for an installed skill. Call this as "
            "soon as a skill's description looks relevant to the request; the "
            "returned text tells you how to complete the task and lists any "
            "bundled files you can read or run.",
            {"name": {"type": "string", "description": "Skill name to load."}},
            ["name"],
            lambda a: self.skills.render(a.get("name", "")),
        )

        self.add(
            "list_skills",
            "List every installed skill with its description. Useful after "
            "creating a new skill to confirm it registered.",
            {}, [],
            lambda a: self.skills.catalog(),
        )

        self.add(
            "list_dir",
            "List files and directories at a path on the board's filesystem.",
            {"path": {"type": "string", "description": "Absolute path, e.g. /skills"}},
            ["path"],
            self._list_dir,
        )

        self.add(
            "read_file",
            "Read a UTF-8 text file from the board's filesystem.",
            {
                "path": {"type": "string", "description": "Absolute file path."},
                "max_bytes": {"type": "integer", "description": "Cap on bytes read (default 4000)."},
            },
            ["path"],
            self._read_file,
        )

        self.add(
            "write_file",
            "Create or overwrite a text file on the board. Parent directories "
            "are created automatically. To author a skill, load the "
            "'write-skill' skill first and follow it: a skill is a directory "
            "/skills/<name>/SKILL.md, never a loose .py file.",
            {
                "path": {"type": "string", "description": "Absolute file path."},
                "content": {"type": "string", "description": "Full file contents."},
            },
            ["path", "content"],
            self._write_file,
        )

        self.add(
            "run_script",
            "Execute a MicroPython .py script that is bundled with a skill. "
            "Anything the script prints is returned to you, as is the value it "
            "assigns to a variable named `result`. Scripts run with `args`, "
            "`cfg`, `machine`, `time` and `tool` in scope, where "
            "tool('name', {...}) calls any tool listed here.",
            {
                "path": {"type": "string", "description": "Absolute path to a .py file."},
                "args": {"type": "object", "description": "Optional args, available to the script as `args`."},
            },
            ["path"],
            self._run_script,
        )

        # Deliberately not named "sysinfo": a native tool sharing a skill's
        # exact name gets called directly, and the skill's interpretation
        # guidance is never loaded.
        self.add(
            "board_status",
            "Return raw board diagnostic values: heap and PSRAM usage, "
            "filesystem usage, CPU frequency, die temperature, uptime, WiFi "
            "state and MAC address. Values are unformatted and some are "
            "easily misread; the sysinfo skill explains how to interpret them.",
            {}, [],
            self._sysinfo,
        )

        self.add(
            "wifi_scan",
            "Scan for nearby WiFi access points, strongest first.",
            {"limit": {"type": "integer", "description": "Max networks to return (default 15)."}},
            [],
            lambda a: wifi.scan(int(a.get("limit", 15))),
        )

        if self.tavily.enabled:
            self.add(
                "web_search",
                "Search the live web via Tavily and get back a short synthesised "
                "answer plus source snippets. Use for anything you cannot know "
                "from the board itself: current events, prices, weather, "
                "documentation, datasheets, or any fact that may have changed "
                "since training. Prefer this over http_get, which returns raw "
                "unparsed HTML.",
                {
                    "query": {"type": "string", "description": "The search query."},
                    "max_results": {"type": "integer", "description": "Sources to return, 1-10 (default 5)."},
                    "topic": {"type": "string", "description": "'general' (default) or 'news' for recent events."},
                    "days": {"type": "integer", "description": "With topic='news', how many days back to look."},
                },
                ["query"],
                self._web_search,
            )

        if self.camera.enabled:
            self.add(
                "take_photo",
                "Take a photo with the onboard camera and save it to the "
                "board's filesystem. Returns the saved path, dimensions and "
                "file size. You cannot see the image yourself -- report where "
                "it was saved, do not describe what is in it.",
                {
                    "filename": {"type": "string", "description": "Optional name, e.g. 'desk.bmp'. Defaults to a timestamp."},
                    "frame_size": {"type": "string", "description": "QQVGA, QVGA, VGA, SVGA (default), XGA, HD, SXGA or UXGA."},
                },
                [],
                self._take_photo,
            )
            self.add(
                "list_photos",
                "List photos already saved on the board, with their sizes.",
                {}, [],
                self._list_photos,
            )

        self.add(
            "http_get",
            "Fetch a URL from the internet and return the response body as text.",
            {
                "url": {"type": "string", "description": "Full URL including scheme."},
                "max_bytes": {"type": "integer", "description": "Cap on bytes returned (default 2000)."},
            },
            ["url"],
            self._http_get,
        )

        self.add(
            "gpio_write",
            "Drive a GPIO pin high or low.",
            {
                "pin": {"type": "integer", "description": "GPIO number."},
                "value": {"type": "integer", "description": "1 for high, 0 for low."},
            },
            ["pin", "value"],
            self._gpio_write,
        )

        if self.cfg.get("led_pin") is not None:
            self.add(
                "led_set",
                "Turn the onboard user LED on or off. This board has a single "
                "yellow LED -- it has no colour, so ignore any request for a "
                "particular colour and say so.",
                {"state": {"type": "boolean",
                           "description": "true for on, false for off."}},
                ["state"],
                self._led_set,
            )

    def _list_dir(self, a):
        path = a.get("path", "/")
        if not _is_dir(path):
            return "Not a directory: %s" % path
        rows = []
        for entry in sorted(os.listdir(path)):
            full = (path.rstrip("/") + "/" + entry)
            if _is_dir(full):
                rows.append("%s/" % entry)
            else:
                try:
                    rows.append("%s (%d bytes)" % (entry, os.stat(full)[6]))
                except OSError:
                    rows.append(entry)
        return "\n".join(rows) if rows else "(empty)"

    def _read_file(self, a):
        path = a.get("path", "")
        limit = int(a.get("max_bytes", 4000))
        with open(path) as f:
            data = f.read(limit + 1)
        if len(data) > limit:
            return data[:limit] + "\n...[truncated]"
        return data

    def _write_file(self, a):
        path = a.get("path", "")
        content = a.get("content", "")
        if not path.startswith("/"):
            return "Error: path must be absolute"

        # Writing into /skills/ is how the agent extends itself, and it is also
        # where it most often goes wrong: dropping a loose .py in the root
        # silently creates nothing, and the model then reports success. Reject
        # that shape and state the required layout instead.
        root = self.skills.root.rstrip("/") + "/"
        if path.startswith(root):
            rel_parts = [p for p in path[len(root):].split("/") if p]
            if len(rel_parts) == 1:
                return (
                    "Refused: %s would sit loose in %s and would NOT become a "
                    "skill. A skill must be a directory containing SKILL.md:\n"
                    "  %s<name>/SKILL.md      instructions with YAML "
                    "frontmatter (name, description)\n"
                    "  %s<name>/scripts/*.py  optional code\n"
                    "Load the 'write-skill' skill for the exact format, then "
                    "write to %s<name>/SKILL.md."
                    % (path, self.skills.root, root, root, root))
            if rel_parts[-1] == "SKILL.md":
                # A manifest without valid frontmatter is silently ignored by
                # the registry, which reads to the model as a successful write.
                # Refuse it so the failure is impossible to miss.
                problem = _validate_manifest(content, rel_parts[0])
                if problem:
                    return (
                        "Refused: %s is not a valid SKILL.md -- %s\n"
                        "It must begin with YAML frontmatter, exactly:\n"
                        "---\n"
                        "name: %s\n"
                        "description: <what it does AND when to use it, "
                        "including words a user would say>\n"
                        "---\n\n"
                        "# <title>\n"
                        "<instructions>\n"
                        % (path, problem, rel_parts[0]))
            else:
                manifest = root + rel_parts[0] + "/SKILL.md"
                if not _exists(manifest):
                    return (
                        "Refused: skill '%s' has no SKILL.md yet, so a bundled "
                        "file cannot be attached to it. Write %s first, then "
                        "add this file." % (rel_parts[0], manifest))

        _mkdirp(path)
        with open(path, "w") as f:
            f.write(content)
        # A new or edited SKILL.md changes the catalog, so reindex immediately.
        if path.endswith("SKILL.md"):
            self.skills.discover()
            return ("Wrote %d bytes to %s and reloaded the skill registry.\n\n"
                    "If this skill drives hardware, do NOT invent pin access in "
                    "its scripts. Load the skill that already documents that "
                    "hardware and reuse its approach -- for the RGB LED that is "
                    "the 'led' skill, which uses the neopixel driver on the pin "
                    "in cfg['led_pin'], not a bare machine.Pin. A bare Pin "
                    "cannot produce a colour and will run cleanly while doing "
                    "nothing.\n\nInstalled skills are now:\n%s"
                    % (len(content), path, self.skills.catalog()))
        return "Wrote %d bytes to %s" % (len(content), path)

    def _run_script(self, a):
        path = a.get("path", "")
        if not path.endswith(".py"):
            return "Error: run_script only executes .py files"
        try:
            with open(path) as f:
                source = f.read()
        except OSError as exc:
            return "Error: cannot read %s: %s" % (path, exc)

        # Capture output by giving the script its own print() in its globals,
        # which shadows the builtin. sys.stdout is not reassignable in this
        # MicroPython build, and swapping global state would leave the REPL
        # broken if a script raised midway.
        captured = []

        def _capture(*values, **kwargs):
            sep = kwargs.get("sep", " ")
            captured.append(sep.join(str(v) for v in values))

        namespace = {
            "args": a.get("args") or {},
            # A comprehension, not dict(): MicroPython's dict() constructor
            # fast-paths exact dicts only, and iterates a dict *subclass* as a
            # sequence of pairs, which raises. Config is a subclass.
            "cfg": {k: v for k, v in self.cfg.items()},
            "machine": machine,
            "time": time,
            "print": _capture,
            # Scripts compose existing capability through this rather than
            # importing modules that do not exist. Without a supported route
            # to reuse a tool, models invent one (`import led`) and the script
            # fails at run time.
            "tool": lambda name, tool_args=None: self.invoke(name, tool_args or {}),
            "result": None,
            "__name__": "__skill__",
        }

        try:
            exec(source, namespace)
        except Exception as exc:
            return "Script raised %s: %s\n--- output ---\n%s" % (
                type(exc).__name__, exc, "\n".join(captured))

        parts = []
        printed = "\n".join(captured).strip()
        if printed:
            parts.append(printed)
        value = namespace.get("result")
        if value is not None:
            try:
                parts.append("result = " + json.dumps(value))
            except Exception:
                parts.append("result = " + str(value))
        return "\n".join(parts) if parts else "Script finished with no output."

    def _sysinfo(self, a):
        gc.collect()
        stat = os.statvfs("/")
        fs_total = stat[0] * stat[2]
        fs_free = stat[0] * stat[3]
        info = {
            "heap_free": gc.mem_free(),
            "heap_used": gc.mem_alloc(),
            "fs_total_bytes": fs_total,
            "fs_free_bytes": fs_free,
            "cpu_hz": machine.freq(),
            "uptime_s": time.ticks_ms() // 1000,
            "wifi_ip": wifi.ip(),
            "wifi_rssi": wifi.rssi(),
            "micropython": sys.version,
            "platform": sys.implementation._machine,
        }
        try:
            import ubinascii
            import network
            mac = network.WLAN(network.STA_IF).config("mac")
            info["mac"] = ubinascii.hexlify(mac, ":").decode()
        except Exception:
            pass
        try:
            import esp32
            info["mcu_temp_c"] = round(esp32.mcu_temperature(), 1)
        except Exception:
            pass
        return info

    def _take_photo(self, a):
        try:
            info = self.camera.capture(
                path=a.get("filename"),
                frame_size=a.get("frame_size"),
            )
        except Exception as exc:
            return "Photo failed: %s: %s" % (type(exc).__name__, exc)
        name = info["path"].rsplit("/", 1)[-1]
        # Cache-buster: the default filename is reused for every shot, so a
        # browser would otherwise keep showing the first photo it fetched.
        rel = "/photos/%s?t=%d" % (name, time.ticks_ms())
        ip = wifi.ip()
        info["view_url"] = ("http://%s%s" % (ip, rel)) if ip else None
        # Picked up by the web chat so the image is shown inline.
        self.last_photo = rel
        return info

    def _list_photos(self, a):
        photos = self.camera.list_photos()
        if not photos:
            return "No photos saved yet."
        return "\n".join("%s (%d bytes)" % (n, s) for n, s in photos)

    def _web_search(self, a):
        try:
            data = self.tavily.search(
                a.get("query", ""),
                max_results=a.get("max_results"),
                topic=a.get("topic", "general") or "general",
                days=a.get("days"),
            )
        except _search.SearchError as exc:
            return "Search failed: %s" % exc
        return _search.format_results(data)

    def _http_get(self, a):
        limit = int(a.get("max_bytes", 2000))
        resp = httpc.get(a.get("url", ""), timeout=20, max_bytes=limit)
        body = resp.content.decode("utf-8", "replace")
        return "HTTP %d\n%s" % (resp.status_code, body)

    def _gpio_write(self, a):
        pin_no = int(a["pin"])
        value = 1 if int(a["value"]) else 0
        machine.Pin(pin_no, machine.Pin.OUT).value(value)
        return "GPIO%d set to %d" % (pin_no, value)

    def _led_pin(self):
        """The user LED as a plain output.

        This board (XIAO ESP32S3 Sense) has a single-colour user LED on GPIO21
        wired active-LOW -- pin low lights it. It is NOT addressable, so the
        neopixel driver is wrong for it: neopixel leaves the line resting low
        between frames, which on an active-low LED means permanently ON.
        """
        if self._np is None:
            off = 1 if self.cfg.get("led_active_low", True) else 0
            self._np = machine.Pin(int(self.cfg["led_pin"]), machine.Pin.OUT,
                                   value=off)
        return self._np

    def _led_write(self, on):
        pin = self._led_pin()
        if self.cfg.get("led_active_low", True):
            pin.value(0 if on else 1)
        else:
            pin.value(1 if on else 0)

    def _led_set(self, a):
        raw = a.get("state", a.get("on", True))
        if isinstance(raw, str):
            on = raw.strip().lower() in ("on", "true", "1", "yes")
        else:
            on = bool(raw)
        self._led_write(on)
        return "LED on GPIO%s turned %s" % (self.cfg["led_pin"], "on" if on else "off")

    def clear_led(self):
        """Force the LED off at boot so it starts from a known state."""
        if self.cfg.get("led_pin") is None:
            return False
        try:
            self._led_write(False)
            return True
        except Exception as exc:
            print("[boot] could not clear LED: %s" % exc)
            return False
