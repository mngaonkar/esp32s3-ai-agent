"""Editable-settings schema for the web config screen.

The schema lives on the board rather than in the page's JavaScript so there is
exactly one definition of what may be changed, what type it is, and what counts
as a legal value. The browser renders whatever this module reports.
"""

import json

# key, type, label, group, and optional constraints.
#   secret  -> never sent to the browser; an empty submission means "unchanged"
#   select  -> fixed set of options
FIELDS = (
    ("wifi_ssid", "text", "WiFi SSID", "Network", {}),
    ("wifi_password", "secret", "WiFi password", "Network", {}),

    ("base_url", "text", "API base URL", "Model", {}),
    ("api_key", "secret", "OpenAI API key", "Model", {}),
    ("model", "text", "Model", "Model", {}),
    ("temperature", "float", "Temperature", "Model", {"min": 0, "max": 2}),
    ("max_tokens", "int", "Max tokens", "Model", {"min": 1, "max": 8192}),

    ("tavily_api_key", "secret", "Tavily API key", "Search", {}),
    ("tavily_max_results", "int", "Max results", "Search", {"min": 1, "max": 10}),
    ("tavily_search_depth", "select", "Search depth", "Search",
     {"options": ("basic", "advanced")}),

    ("max_tool_iterations", "int", "Max tool rounds", "Agent", {"min": 1, "max": 30}),
    ("history_limit", "int", "History limit", "Agent", {"min": 2, "max": 100}),
    ("system_prompt", "textarea", "Extra system prompt", "Agent", {}),

    ("verify_tls", "bool", "Verify TLS certificates", "Security", {}),
    ("ca_cert", "text", "CA bundle path", "Security", {}),
    ("request_timeout", "int", "Request timeout (s)", "Security", {"min": 5, "max": 120}),

    ("led_pin", "int", "User LED pin (GPIO)", "Hardware", {"min": 0, "max": 48}),
    ("led_active_low", "bool", "LED is active-LOW", "Hardware", {}),
    ("web_enabled", "bool", "Web chat enabled", "Hardware", {}),
    ("web_port", "int", "Web port", "Hardware", {"min": 1, "max": 65535}),
)

# Kept out of the web UI entirely -- neither editable nor listed. Camera and
# photo settings are tuned to this specific sensor and wiring; a wrong value
# there breaks capture in ways that are not obvious from the form.
_HIDDEN = ("camera_enabled", "camera_frame_size", "camera_pins", "camera_quality",
           "photo_dir", "photo_name", "photo_overwrite")

# Shown read-only: nested structures, or paths the agent needs to find its
# own code.
_READ_ONLY = ("skills_dir", "wifi_timeout")

# Changing these cannot take effect without a reboot; everything else is
# re-applied to the running agent immediately.
RESTART_REQUIRED = ("wifi_ssid", "wifi_password", "web_port", "web_enabled")

_BY_KEY = {}
for _f in FIELDS:
    _BY_KEY[_f[0]] = _f


def describe(cfg):
    """Field metadata plus current values, with secrets withheld."""
    out = []
    for key, kind, label, group, extra in FIELDS:
        item = {
            "key": key,
            "type": kind,
            "label": label,
            "group": group,
            "restart": key in RESTART_REQUIRED,
        }
        if kind == "secret":
            # The real value never leaves the board. The UI shows only whether
            # one is stored, so loading the page cannot leak a key.
            item["value"] = ""
            item["isSet"] = bool(cfg.get(key))
        else:
            item["value"] = cfg.get(key)
        for k in ("min", "max"):
            if k in extra:
                item[k] = extra[k]
        if "options" in extra:
            item["options"] = list(extra["options"])
        out.append(item)
    return out


def extras(cfg):
    """Every config key the form does not edit, shown read-only.

    Without this the screen silently omits whatever the form has not caught up
    with, so adding a setting elsewhere in the code makes the two drift apart
    with no visible sign. Anything here is still editable by deploying
    config.json.
    """
    out = []
    for key in sorted(cfg):
        if key in _BY_KEY or key in _HIDDEN:
            continue
        value = cfg[key]
        if "key" in key or "password" in key or "secret" in key:
            value = "********" if value else ""
        elif not isinstance(value, (str, int, float, bool)) and value is not None:
            try:
                value = json.dumps(value)
            except Exception:
                value = str(value)
        out.append({"key": key, "value": value,
                    "note": "not editable here" if key in _READ_ONLY else ""})
    return out


def _coerce(kind, raw, extra):
    """Return (value, error)."""
    if kind == "bool":
        if isinstance(raw, bool):
            return raw, None
        return str(raw).lower() in ("1", "true", "on", "yes"), None

    if kind in ("int", "float"):
        text = str(raw).strip()
        if text == "":
            return None, "must not be empty"
        try:
            value = int(text) if kind == "int" else float(text)
        except ValueError:
            return None, "must be a number"
        if "min" in extra and value < extra["min"]:
            return None, "must be at least %s" % extra["min"]
        if "max" in extra and value > extra["max"]:
            return None, "must be at most %s" % extra["max"]
        return value, None

    if kind == "select":
        text = str(raw)
        if text not in extra.get("options", ()):
            return None, "must be one of %s" % ", ".join(extra.get("options", ()))
        return text, None

    return str(raw), None


def apply(cfg, values):
    """Validate and merge submitted values into cfg in place.

    Returns (changed_keys, errors, needs_restart). cfg is only touched when
    every field validates, so a rejected form never leaves a half-applied
    configuration behind.
    """
    errors = {}
    staged = {}

    for key, raw in values.items():
        spec = _BY_KEY.get(key)
        if not spec:
            continue
        _, kind, _, _, extra = spec

        if kind == "secret":
            # Blank means "leave the stored secret alone".
            if str(raw).strip() == "":
                continue
            staged[key] = str(raw).strip()
            continue

        value, error = _coerce(kind, raw, extra)
        if error:
            errors[key] = error
        else:
            staged[key] = value

    if errors:
        return [], errors, False

    changed = []
    for key, value in staged.items():
        if cfg.get(key) != value:
            cfg[key] = value
            changed.append(key)

    needs_restart = any(k in RESTART_REQUIRED for k in changed)
    return changed, {}, needs_restart
