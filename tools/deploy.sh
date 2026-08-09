#!/usr/bin/env bash
# Copy the agent source, skills and CA cert to the board.
#
#   tools/deploy.sh              push code (leaves /config.json alone)
#   tools/deploy.sh --config     also push ./config.json, overwriting the board's
#
# config.json holds credentials and is never pushed unless asked for explicitly.
set -euo pipefail

cd "$(dirname "$0")/.."

# Auto-detect: the node name changes when the board re-enumerates
# (usbmodem1101 vs usbmodem101), so do not hardcode it.
PORT="${PORT:-$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)}"
if [[ -z "$PORT" ]]; then echo "no /dev/cu.usbmodem* found - is the board plugged in?" >&2; exit 1; fi
MPR="${MPR:-.venv/bin/mpremote}"
MP="$MPR connect $PORT"

push_config=false
[[ "${1:-}" == "--config" ]] && push_config=true

echo "==> deploying to $PORT"

# Stop any running main.py so the filesystem is not busy.
$MP exec "import sys" >/dev/null 2>&1 || true

echo "--> directories"
for d in :agent :skills :certs; do
  $MP mkdir "$d" >/dev/null 2>&1 || true
done
# Derived from the tree, so a newly added skill needs no edit here.
for skill_dir in src/skills/*/; do
  name=$(basename "$skill_dir")
  $MP mkdir ":skills/$name" >/dev/null 2>&1 || true
  if compgen -G "${skill_dir}scripts/*.py" >/dev/null; then
    $MP mkdir ":skills/$name/scripts" >/dev/null 2>&1 || true
  fi
done

echo "--> agent package"
$MP cp src/main.py :main.py
for f in src/agent/*.py; do
  $MP cp "$f" ":agent/$(basename "$f")"
done

echo "--> skills"
for skill_dir in src/skills/*/; do
  name=$(basename "$skill_dir")
  $MP cp "${skill_dir}SKILL.md" ":skills/$name/SKILL.md"
  if compgen -G "${skill_dir}scripts/*.py" >/dev/null; then
    for f in "${skill_dir}"scripts/*.py; do
      $MP cp "$f" ":skills/$name/scripts/$(basename "$f")"
    done
  fi
done

echo "--> CA trust bundle"
for cert in certs/*; do
  [[ -f "$cert" ]] && $MP cp "$cert" ":certs/$(basename "$cert")"
done

if $push_config; then
  if [[ -f config.json ]]; then
    echo "--> config.json"
    echo "    NOTE: overwrites the board's copy, discarding any edits made in"
    echo "    the web Config screen. Plain 'deploy.sh' leaves it untouched."
    $MP cp config.json :config.json
  else
    echo "!! config.json not found; copy config.example.json and fill it in" >&2
    exit 1
  fi
fi

echo "==> done. Open the console with: tools/console.sh"
