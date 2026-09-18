#!/bin/sh
set -eu

template=${1:-deploy/gateway/episteck-gateway.nft}
output=${2:-/dev/stdout}
gateway_uid=$(id -u svc-home-gateway)
case "$gateway_uid" in
    ''|*[!0-9]*) echo "svc-home-gateway uid is not numeric" >&2; exit 2 ;;
esac
sed "s/__SVC_HOME_GATEWAY_UID__/${gateway_uid}/g" "$template" > "$output"
printf '%s\n' "rendered svc-home-gateway uid=${gateway_uid}" >&2
