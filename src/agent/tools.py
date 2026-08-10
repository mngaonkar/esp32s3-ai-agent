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
from . import llm as _llm
from . import search as _search
from . import vision as _vision
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


# Paths the agent may create, overwrite, or delete while authoring skills and
# saving media. Everything else is protected so a bad tool call cannot wipe
# firmware entrypoints or the agent package.
_MUTABLE_PREFIXES = ("/skills/", "/tmp/", "/photos/", "/audio/")


def _is_mutable_path(path):
    if path in ("/skills", "/tmp", "/photos", "/audio"):
        return True
    for prefix in _MUTABLE_PREFIXES:
        if path == prefix.rstrip("/") or path.startswith(prefix):
            return True
    return False


def _rm_tree(path):
    """Remove a file or directory tree. Returns a short status string."""
    if not _exists(path):
        return "missing"
    if _is_dir(path):
        for name in os.listdir(path):
            child = path.rstrip("/") + "/" + name
            _rm_tree(child)
        os.rmdir(path)
        return "dir"
    os.remove(path)
    return "file"


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
        self._cadata = cadata
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
            "Create or overwrite a text file under /skills/, /tmp/, /photos/, "
            "or /audio/. Parent dirs are created automatically. For a new "
            "skill write /skills/<name>/SKILL.md (load write-skill for format) "
            "then optional scripts/; never a loose .py under /skills/.",
            {
                "path": {"type": "string", "description": "Absolute file path."},
                "content": {"type": "string", "description": "Full file contents."},
            },
            ["path", "content"],
            self._write_file,
        )

        self.add(
            "delete_file",
            "Delete a file or an entire directory tree under /skills/, /tmp/, "
            "/photos/, or /audio/. Use to remove a failed skill "
            "(/skills/<name>/) and start over, or to free space. Protected "
            "paths (agent code, config.json, main.py) cannot be deleted. "
            "After deleting under /skills/, the skill registry is reloaded.",
            {
                "path": {"type": "string",
                         "description": "Absolute path to a file or directory."},
            },
            ["path"],
            self._delete_file,
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
                "board's filesystem. Returns path, size and view_url. To "
                "describe or analyse what is in the image, call "
                "analyze_photo next with that path (or omit path for latest).",
                {
                    "filename": {"type": "string", "description": "Optional name, e.g. 'desk.bmp'. Defaults to a reused latest name."},
                    "frame_size": {"type": "string", "description": "QQVGA, QVGA (default for vision), VGA, … Prefer QVGA or QQVGA if you will analyze."},
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
                "analyze_photo",
                "Send a saved photo to the vision-capable chat model and "
                "return its description. Use after take_photo, or on an "
                "existing file under /photos/, whenever the user asks what "
                "is in the picture, to read text, or to analyse the scene. "
                "Requires a vision model (e.g. gpt-4o, gpt-4o-mini).",
                {
                    "path": {"type": "string", "description": "Absolute path e.g. /photos/latest.bmp. Default: last capture or photo_dir/latest."},
                    "question": {"type": "string", "description": "What to look for. Default: brief scene description."},
                    "max_side": {"type": "integer", "description": "Downscale long side before upload (default 320)."},
                },
                [],
                self._analyze_photo,
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
        path = a.get("path", "") or ""
        content = a.get("content", "")
        if not str(path).strip():
            return (
                "Error: path is empty. Pass an absolute path such as "
                "/skills/<name>/scripts/foo.py or /tmp/draft.py"
            )
        if not path.startswith("/"):
            return "Error: path must be absolute (got %r)" % path
        if not _is_mutable_path(path):
            return (
                "Refused: can only write under /skills/, /tmp/, /photos/, or "
                "/audio/ (got %s). Draft under /tmp/ or install under /skills/."
                % path)
        if content is None:
            content = ""
        if not isinstance(content, str):
            content = str(content)

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
                        "add this file. Or draft under /tmp/ until tests pass."
                        % (rel_parts[0], manifest))

        if _exists(path) and _is_dir(path):
            return "Error: %s is a directory; write to a file path inside it" % path

        try:
            _mkdirp(path)
            with open(path, "w") as f:
                f.write(content)
        except OSError as exc:
            errno = getattr(exc, "errno", None)
            extra = ""
            if errno in (28, 105):
                extra = (" (filesystem full? use delete_file on old "
                         "/photos or abandoned /skills)")
            elif errno == 30:
                extra = " (read-only filesystem)"
            return "Error writing %s: %s%s" % (path, exc, extra)

        # A new or edited SKILL.md changes the catalog, so reindex immediately.
        if path.endswith("SKILL.md"):
            self.skills.discover()
            return ("Wrote %d bytes to %s and reloaded the skill registry.\n\n"
                    "If you are still prototyping, test scripts with "
                    "run_script before claiming the skill works. Prefer "
                    "drafting under /tmp/ then copying into "
                    "/skills/<name>/scripts/ once tests pass. For hardware, "
                    "load the skill that already owns it (e.g. led uses "
                    "led_set with state true/false on cfg['led_pin'], not "
                    "neopixel or inventing pins). To abandon a broken skill, "
                    "delete_file the whole /skills/<name>/ directory.\n\n"
                    "Installed skills are now:\n%s"
                    % (len(content), path, self.skills.catalog()))
        return "Wrote %d bytes to %s" % (len(content), path)

    def _delete_file(self, a):
        path = a.get("path", "")
        if not path.startswith("/"):
            return "Error: path must be absolute (got %r)" % path
        if path in ("/", "/skills", "/tmp", "/photos", "/audio"):
            return "Refused: will not delete the root of %s" % path
        if not _is_mutable_path(path):
            return (
                "Refused: can only delete under /skills/, /tmp/, /photos/, or "
                "/audio/ (got %s)" % path)
        if not _exists(path):
            return "Nothing to delete: %s does not exist" % path

        try:
            kind = _rm_tree(path)
        except OSError as exc:
            return "Error deleting %s: %s" % (path, exc)

        skills_root = self.skills.root.rstrip("/")
        if path == skills_root or path.startswith(skills_root + "/"):
            self.skills.discover()
            return ("Deleted %s (%s) and reloaded the skill registry.\n\n"
                    "Installed skills are now:\n%s"
                    % (path, kind, self.skills.catalog()))
        return "Deleted %s (%s)" % (path, kind)

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

    def _resolve_photo_path(self, path):
        if path:
            if not path.startswith("/"):
                path = self.camera.photo_dir.rstrip("/") + "/" + path
            return path
        # Prefer the last web-facing capture name.
        if self.last_photo:
            name = self.last_photo.split("?", 1)[0].rsplit("/", 1)[-1]
            return self.camera.photo_dir.rstrip("/") + "/" + name
        default = self.cfg.get("photo_name") or "latest.bmp"
        return self.camera.photo_dir.rstrip("/") + "/" + default

    def _analyze_photo(self, a):
        path = self._resolve_photo_path(a.get("path"))
        question = (a.get("question") or "").strip() or (
            "Describe this photo briefly: main subjects, setting, any readable "
            "text, and notable details. Be factual; say if the image is dark, "
            "blurry, or unclear."
        )
        max_side = int(a.get("max_side") or 320)
        if max_side < 64:
            max_side = 64
        if max_side > 640:
            max_side = 640

        try:
            data_url, w, h, png_len = _vision.photo_data_url(path, max_side=max_side)
        except Exception as exc:
            return "Analyze failed (encode): %s: %s" % (type(exc).__name__, exc)

        print("[vision] upload %s -> %dx%d png~%dB" % (path, w, h, png_len))
        client = _llm.Client(self.cfg, self._cadata)
        try:
            text = client.chat_vision(question, data_url, detail="low")
        except Exception as exc:
            return (
                "Analyze failed (API): %s: %s\n"
                "Use a vision-capable model (e.g. gpt-4o or gpt-4o-mini) in Config."
                % (type(exc).__name__, exc)
            )
        finally:
            # Drop huge base64 string ASAP.
            data_url = None
            gc.collect()

        return (
            "Vision analysis of %s (%sx%s, png~%s bytes):\n%s"
            % (path, w or "?", h or "?", png_len, text or "(empty reply)")
        )

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
        raw = resp.content
        ctype = (resp.headers.get("content-type") or "").lower()
        # Images and other binary must not be decoded as text -- MicroPython
        # can raise UnicodeError, and the bytes are useless to the model anyway.
        looks_binary = (
            ctype.startswith("image/")
            or ctype.startswith("audio/")
            or ctype.startswith("video/")
            or ctype.startswith("application/octet")
            or (raw[:3] == b"\xff\xd8\xff")  # JPEG
            or (raw[:8] == b"\x89PNG\r\n\x1a\n")
            or (raw[:2] == b"BM")
        )
        if looks_binary:
            return (
                "HTTP %d\nContent-Type: %s\nBytes read: %d (binary; not shown)\n"
                "Tip: use the URL as-is for download/display; do not expect "
                "text body from image endpoints."
                % (resp.status_code, ctype or "unknown", len(raw))
            )
        try:
            body = raw.decode("utf-8")
        except Exception:
            body = raw.decode("utf-8", "ignore") if hasattr(raw, "decode") else str(raw)
            body = "(partial decode)\n" + body
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
