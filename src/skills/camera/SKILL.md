---
name: camera
description: Take a photo with the board's onboard camera, list photos already saved, and give the user a link to view them. Use whenever the user asks for a picture, photo, snapshot, or to look at or capture something with the camera.
version: 1.0.0
---

# Taking photos

## The camera on this board

A **Seeed XIAO ESP32S3 Sense** with an **OV3660** sensor on the Sense expansion
board. It is confirmed working: the sensor answers on SCCB at address `0x3C`
and reports chip ID `0x3660`.

Note this is *not* the OV2640 usually documented for this board. If you search
the web for help with it, say OV3660 — OV2640 advice will not apply.

## Taking a picture

Call `take_photo`. Both arguments are optional:

- `filename` — e.g. `desk.bmp`. Defaults to a timestamped name.
- `frame_size` — `QVGA` (default) through `UXGA`.

It returns the saved path, dimensions, byte size and a `view_url`.

In the web chat the photo is displayed inline automatically — you do not need
to paste the link for it to appear. Say what you did in one short sentence;
do not describe the image. Include `view_url` only when the user is on the
serial console, or when they ask for the link.

## Photos overwrite by default

Every capture writes to the same file (`latest.bmp`) and replaces the previous
one. That is deliberate: an uncompressed frame is hundreds of kilobytes and
this board has only a few megabytes free, so keeping every shot fills the
filesystem within a handful of captures.

If the user wants to keep a photo, pass an explicit `filename` — that shot is
saved under its own name and survives later captures. Mention this only when
it matters, for instance if they ask to compare two photos or say they want to
keep one.

## You cannot see the photo

You have no vision over this image. `take_photo` returns file metadata, not
picture content.

Never describe what is in the photo, never say whether it is in focus, well
lit, or whether the subject is present. Report that it was taken, where it was
saved, and the link. If the user asks what is in it, say plainly that you
cannot see it and offer the link.

## Choosing a size

Bigger frames cost time and flash. Photos are uncompressed, so size is
predictable: `width x height x 3` bytes plus a small header.

| Frame size | Pixels | File size | Capture time | Roughly |
|---|---|---|---|---|
| `QQVGA` | 160x120 | ~56 KB | ~3 s | thumbnails |
| `QVGA` | 320x240 | ~225 KB | ~7 s | default |
| `VGA` | 640x480 | ~900 KB | ~20 s | good detail |
| `SVGA` | 800x600 | ~1.4 MB | ~30 s | large |
| `HD` and above | | 2.5 MB+ | 45 s+ | rarely worth it |

These are measured, not estimates: converting the frame to BMP runs in Python,
so time scales with pixel count. The filesystem holds only a few megabytes, so
default to `QVGA` and only go larger when the user actually asks for detail.

**Tell the user before capturing anything above QVGA**, with the expected wait.
The whole agent blocks during a capture — the web page and console are both
unresponsive until it finishes — so a silent 30-second stall looks like a
crash.

Run `list_photos` and delete old ones with `write_file`'s sibling tools if
space runs short — a full filesystem makes the next capture fail.

## Why photos are BMP, not JPEG

This sensor's JPEG mode does not work on this firmware. Every JPEG
configuration tested — QVGA through HD, one and two frame buffers, 16/20/24 MHz
clocks, both grab modes — either fails on the first frame or returns nothing,
while RGB565 captures reliably at every size. The agent therefore captures
RGB565 and writes a 24-bit BMP.

BMP opens everywhere, but the files are large and uncompressed. If a user asks
why the photos are not JPEGs, explain this; do not claim JPEG is available.

## Orientation

The camera is mounted rotated on this board, so photos come out **rotated 90
degrees** — a standing person appears lying on their side. This is physical,
not a bug, and the agent does not rotate the image. Mention it when handing
over a photo so the user is not confused by it.

## Warm-up frames

The first frames after power-up come out dark or colour-cast because exposure
and white balance have not settled. `take_photo` discards two frames before
keeping one. If a photo comes back visibly wrong and the user asks for a
retake, simply take another — the sensor will have settled by then.
