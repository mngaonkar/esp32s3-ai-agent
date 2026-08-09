#!/usr/bin/env python3
"""Build a single flashable image: MicroPython + the agent's filesystem.

The result is written to dist/ and can be flashed at offset 0 in one command,
so a new board needs no mpremote, no per-file copying and no Python tooling.

    python3 tools/build_image.py
    tools/flash.sh dist/esp32s3-agent-<version>.bin

config.json is deliberately NOT included. The board runs its first-boot setup
and asks for the few settings it cannot guess, so the image carries no
credentials and is safe to share.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

# Must match the board's partition table (esp32.Partition):
#   factory app at 0x010000 size 0x1f0000
#   vfs         at 0x200000 size 0x600000, 4096-byte blocks
VFS_OFFSET = 0x200000
BLOCK_SIZE = 4096
BLOCK_COUNT = 0x600000 // BLOCK_SIZE  # 1536

FIRMWARE = os.path.join(ROOT, "firmware", "mpy_cam", "firmware.bin")
VERSION = "1.0.0"


def collect():
    """(archive path, source path) for everything that ships on the board."""
    files = []
    src = os.path.join(ROOT, "src")
    files.append(("main.py", os.path.join(src, "main.py")))
    for name in sorted(os.listdir(os.path.join(src, "agent"))):
        if name.endswith(".py"):
            files.append(("agent/" + name, os.path.join(src, "agent", name)))

    skills_root = os.path.join(src, "skills")
    for skill in sorted(os.listdir(skills_root)):
        sdir = os.path.join(skills_root, skill)
        if not os.path.isdir(sdir):
            continue
        for dirpath, _, filenames in os.walk(sdir):
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, src).replace(os.sep, "/")
                files.append((rel, full))

    certs = os.path.join(ROOT, "certs")
    for name in sorted(os.listdir(certs)):
        full = os.path.join(certs, name)
        if os.path.isfile(full):
            files.append(("certs/" + name, full))
    return files


def build_fs(files, out_path):
    from littlefs import LittleFS

    fs = LittleFS(block_size=BLOCK_SIZE, block_count=BLOCK_COUNT, mount=False)
    fs.format()
    fs.mount()

    made = set()
    for arcname, source in files:
        parts = arcname.split("/")[:-1]
        cur = ""
        for part in parts:
            cur = cur + "/" + part if cur else "/" + part
            if cur not in made:
                try:
                    fs.mkdir(cur)
                except Exception:
                    pass
                made.add(cur)
        with open(source, "rb") as f:
            data = f.read()
        with fs.open("/" + arcname, "wb") as f:
            f.write(data)

    with open(out_path, "wb") as f:
        f.write(fs.context.buffer)
    return out_path


def verify_fs(path, expected):
    """Re-mount the image and confirm every file is present and intact."""
    from littlefs import LittleFS

    data = bytearray(open(path, "rb").read())
    fs = LittleFS(block_size=BLOCK_SIZE, block_count=BLOCK_COUNT, mount=False)
    fs.context.buffer = data
    fs.mount()

    problems = []
    for arcname, source in expected:
        try:
            with fs.open("/" + arcname, "rb") as f:
                got = f.read()
        except Exception as exc:
            problems.append("%s: unreadable (%s)" % (arcname, exc))
            continue
        want = open(source, "rb").read()
        if got != want:
            problems.append("%s: content differs (%d vs %d bytes)"
                            % (arcname, len(got), len(want)))
    return problems


def main():
    if not os.path.exists(FIRMWARE):
        sys.exit("missing firmware: %s" % FIRMWARE)
    os.makedirs(DIST, exist_ok=True)

    files = collect()
    total = sum(os.path.getsize(s) for _, s in files)
    print("==> %d files, %d bytes of payload" % (len(files), total))

    fs_img = os.path.join(DIST, "littlefs.img")
    build_fs(files, fs_img)
    print("--> filesystem image: %s (%d bytes)" % (fs_img, os.path.getsize(fs_img)))

    problems = verify_fs(fs_img, files)
    if problems:
        for p in problems:
            print("!! " + p)
        sys.exit("filesystem image failed verification")
    print("--> verified: all %d files re-read byte-identical" % len(files))

    esptool = os.path.join(ROOT, ".venv", "bin", "esptool")
    if not os.path.exists(esptool):
        esptool = "esptool"
    out = os.path.join(DIST, "esp32s3-agent-%s.bin" % VERSION)
    cmd = [esptool, "--chip", "esp32s3", "merge-bin", "-o", out,
           "--flash-mode", "dio", "--flash-size", "8MB",
           "0x0", FIRMWARE, hex(VFS_OFFSET), fs_img]
    print("--> merging: %s" % " ".join(os.path.basename(c) for c in cmd[:4]))
    subprocess.run(cmd, check=True, capture_output=True)

    os.remove(fs_img)
    print("\n==> %s (%.1f MB)" % (out, os.path.getsize(out) / 1048576))
    print("    flash with: tools/flash.sh")


if __name__ == "__main__":
    main()
