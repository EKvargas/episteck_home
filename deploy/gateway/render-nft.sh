#!/bin/sh
set -eu

template=${1:-deploy/gateway/episteck-gateway.nft}
output=${2:-/dev/stdout}
gateway_uid=$(id -u svc-home-gateway)
www_data_uid=$(id -u www-data)
ana_uid=$(id -u home-agent-ana)
for uid in "$gateway_uid" "$www_data_uid" "$ana_uid"; do
    case "$uid" in
        ''|*[!0-9]*) echo "a rendered uid is not numeric" >&2; exit 2 ;;
    esac
done
sed -e "s/__SVC_HOME_GATEWAY_UID__/${gateway_uid}/g" \
    -e "s/__WWW_DATA_UID__/${www_data_uid}/g" \
    -e "s/__HOME_AGENT_ANA_UID__/${ana_uid}/g" "$template" > "$output"
printf '%s\n' "rendered svc-home-gateway uid=${gateway_uid} www-data uid=${www_data_uid} home-agent-ana uid=${ana_uid}" >&2
