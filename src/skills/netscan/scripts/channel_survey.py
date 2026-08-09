# Bucket nearby APs by channel, weighting each by signal strength, and
# recommend a non-overlapping 2.4 GHz channel.
import network

sta = network.WLAN(network.STA_IF)
sta.active(True)

load = {}
for net in sta.scan():
    channel = net[2]
    rssi = net[3]
    # A neighbour at -40 dBm crowds the channel far more than one at -85.
    weight = max(1, 100 + rssi)
    load[channel] = load.get(channel, 0) + weight

print("channel load (higher = more congested):")
for channel in sorted(load):
    print("  ch %-3d weight %-5d" % (channel, load[channel]))

candidates = [1, 6, 11]
scores = {c: load.get(c, 0) for c in candidates}
best = min(scores, key=lambda c: scores[c])

print("\nnon-overlapping options: %s" % scores)
print("recommended: channel %d" % best)

result = {
    "per_channel_load": load,
    "non_overlapping_scores": scores,
    "recommended_channel": best,
    "networks_seen": sum(1 for _ in load),
}
