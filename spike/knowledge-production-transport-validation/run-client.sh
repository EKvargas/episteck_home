#!/usr/bin/env sh
set -eu
python3 -m pip install --disable-pip-version-check --quiet 'httpx==0.28.1' 'httpcore==1.0.9'
python3 /work/client.py \
  --url https://100.71.79.33:18473/probe \
  --ca /work/ca.pem \
  --samples 30 \
  --output /work/baseline-v2.jsonl
