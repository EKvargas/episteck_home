#!/bin/bash
# Local-only A1-A11 loopback: witness inside the replica (Python 3.14 / MariaDB 11.8.6),
# Home runner on the host as in the real topology (Python 3.12 / MariaDB 10.11).
# Requires: podman, and HOME_PY = a host Python with PyMySQL, pytest and cryptography.
# Keeps the witness MariaDB error log and session state before stopping the witness.
set -uo pipefail
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
HOME_PY=${HOME_PY:?set HOME_PY to the host Home-runner python}
IMAGE=${KAP2_REPLICA_IMAGE:-localhost/kap2-witness-replica:11.8.6}
podman image exists "$IMAGE" || podman build -t "$IMAGE" "$(dirname "$0")"
TAG=replica-$(date +%Y%m%d-%H%M%S)
CERTS=/tmp/kap2-pr71-certs-local-$TAG
WROOT=/tmp/kap2-pr71-twohost-local-w-$TAG
HROOT=/tmp/kap2-pr71-twohost-local-h-$TAG
OUT=/tmp/kap2-replica-evidence-$TAG
NAME=kap2-witness-$TAG
mkdir -p "$OUT"
export PYTHONPATH="$REPO/apps/episteck_home:$REPO/packages/home-contracts/src${HOME_PYTHONPATH:+:$HOME_PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
cd "$REPO/spike/knowledge-kap2-two-host"
"$HOME_PY" certs.py --out "$CERTS" --server-ip 127.0.0.1 --local > "$OUT/certs.log" 2>&1 \
  || { echo CERTS_FAILED; exit 1; }
podman run -d --rm --name "$NAME" --network host --userns=keep-id --user "$(id -u):$(id -g)" \
  -v "$REPO:$REPO:ro" -v "$CERTS:$CERTS:ro" -v "$OUT:$OUT" -w "$PWD" "$IMAGE" \
  python3 witness_runner.py --root "$WROOT" --evidence "$OUT/witness.jsonl" --bind 127.0.0.1 \
  --loopback-only --port 19442 --ca "$CERTS/ca.crt" --cert "$CERTS/server.crt" \
  --key "$CERTS/server.key" > /dev/null || { echo WITNESS_START_FAILED; exit 1; }
for _ in $(seq 150); do grep -q listener_ready "$OUT/witness.jsonl" 2>/dev/null && break; sleep 0.2; done
"$HOME_PY" home_runner.py --root "$HROOT" --evidence "$OUT/home.jsonl" --witness-host 127.0.0.1 \
  --port 19442 --ca "$CERTS/ca.crt" --serving-cert "$CERTS/serving.crt" \
  --serving-key "$CERTS/serving.key" --recovery-cert "$CERTS/recovery.crt" \
  --recovery-key "$CERTS/recovery.key" --local > "$OUT/home.log" 2>&1
echo "HOME_EXIT=$?"
podman exec "$NAME" bash -c "cp $WROOT/db/log.err $OUT/mariadb-error.log 2>/dev/null; \
  mariadb --no-defaults --socket=$WROOT/db/db.sock -uroot -N -B -e \
  \"SELECT ID,USER,COMMAND FROM information_schema.PROCESSLIST WHERE USER LIKE 'gw%'; \
    SHOW GLOBAL STATUS WHERE Variable_name IN ('Aborted_clients','Com_kill');\" \
  > $OUT/witness-db.txt 2>&1" || true
podman logs "$NAME" > "$OUT/witness.stdout.log" 2>&1
podman kill --signal TERM "$NAME" > /dev/null 2>&1
for _ in $(seq 100); do podman container exists "$NAME" || break; sleep 0.2; done
rm -rf "$CERTS"
grep -h '"result"' "$OUT/home.jsonl" | cut -c1-200
grep -h 'latency_distribution' "$OUT/home.jsonl" | cut -c1-400
echo "EVIDENCE=$OUT"
