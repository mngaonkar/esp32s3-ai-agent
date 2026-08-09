"""Microphone recording -- NOT FUNCTIONAL on this firmware.

Kept for reference only. `audio_enabled` defaults to False, so none of this
runs and the agent advertises no recording tools.

MicroPython cannot read this board's microphone. It is a PDM mic, and
machine.I2S implements only standard I2S -- there is no PDM mode in any
released MicroPython. From the machine.I2S maintainer:

    "The PDM protocol is not supported by MicroPython. It is not possible to
    use the machine.I2S class with a PDM microphone."
    -- micropython discussion #16048

The ESP32-S3 does have a hardware PDM-to-PCM converter on I2S0, and ESP-IDF
exposes it, but MicroPython does not. PR #14176 adds PDM_RX and was never
merged.

What is below clocks the mic with a standard I2S receiver and decimates the
bitstream in software. A standard I2S receiver cannot align to PDM framing, so
the result is noise with only weak correlation to sound -- no amount of
filtering fixes it. Do not mistake this for a tuning problem.

To actually record audio, one of:
  - build MicroPython with PR #14176 applied (ESP-IDF toolchain required)
  - use ESP-IDF or Arduino, where the PDM driver is available
  - use CircuitPython, which supports PDM via audiobusio.PDMIn
"""


import gc
import os
import struct
import time

# machine.I2S clocks SCK at rate * bits, so 46875 * 32 = 1.5 MHz, which is
# inside the mic's specified clock range.
PDM_I2S_RATE = 46875
PDM_CLOCK_HZ = PDM_I2S_RATE * 32
# Counting is done over 64 PDM bits, then filtered and decimated by 3. A bit
# count is a boxcar filter with a poor stopband, and PDM deliberately shapes
# its quantisation noise upwards, so counting alone leaves audible hiss --
# measured energy rose steadily with frequency, 5.9% below 300 Hz against
# 23.5% in the top octave. The cascaded low-pass below fixes that.
# Counting in 12-byte groups rather than 8 keeps the same total popcount work
# but a third fewer loop iterations, which is what dominates decode time.
COUNT_BYTES = 12                    # 96 PDM bits per intermediate sample
INTERMEDIATE_RATE = PDM_CLOCK_HZ // (COUNT_BYTES * 8)   # 15625 Hz
DECIMATE = 2
SAMPLE_RATE = INTERMEDIATE_RATE // DECIMATE             # 7812 Hz
# 3-pole one-pole cascade at ~3 kHz. Filtering happens before decimation --
# afterwards would be too late to stop HF noise aliasing into the speech band.
LP_ALPHA = 0.70
BYTES_PER_SECOND = PDM_CLOCK_HZ // 8              # 187500

_POPCOUNT = bytes(bin(i).count("1") for i in range(256))


class AudioError(Exception):
    pass


def _ensure_dir(path):
    parts = [p for p in path.split("/") if p]
    cur = ""
    for part in parts:
        cur += "/" + part
        try:
            os.mkdir(cur)
        except OSError:
            pass


def wav_header(n_samples, rate=SAMPLE_RATE, channels=1, bits=16):
    data_bytes = n_samples * channels * bits // 8
    byte_rate = rate * channels * bits // 8
    return (b"RIFF" + struct.pack("<I", 36 + data_bytes) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, channels, rate, byte_rate,
                        channels * bits // 8, bits) +
            b"data" + struct.pack("<I", data_bytes))


class Recorder:
    def __init__(self, cfg):
        self.cfg = cfg
        self.pins = cfg.get("audio_pins") or {}
        self.audio_dir = cfg.get("audio_dir", "/audio")

    @property
    def enabled(self):
        return bool(self.cfg.get("audio_enabled"))

    def _open(self):
        from machine import I2S, Pin
        return I2S(
            0,
            sck=Pin(self.pins.get("clk", 42)),
            # PDM has no word-select line, but machine.I2S requires one; this
            # pin is driven and otherwise unused.
            ws=Pin(self.pins.get("ws", 2)),
            sd=Pin(self.pins.get("data", 41)),
            mode=I2S.RX,
            bits=32,
            format=I2S.MONO,
            rate=PDM_I2S_RATE,
            ibuf=40000,
        )

    def record(self, seconds=None, path=None):
        if not self.enabled:
            raise AudioError("audio_enabled is false in /config.json")

        seconds = float(seconds or self.cfg.get("audio_seconds", 5))
        limit = float(self.cfg.get("audio_max_seconds", 10))
        if seconds <= 0:
            raise AudioError("seconds must be positive")
        if seconds > limit:
            raise AudioError("recording is capped at %g seconds (audio_max_seconds)"
                             % limit)

        if not path:
            if self.cfg.get("audio_overwrite", True):
                path = "%s/%s" % (self.audio_dir.rstrip("/"),
                                  self.cfg.get("audio_name", "latest.wav"))
            else:
                t = time.localtime()
                path = "%s/rec-%04d%02d%02d-%02d%02d%02d.wav" % (
                    self.audio_dir.rstrip("/"), t[0], t[1], t[2], t[3], t[4], t[5])
        if not path.startswith("/"):
            path = self.audio_dir.rstrip("/") + "/" + path
        if not path.lower().endswith(".wav"):
            path += ".wav"
        _ensure_dir(path.rsplit("/", 1)[0])

        gc.collect()
        want = int(seconds * BYTES_PER_SECOND)
        raw = bytearray(want)
        mic = None
        try:
            mic = self._open()
            # The first block after start-up is a transient; drop it.
            throwaway = bytearray(8192)
            time.sleep_ms(300)
            mic.readinto(throwaway)
            got = mic.readinto(raw)
        finally:
            if mic:
                try:
                    mic.deinit()
                except Exception:
                    pass

        if not got:
            raise AudioError("microphone returned no data")

        started = time.ticks_ms()
        n_samples = self._decode(path, raw, got)
        elapsed = time.ticks_diff(time.ticks_ms(), started)
        del raw
        gc.collect()

        return {
            "path": path,
            "bytes": os.stat(path)[6],
            "seconds": round(n_samples / SAMPLE_RATE, 2),
            "sample_rate": SAMPLE_RATE,
            "format": "WAV 16-bit mono",
            "decode_ms": elapsed,
        }

    def _decode(self, path, raw, length):
        """Decimate the PDM bitstream to 16-bit PCM and write a WAV."""
        steps = length // COUNT_BYTES
        out_count = steps // DECIMATE
        mv = memoryview(raw)
        pop = _POPCOUNT
        gain = int(self.cfg.get("audio_gain", 2000))
        a = LP_ALPHA
        dc = COUNT_BYTES * 4.0     # bitstream sits near 50% density
        y1 = y2 = y3 = 0.0
        chunk = bytearray(2048)

        with open(path, "wb") as f:
            f.write(wav_header(out_count))
            o = 0
            written = 0
            for k in range(steps):
                i = k * COUNT_BYTES
                c = 0
                for j in range(i, i + COUNT_BYTES):
                    c += pop[mv[j]]

                # Track and subtract the 50% density, or every sample is
                # one-sided.
                dc += (c - dc) * 0.002
                x = c - dc

                # Three one-pole sections in series: ~18 dB/octave above 3 kHz.
                y1 += (x - y1) * a
                y2 += (y1 - y2) * a
                y3 += (y2 - y3) * a

                if k % DECIMATE:
                    continue
                if written >= out_count:
                    break

                v = int(y3 * gain)
                if v > 32767:
                    v = 32767
                elif v < -32768:
                    v = -32768
                chunk[o] = v & 0xFF
                chunk[o + 1] = (v >> 8) & 0xFF
                o += 2
                written += 1
                if o >= 2048:
                    f.write(chunk)
                    o = 0
            if o:
                f.write(chunk[:o])
        return out_count

    def list_recordings(self):
        try:
            names = sorted(os.listdir(self.audio_dir))
        except OSError:
            return []
        out = []
        for n in names:
            full = self.audio_dir.rstrip("/") + "/" + n
            try:
                out.append((n, os.stat(full)[6]))
            except OSError:
                pass
        return out
