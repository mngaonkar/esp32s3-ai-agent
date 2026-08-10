"""Encode board photos for OpenAI-compatible vision APIs.

Photos on disk are 24-bit BMP. Vision endpoints accept PNG/JPEG/WebP/GIF,
not BMP, so this module converts BMP -> PNG and base64 for a data URL.
"""

import gc
import struct

try:
    import zlib
except ImportError:
    zlib = None

try:
    import ubinascii
except ImportError:
    import binascii as ubinascii


class VisionError(Exception):
    pass


def _b64(data):
    raw = ubinascii.b2a_base64(data)
    if isinstance(raw, bytes):
        raw = raw.decode()
    return raw.replace("\n", "").replace("\r", "")


def _crc32(data):
    try:
        import binascii
        return binascii.crc32(data) & 0xFFFFFFFF
    except Exception:
        raise VisionError("binascii.crc32 required to encode PNG")


def _adler32(data):
    a, b = 1, 0
    for i in range(len(data)):
        a = (a + data[i]) % 65521
        b = (b + a) % 65521
    return (b << 16) | a


def _zlib_store(data):
    """zlib-wrapped DEFLATE with stored (uncompressed) blocks -- no zlib lib."""
    out = bytearray()
    # CMF/FLG: deflate, 32K window, no dict; 0x7801 % 31 == 0
    out.append(0x78)
    out.append(0x01)
    i = 0
    n = len(data)
    while i < n:
        chunk_len = n - i
        if chunk_len > 65535:
            chunk_len = 65535
        i_next = i + chunk_len
        bfinal = 1 if i_next >= n else 0
        # BFINAL + BTYPE=00, already byte-aligned
        out.append(bfinal)
        out.append(chunk_len & 0xFF)
        out.append((chunk_len >> 8) & 0xFF)
        nlen = chunk_len ^ 0xFFFF
        out.append(nlen & 0xFF)
        out.append((nlen >> 8) & 0xFF)
        out.extend(data[i:i_next])
        i = i_next
    adler = _adler32(data)
    out.append((adler >> 24) & 0xFF)
    out.append((adler >> 16) & 0xFF)
    out.append((adler >> 8) & 0xFF)
    out.append(adler & 0xFF)
    return bytes(out)


def _compress_png_raw(raw_bytes):
    if zlib is not None:
        try:
            return zlib.compress(raw_bytes, 1)
        except TypeError:
            return zlib.compress(raw_bytes)
        except Exception:
            pass
    try:
        import deflate
        import io
        buf = io.BytesIO()
        # wbits=15 zlib wrapper; write mode compresses
        d = deflate.DeflateIO(buf, deflate.ZLIB if hasattr(deflate, "ZLIB") else 15)
        d.write(raw_bytes)
        d.close()
        return buf.getvalue()
    except Exception:
        pass
    return _zlib_store(raw_bytes)


def _png_chunk(tag, data):
    out = struct.pack(">I", len(data)) + tag + data
    out += struct.pack(">I", _crc32(tag + data))
    return out


def rgb_to_png(width, height, rgb):
    """rgb: bytes/bytearray length width*height*3, top-down RGB."""
    row = width * 3
    if len(rgb) < row * height:
        raise VisionError("RGB buffer too short for %dx%d" % (width, height))

    # PNG filter 0 (None) per row, then zlib/deflate.
    raw = bytearray((row + 1) * height)
    o = 0
    for y in range(height):
        raw[o] = 0
        o += 1
        start = y * row
        raw[o:o + row] = rgb[start:start + row]
        o += row

    raw_bytes = bytes(raw)
    del raw
    gc.collect()
    compressed = _compress_png_raw(raw_bytes)
    del raw_bytes
    gc.collect()

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", ihdr)
    png += _png_chunk(b"IDAT", compressed)
    png += _png_chunk(b"IEND", b"")
    return png


def read_bmp24(path):
    """Return (width, height, rgb_top_down) from a 24-bit BMP."""
    with open(path, "rb") as f:
        hdr = f.read(54)
        if len(hdr) < 54 or hdr[0:2] != b"BM":
            raise VisionError("not a BMP file: %s" % path)
        width = struct.unpack_from("<i", hdr, 18)[0]
        height = struct.unpack_from("<i", hdr, 22)[0]
        bpp = struct.unpack_from("<H", hdr, 28)[0]
        data_off = struct.unpack_from("<I", hdr, 10)[0]
        if bpp != 24:
            raise VisionError("only 24-bit BMP supported (got %d bpp)" % bpp)
        if width <= 0:
            raise VisionError("invalid BMP width")

        bottom_up = height > 0
        height = abs(height)
        row_bytes = width * 3
        pad = (4 - (row_bytes % 4)) % 4
        stride = row_bytes + pad

        f.seek(data_off)
        pixel = f.read(stride * height)
        if len(pixel) < stride * height:
            raise VisionError("truncated BMP pixel data")

    rgb = bytearray(width * height * 3)
    for y in range(height):
        # BMP rows are bottom-up when height > 0
        src_y = (height - 1 - y) if bottom_up else y
        src = src_y * stride
        dst = y * row_bytes
        # BGR -> RGB
        for x in range(width):
            i = src + x * 3
            o = dst + x * 3
            rgb[o] = pixel[i + 2]
            rgb[o + 1] = pixel[i + 1]
            rgb[o + 2] = pixel[i]
    del pixel
    gc.collect()
    return width, height, rgb


def downscale_rgb(width, height, rgb, max_side=320):
    """Integer-box downscale so the long side is <= max_side."""
    long_side = width if width >= height else height
    if long_side <= max_side:
        return width, height, rgb
    factor = (long_side + max_side - 1) // max_side
    if factor < 2:
        return width, height, rgb
    nw = max(1, width // factor)
    nh = max(1, height // factor)
    out = bytearray(nw * nh * 3)
    for y in range(nh):
        for x in range(nw):
            # sample one pixel (nearest) — fast enough on MCU
            sx = min(width - 1, x * factor + factor // 2)
            sy = min(height - 1, y * factor + factor // 2)
            si = (sy * width + sx) * 3
            di = (y * nw + x) * 3
            out[di] = rgb[si]
            out[di + 1] = rgb[si + 1]
            out[di + 2] = rgb[si + 2]
    return nw, nh, out


def photo_data_url(path, max_side=320):
    """Load a board photo and return (data_url, width, height, png_bytes)."""
    path = path or ""
    if not path.startswith("/"):
        raise VisionError("path must be absolute")
    low = path.lower()
    if not (low.endswith(".bmp") or low.endswith(".png") or low.endswith(".jpg")
            or low.endswith(".jpeg")):
        raise VisionError("unsupported image type: %s" % path)

    gc.collect()
    if low.endswith(".bmp"):
        w, h, rgb = read_bmp24(path)
        w, h, rgb = downscale_rgb(w, h, rgb, max_side=max_side)
        png = rgb_to_png(w, h, rgb)
        del rgb
        gc.collect()
        b64 = _b64(png)
        url = "data:image/png;base64," + b64
        return url, w, h, len(png)

    # Already PNG/JPEG: send as-is (capped by size).
    with open(path, "rb") as f:
        data = f.read()
    if len(data) > 400000:
        raise VisionError("image too large to upload (%d bytes)" % len(data))
    mime = "image/png" if low.endswith(".png") else "image/jpeg"
    url = "data:%s;base64,%s" % (mime, _b64(data))
    return url, 0, 0, len(data)
