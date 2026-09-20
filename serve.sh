#!/usr/bin/env bash
# Serve the project page with byte-range support (see serve.py), so the videos
# are seekable and start playing before they have finished downloading.
#
#   ./serve.sh          # http://localhost:8800
#   ./serve.sh 9001     # different port
set -eu
cd "$(dirname "$0")"
PY="${PY:-$HOME/miniconda3/envs/puzzles/bin/python}"
[ -x "$PY" ] || PY=python3
exec "$PY" serve.py "${1:-8800}"
