---
name: camera
description: Take a photo with the board's onboard camera, list saved photos,
  show them in the web UI, and analyse what is in a photo via the vision model.
  Use whenever the user asks for a picture, photo, snapshot, what the camera
  sees, to describe an image, or to look at something with the camera.
version: 1.2.0
---

# Taking and analysing photos

## The camera on this board

A **Seeed XIAO ESP32S3 Sense** with an **OV3660** sensor (not OV2640). SCCB
`0x3C`, chip id `0x3660`.

## Taking a picture

Call `take_photo`. Optional args:

- `filename` — e.g. `desk.bmp`. Default reuses `latest.bmp` (overwrites).
- `frame_size` — `QQVGA`, `QVGA` (default), `VGA`, …

Returns path, size, and `view_url`. In **web chat** the image is shown inline.
On serial, give the user `view_url`.

If you will **analyse** the photo next, prefer **QVGA** or **QQVGA** so the
upload stays small and fast.

## Analysing a photo (vision)

You **can** see the image by calling `analyze_photo` after capture (or on an
existing path under `/photos/`). That tool converts the BMP to PNG, sends it to
the chat model with vision, and returns a text description.

Use it when the user asks:

- what is in the photo / what do you see  
- describe the scene, read text/labels, count objects  
- anything that needs looking at the picture  

Typical flow:

1. `take_photo` (optional `frame_size`: `QVGA`)
2. `analyze_photo` with `path` from the result (or omit path for latest) and an
   optional `question` focused on what they asked
3. Answer the user from the analysis text; do **not** invent scene details
   without calling `analyze_photo`

`analyze_photo` needs a **vision-capable model** in Config (e.g. `gpt-4o-mini`
or `gpt-4o`). If the API rejects the request, say so and suggest switching model.

## You cannot invent vision without the tool

Do not claim to see the image from `take_photo` metadata alone. Metadata is
path/size only. Always use `analyze_photo` for content.

## Photos overwrite by default

Default name reuses one file so flash does not fill up. Pass an explicit
`filename` to keep a shot. Free space with `delete_file` under `/photos/` if
needed.

## Size and time

| Frame size | ~file size | ~encode time |
|---|---|---|
| `QQVGA` | ~56 KB | ~3 s |
| `QVGA` | ~225 KB | ~7 s |
| `VGA` | ~900 KB | ~20 s |

Warn before capturing above QVGA. The agent blocks during capture.

Photos are **BMP** (RGB565 path works; JPEG does not on this firmware). Vision
upload converts to PNG automatically.

## Warm-up

The capture path discards early frames so exposure can settle. Retake if the
user says the shot looks wrong.
