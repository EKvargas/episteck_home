#!/usr/bin/env bash
set -euo pipefail
BASE=${1:?pass exact temporary directory}
case "$BASE" in
  /home/frappe/knowledge-transport.????????) ;;
  *) echo 'refusing unexpected cleanup path' >&2; exit 1 ;;
esac
test -d "$BASE"
for name in nginx-shell gunicorn; do
  pid=$(cat "$BASE/${name}.pid")
  if ps -p "$pid" -o args= | grep -Eq 'nginx|gunicorn'; then
    kill "$pid"
  fi
done
sleep 1
if ss -ltn | grep -Eq '(100.71.79.33:18473|127.0.0.1:18474)'; then
  echo 'temporary listener still open; preserving evidence directory' >&2
  exit 1
fi
rm -rf -- "$BASE"
echo 'temporary Home transport seam removed'
