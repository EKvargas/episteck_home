#!/usr/bin/env sh
set -eu
python3 -m pip install --disable-pip-version-check --quiet 'httpx==0.28.1' 'httpcore==1.0.9'
python3 /work/failure_probe.py
