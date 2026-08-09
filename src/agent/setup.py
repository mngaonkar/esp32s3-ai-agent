"""First-boot setup.

A freshly flashed board has no /config.json. Rather than fail with an
unhelpful error, it asks for the handful of settings it cannot possibly guess
and writes the file itself.

Only three answers are required -- the network to join, its password, and an
API key. Everything else has a working default and can be changed later in the
web Config screen, so setup stays short enough that nobody skips it.
"""

from . import config

BANNER = """
==============================================
  First-time setup
==============================================
This board has no configuration yet. Three
answers are needed; press Enter to accept the
default shown in [brackets].

Everything else can be changed later at
http://<board-ip>/ under Config.
"""


def needed(cfg):
    """True when the agent cannot run as configured."""
    return not (cfg.get("wifi_ssid") and cfg.get("api_key"))


def _ask(prompt, default=None, required=False, validate=None):
    while True:
        suffix = " [%s]" % default if default else ""
        try:
            answer = input("%s%s: " % (prompt, suffix)).strip()
        except (EOFError, KeyboardInterrupt):
            raise SetupAborted()

        if not answer and default is not None:
            answer = default
        if not answer:
            if required:
                print("  ...this one is required.")
                continue
            return ""
        if validate:
            problem = validate(answer)
            if problem:
                print("  ...%s" % problem)
                continue
        return answer


class SetupAborted(Exception):
    pass


def _check_key(value):
    if not value.startswith("sk-"):
        # Warn rather than reject: proxies and compatible endpoints issue keys
        # in other formats, and refusing them would be wrong.
        print("  note: OpenAI keys normally start with 'sk-'. Using it anyway.")
    return None


def run(cfg):
    """Prompt for the mandatory settings and save. Returns the updated cfg."""
    print(BANNER)

    cfg["wifi_ssid"] = _ask("WiFi network name", cfg.get("wifi_ssid") or None,
                            required=True)
    cfg["wifi_password"] = _ask("WiFi password", required=True)
    cfg["api_key"] = _ask("OpenAI API key", required=True, validate=_check_key)

    print("\nOptional -- press Enter to skip:")
    model = _ask("Model", cfg.get("model", "gpt-4o-mini"))
    if model:
        cfg["model"] = model
    tavily = _ask("Tavily API key (enables web search)")
    if tavily:
        cfg["tavily_api_key"] = tavily

    try:
        config.save(cfg)
    except Exception as exc:
        print("\n!! could not write /config.json: %s" % exc)
        print("   Settings apply for this session only.")
        return cfg

    print("\nSaved to /config.json. Starting the agent...\n")
    return cfg


def maybe_run(cfg):
    """Run setup when required. Returns (cfg, ran)."""
    if not needed(cfg):
        return cfg, False
    try:
        return run(cfg), True
    except SetupAborted:
        print("\n[setup] cancelled. The agent cannot start without WiFi and an "
              "API key.\n         Re-run by resetting the board, or deploy a "
              "config.json.")
        return cfg, False
    except Exception as exc:
        print("\n[setup] failed: %s" % exc)
        return cfg, False
