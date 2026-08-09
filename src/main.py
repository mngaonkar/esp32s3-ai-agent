"""Entry point: brings up WiFi, the agent, and both chat interfaces.

The serial console and the web server share one thread. Both file descriptors
are polled, so whichever gets input first drives the agent; an LLM call blocks
the other interface for its duration, which is the right trade for a
single-user device and avoids a second 8 KB stack.
"""

import gc
import select
import sys
import time

from agent import config, httpc, llm, loop, setup, skills, tools, web, wifi

BANNER = r"""
  ___ ___ ___ ___ ___     _   ___ ___ _  _ ___
 | __/ __| _ \_  )  _|   /_\ / __| __| \| |_  )
 | _|\__ \  _// /\__ \  / _ \ (_ | _|| .` |/ /
 |___|___/_| /___|___/ /_/ \_\___|___|_|\_/___|
"""


def build():
    cfg = config.load()
    # A freshly flashed board has no config; ask for what cannot be guessed.
    cfg, _ = setup.maybe_run(cfg)
    gc.collect()

    ip = wifi.connect(cfg["wifi_ssid"], cfg["wifi_password"], cfg["wifi_timeout"])
    if not ip:
        print("[boot] WARNING: no network. LLM calls will fail until WiFi is up.")

    try:
        time.sleep(1)
        import ntptime
        ntptime.settime()  # TLS certificate validity needs a real clock
        print("[boot] clock synced")
    except Exception as exc:
        print("[boot] NTP sync failed (%s); TLS verification may fail" % exc)

    # One trust bundle shared by every HTTPS client on the board.
    cadata = httpc.load_ca(cfg["ca_cert"]) if cfg.get("verify_tls") else None

    registry_skills = skills.SkillRegistry(cfg["skills_dir"])
    client = llm.Client(cfg, cadata)
    registry = tools.ToolRegistry(cfg, registry_skills, cadata)
    agent = loop.Agent(cfg, client, registry, registry_skills)

    if registry.clear_led():
        print("[boot] LED cleared (GPIO%s)" % cfg["led_pin"])

    print("[boot] model=%s tools=%d search=%s" % (
        cfg["model"], len(registry.schemas()),
        "tavily" if registry.tavily.enabled else "off"))
    return cfg, agent, ip


def run():
    print(BANNER)
    cfg, agent, ip = build()

    def reload_runtime(new_cfg):
        """Re-apply edited settings to the running agent.

        The LLM and Tavily clients cache their settings at construction, so a
        model or key change needs new instances. cfg is mutated in place, so
        the agent loop picks up prompt and iteration changes on its own.
        """
        cadata = httpc.load_ca(new_cfg["ca_cert"]) if new_cfg.get("verify_tls") else None
        agent.client = llm.Client(new_cfg, cadata)
        agent.registry = tools.ToolRegistry(new_cfg, agent.skills, cadata)
        print("[web] runtime reloaded (model=%s tools=%d)"
              % (new_cfg["model"], len(agent.registry.schemas())))

    server = None
    if cfg.get("web_enabled") and ip:
        try:
            server = web.WebServer(agent, cfg["web_port"], reload_runtime)
            print("[boot] web chat at http://%s:%s/" % (ip, cfg["web_port"]))
        except Exception as exc:
            print("[boot] web server failed to start: %s" % exc)

    print("\nType a message and press enter. Commands: /reset /skills /info /quit\n")
    sys.stdout.write("> ")

    poller = select.poll()
    poller.register(sys.stdin, select.POLLIN)

    buffer = ""
    while True:
        # Serve any pending web request first so the browser stays responsive
        # while the console sits idle waiting for a line.
        if server:
            try:
                while server.poll_once():
                    pass
            except Exception as exc:
                print("[web] %s" % exc)

        for _ in poller.poll(200):
            ch = sys.stdin.read(1)
            if ch in ("\n", "\r"):
                line = buffer.strip()
                buffer = ""
                sys.stdout.write("\n")
                if line:
                    handle(agent, line)
                sys.stdout.write("> ")
            elif ch in ("\x7f", "\x08"):
                if buffer:
                    buffer = buffer[:-1]
                    sys.stdout.write("\x08 \x08")
            elif ch == "\x03":
                raise KeyboardInterrupt
            else:
                buffer += ch
                sys.stdout.write(ch)


def handle(agent, line):
    if line in ("/quit", "/exit"):
        raise SystemExit
    if line == "/reset":
        agent.reset()
        print("Conversation cleared.")
        return
    if line == "/skills":
        agent.skills.discover()
        print(agent.skills.catalog())
        return
    if line == "/info":
        print(agent.registry.invoke("board_status", {}))
        return

    start = time.ticks_ms()
    reply = agent.ask(line)
    elapsed = time.ticks_diff(time.ticks_ms(), start) / 1000
    print("\n%s\n(%.1fs, heap free %d)" % (reply, elapsed, gc.mem_free()))


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n[boot] interrupted; dropping to REPL")
    except SystemExit:
        print("\n[boot] exited to REPL")
