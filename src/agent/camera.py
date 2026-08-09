"""OV3660 camera capture for the XIAO ESP32S3 Sense.

Runs on the cnadler86 micropython-camera-API build. That build is generic, so
the XIAO wiring is supplied from config; it is used because it detects this
board's OV3660, which the Seeed/shariltumin "kaki5" build does not -- that one
compiles in an OV2640-only detection path and rejects this sensor.

Photos are saved as 24-bit BMP rather than JPEG. That is not a preference:
this sensor's JPEG path does not work on this driver build. Every JPEG
configuration tried (QVGA through HD, fb_count 1 and 2, xclk 16/20/24 MHz,
both grab modes, and reconfigure-after-init) either failed on the first frame
or returned None, while RGB565 captured reliably at every size.

The camera is initialised per shot and released afterwards. Its frame buffers
are large, and holding them for the lifetime of a long-running agent costs
PSRAM for a peripheral used occasionally.
"""

import gc
import os
import struct
import time

_FRAME_SIZES = ("QQVGA", "QVGA", "HVGA", "VGA", "SVGA", "XGA", "HD", "SXGA", "UXGA")


class CameraError(Exception):
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


def _bmp_header(width, height):
    """24-bit BMP, bottom-up."""
    row_bytes = width * 3
    pad = (4 - row_bytes % 4) % 4
    pixel_bytes = (row_bytes + pad) * height
    hdr = bytearray(54)
    hdr[0:2] = b"BM"
    struct.pack_into("<I", hdr, 2, 54 + pixel_bytes)
    struct.pack_into("<I", hdr, 10, 54)
    struct.pack_into("<I", hdr, 14, 40)
    struct.pack_into("<i", hdr, 18, width)
    struct.pack_into("<i", hdr, 22, height)
    struct.pack_into("<H", hdr, 26, 1)
    struct.pack_into("<H", hdr, 28, 24)
    struct.pack_into("<I", hdr, 34, pixel_bytes)
    return hdr, pad


class CameraDevice:
    def __init__(self, cfg):
        self.cfg = cfg
        self.pins = cfg.get("camera_pins") or {}
        self.photo_dir = cfg.get("photo_dir", "/photos")

    @property
    def enabled(self):
        return bool(self.cfg.get("camera_enabled"))

    def _open(self, frame_size):
        from camera import Camera, FrameSize, PixelFormat, GrabMode

        size = getattr(FrameSize, frame_size, None)
        if size is None:
            raise CameraError("unknown frame size '%s'; use one of %s"
                              % (frame_size, ", ".join(_FRAME_SIZES)))

        p = self.pins
        cam = Camera(
            data_pins=p.get("data", [15, 17, 18, 16, 14, 12, 11, 48]),
            vsync_pin=p.get("vsync", 38),
            href_pin=p.get("href", 47),
            sda_pin=p.get("sda", 40),
            scl_pin=p.get("scl", 39),
            pclk_pin=p.get("pclk", 13),
            xclk_pin=p.get("xclk", 10),
            xclk_freq=p.get("xclk_freq", 20000000),
            powerdown_pin=p.get("pwdn", -1),
            reset_pin=p.get("reset", -1),
            pixel_format=PixelFormat.RGB565,
            frame_size=size,
            fb_count=1,
            grab_mode=GrabMode.WHEN_EMPTY,
        )
        cam.init()
        return cam

    def capture(self, path=None, frame_size=None, warmup=6, flip=False):
        """Capture one frame and write it as a BMP. Returns a summary dict."""
        if not self.enabled:
            raise CameraError("camera_enabled is false in /config.json")

        frame_size = (frame_size or self.cfg.get("camera_frame_size", "QVGA")).upper()

        if not path:
            if self.cfg.get("photo_overwrite", True):
                # One reused filename by default: an uncompressed frame is
                # hundreds of KB and this filesystem has only a few MB, so
                # timestamped shots fill it within a handful of captures.
                path = "%s/%s" % (self.photo_dir.rstrip("/"),
                                  self.cfg.get("photo_name", "latest.bmp"))
            else:
                t = time.localtime()
                path = "%s/photo-%04d%02d%02d-%02d%02d%02d.bmp" % (
                    self.photo_dir.rstrip("/"), t[0], t[1], t[2], t[3], t[4], t[5])
        if not path.startswith("/"):
            path = self.photo_dir.rstrip("/") + "/" + path
        if not path.lower().endswith(".bmp"):
            path += ".bmp"
        _ensure_dir(path.rsplit("/", 1)[0])

        gc.collect()
        cam = None
        try:
            cam = self._open(frame_size)
            sensor = cam.get_sensor_name()

            # Auto-exposure and auto-white-balance converge over the first
            # several frames. Capturing too early is the single biggest cause
            # of a bad photo here: the frame is structurally fine but wildly
            # colour-cast, which looks like a decoding bug and is not one.
            time.sleep_ms(300)
            for _ in range(max(0, int(warmup))):
                cam.capture()
                time.sleep_ms(200)

            buf = cam.capture()
            if not buf:
                raise CameraError("sensor returned no frame")
            width, height = cam.get_pixel_width(), cam.get_pixel_height()
            # Copy before deinit. capture() hands back a view of the driver's
            # frame buffer, and deinit frees it -- encoding from it afterwards
            # reads recycled memory, which yields an image that keeps its
            # structure but has wildly wrong colour.
            frame = bytes(buf)
            buf = None
        finally:
            if cam:
                try:
                    cam.deinit()
                except Exception:
                    pass

        started = time.ticks_ms()
        written = self._write_bmp(path, frame, width, height, flip)
        elapsed = time.ticks_diff(time.ticks_ms(), started)
        del frame
        gc.collect()

        return {
            "path": path,
            "bytes": written,
            "width": width,
            "height": height,
            "sensor": sensor,
            "format": "BMP24",
            "encode_ms": elapsed,
        }

    def _write_bmp(self, path, buf, width, height, flip):
        hdr, pad = _bmp_header(width, height)
        mv = memoryview(buf)
        row = bytearray(width * 3)
        padding = b"\x00" * pad
        stride = width * 2

        with open(path, "wb") as f:
            f.write(hdr)
            # BMP rows run bottom-to-top, so walk the frame in reverse unless
            # the image comes out upside down for a given mounting.
            rows = range(height) if flip else range(height - 1, -1, -1)
            for y in rows:
                base = y * stride
                o = 0
                for x in range(0, stride, 2):
                    # esp32-camera emits RGB565 big-endian; BMP wants BGR.
                    p = (mv[base + x] << 8) | mv[base + x + 1]
                    row[o] = (p & 0x1F) << 3
                    row[o + 1] = ((p >> 5) & 0x3F) << 2
                    row[o + 2] = ((p >> 11) & 0x1F) << 3
                    o += 3
                f.write(row)
                if pad:
                    f.write(padding)

        return os.stat(path)[6]

    def list_photos(self):
        try:
            names = sorted(os.listdir(self.photo_dir))
        except OSError:
            return []
        out = []
        for n in names:
            full = self.photo_dir.rstrip("/") + "/" + n
            try:
                out.append((n, os.stat(full)[6]))
            except OSError:
                pass
        return out
