---
name: netscan
description: Survey and troubleshoot the wireless environment - list nearby WiFi access points with signal strength and channel, find the least congested channel, check whether the board's own connection is healthy, and fetch a URL to test internet reachability. Use for questions about WiFi networks, signal, channels, interference, or connectivity problems.
version: 1.0.0
---

# Wireless survey and connectivity

## Scanning

`wifi_scan` returns nearby access points sorted strongest first, each with
`ssid`, `rssi`, `channel` and `secure`. A scan takes two to three seconds and
briefly competes with the board's own connection, so run it once and work from
that result rather than rescanning.

Hidden networks appear with an ssid of `<hidden>`; that is expected, not a bug.

## Interpreting signal

RSSI is dBm and always negative -- closer to zero is stronger:

- -30 to -50: excellent, same room
- -50 to -67: good, reliable for streaming
- -67 to -75: weak, expect occasional drops
- below -80: effectively unusable

## Channel congestion

For "which channel should I use", run `scripts/channel_survey.py` via
`run_script`. It buckets the scan by channel and weights each network by signal
strength, so one strong neighbour counts for more than three distant ones.

On 2.4 GHz only channels 1, 6 and 11 do not overlap. Always recommend one of
those three, even when an adjacent channel looks emptier -- a network on
channel 3 interferes with both 1 and 6. Say why when you recommend.

This board's radio is 2.4 GHz only, so it cannot see or join 5 GHz networks.
If a user's network is missing from the scan, that is the first thing to check.

## Connectivity checks

Distinguish the two failure modes rather than reporting "no internet":

1. `board_status` -> `wifi_ip` is null means the board never associated. It is
   a WiFi or credentials problem.
2. `wifi_ip` is set but `http_get` on `http://example.com` fails means the
   board is on the LAN but has no route out -- DNS, captive portal, or upstream.

Use a plain-HTTP URL for reachability tests. An HTTPS failure is ambiguous,
since it can also mean the clock is wrong and certificate validation failed.
