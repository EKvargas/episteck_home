#!/bin/bash
# Run pytest inside the witness replica against this checkout (read-only mount, no network).
# Usage (from the repo root): spike/knowledge-kap2-two-host/replica/run_pytest.sh <pytest args>
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
IMAGE=${KAP2_REPLICA_IMAGE:-localhost/kap2-witness-replica:11.8.6}
podman image exists "$IMAGE" || podman build -t "$IMAGE" "$(dirname "$0")"
exec podman run --rm --network none --userns=keep-id --user "$(id -u):$(id -g)" \
  -v "$REPO:$REPO:ro" -w "$REPO" -e TMPDIR=/tmp \
  -e PYTHONPATH="/deps:$REPO/apps/episteck_home:$REPO/packages/home-contracts/src" \
  "$IMAGE" python3 -m pytest -p no:cacheprovider "$@"
