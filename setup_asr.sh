#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install 'vosk==0.3.45'
.venv/bin/python setup_asr.py "${1:-zh}"
printf '\nReady. Start with: .venv/bin/python server.py\n'
