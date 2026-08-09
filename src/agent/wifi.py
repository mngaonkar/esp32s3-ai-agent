"""Station-mode WiFi bring-up."""

import network
import time


_STATUS = {}
for _name in ("STAT_IDLE", "STAT_CONNECTING", "STAT_WRONG_PASSWORD",
              "STAT_NO_AP_FOUND", "STAT_ASSOC_FAIL", "STAT_HANDSHAKE_TIMEOUT",
              "STAT_BEACON_TIMEOUT", "STAT_GOT_IP"):
    if hasattr(network, _name):
        _STATUS[getattr(network, _name)] = _name


def connect(ssid, password, timeout=20):
    """Bring up the station interface. Returns the IP address, or None."""
    sta = network.WLAN(network.STA_IF)
    sta.active(True)

    if sta.isconnected():
        ip = sta.ifconfig()[0]
        print("[wifi] already connected, ip=%s" % ip)
        return ip

    if not ssid:
        print("[wifi] no SSID configured")
        return None

    print("[wifi] connecting to %s ..." % ssid)
    sta.connect(ssid, password)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if sta.isconnected():
            ip = sta.ifconfig()[0]
            print("[wifi] connected, ip=%s rssi=%s" % (ip, rssi()))
            return ip
        status = sta.status()
        if status in (getattr(network, "STAT_WRONG_PASSWORD", -999),
                      getattr(network, "STAT_NO_AP_FOUND", -998),
                      getattr(network, "STAT_ASSOC_FAIL", -997)):
            print("[wifi] failed: %s" % _STATUS.get(status, status))
            return None
        time.sleep(0.5)

    print("[wifi] timed out after %ss (status=%s)" % (
        timeout, _STATUS.get(sta.status(), sta.status())))
    return None


def ip():
    sta = network.WLAN(network.STA_IF)
    return sta.ifconfig()[0] if sta.isconnected() else None


def rssi():
    try:
        return network.WLAN(network.STA_IF).status("rssi")
    except Exception:
        return None


def scan(limit=15):
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    results = []
    for net in sta.scan()[:limit]:
        ssid = net[0].decode("utf-8", "replace") if isinstance(net[0], bytes) else str(net[0])
        results.append({
            "ssid": ssid or "<hidden>",
            "channel": net[2],
            "rssi": net[3],
            "secure": net[4] != 0,
        })
    results.sort(key=lambda r: r["rssi"], reverse=True)
    return results
