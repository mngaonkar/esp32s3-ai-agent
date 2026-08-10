"""Configuration loading for the on-device agent.

Settings live in /config.json on the board's filesystem so that credentials are
never part of the deployed source tree. See config.example.json for the shape.
"""

import json

_PATH = "/config.json"

_DEFAULTS = {
    "wifi_ssid": "",
    "wifi_password": "",
    "wifi_timeout": 20,
    # OpenAI-compatible endpoint.
    "base_url": "https://api.openai.com/v1",
    "api_key": "",
    "model": "gpt-4o-mini",
    "temperature": 0.2,
    "max_tokens": 800,
    # Tavily web search. Leave the key empty to omit the web_search tool.
    "tavily_api_key": "",
    "tavily_max_results": 5,
    "tavily_search_depth": "basic",
    # Verify server certificates against this PEM trust bundle, which holds one
    # root per upstream (GTS Root R4 for api.openai.com, Amazon Root CA 1 for
    # api.tavily.com). When false the TLS session is still encrypted but the
    # peer is not authenticated.
    "verify_tls": True,
    "ca_cert": "/certs/roots.pem",
    "request_timeout": 45,
    # Agent behaviour.
    "skills_dir": "/skills",
    # Skill authoring needs many fix/retry rounds; stop only after a high cap.
    "max_tool_iterations": 50,
    "history_limit": 24,
    "system_prompt": "",
    # Web chat server.
    "web_enabled": True,
    "web_port": 80,
    # Onboard user LED. On this board (XIAO ESP32S3 Sense) it is a single
    # yellow LED on GPIO21 wired active-LOW. Set led_pin to null to disable
    # the LED tools entirely.
    "led_pin": 21,
    "led_active_low": True,
    # OV3660 camera on the XIAO ESP32S3 Sense expansion board. Pin map is
    # verified against the sensor responding on SCCB at 0x3C.
    # Camera runs on the cnadler86 micropython-camera-API build, which is
    # generic, so the XIAO wiring is supplied here. Verified against the
    # sensor answering on SCCB at 0x3C with chip id 0x3660 (OV3660).
    "camera_enabled": True,
    "camera_frame_size": "QVGA",
    "photo_dir": "/photos",
    # Reuse one filename so photos do not fill the filesystem. Give
    # take_photo an explicit filename to keep a shot.
    "photo_overwrite": True,
    "photo_name": "latest.bmp",
    "camera_pins": {
        "data": [15, 17, 18, 16, 14, 12, 11, 48],  # D0..D7
        "vsync": 38, "href": 47, "sda": 40, "scl": 39,
        "pclk": 13, "xclk": 10, "xclk_freq": 20000000,
        "pwdn": -1, "reset": -1,
    },
}


class Config(dict):
    """Dict subclass exposing keys as attributes for convenience."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


def load(path=_PATH):
    cfg = dict(_DEFAULTS)
    try:
        with open(path) as f:
            user = json.load(f)
        if not isinstance(user, dict):
            raise ValueError("config.json must contain a JSON object")
        cfg.update(user)
    except OSError:
        print("[config] %s not found; using defaults (no credentials)" % path)
    return Config(cfg)


def save(cfg, path=_PATH):
    with open(path, "w") as f:
        # See tools.py: dict() on a dict subclass raises under MicroPython.
        json.dump({k: v for k, v in cfg.items()}, f)
