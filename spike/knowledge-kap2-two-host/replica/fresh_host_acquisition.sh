#!/bin/bash
# Local proof of the dedicated witness host's preparation (decision 2026-11-10): on a fresh
# Ubuntu 26.04 system whose apt source is pinned to Ubuntu's snapshot archive, the reviewed
# acquire_mariadb.sh runs UNMODIFIED as a non-sudo kap2-probe user. Also reports whether the
# live archive still offers the pinned version (the A0 timing risk). Needs network access.
set -u
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../.." && pwd)
image='docker.io/library/ubuntu:26.04@sha256:6a06111c3b0a8600feadb270aec771dc239bf407b25625f93f44ab00e11f4d3c'
snapshot=${UBUNTU_SNAPSHOT:-20261109T000000Z}
libs='liburing2 libaio1t64 libnuma1 libedit2 libncurses6'
inner=$(mktemp)
trap 'rm -f "$inner"' EXIT
cat > "$inner" <<INNER
set -eu -o pipefail
export DEBIAN_FRONTEND=noninteractive
echo "== control: live archive candidate today"
apt-get update -qq
apt-cache policy mariadb-server | sed -n '3p'
apt-get install -y -qq ca-certificates >/dev/null
echo "== host prep 1: apt source pinned to snapshot $snapshot"
rm -f /etc/apt/sources.list.d/*.sources /etc/apt/sources.list
cat > /etc/apt/sources.list.d/kap2-snapshot.sources <<SRC
Types: deb
URIs: https://snapshot.ubuntu.com/ubuntu/$snapshot
Suites: resolute resolute-updates resolute-security
Components: main restricted universe
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
SRC
rm -rf /var/lib/apt/lists/*
apt-get update -qq
apt-cache policy mariadb-server | sed -n '3p'
echo "== host prep 2: runtime libraries the extracted binaries link against"
apt-get install -y -qq --no-install-recommends $libs >/dev/null
dpkg-query -W -f='\${Package} \${Version}\n' $libs
echo "== host prep 3: transient non-sudo account"
useradd -m -s /bin/sh kap2-probe
echo "== reviewed acquire_mariadb.sh as kap2-probe (unmodified)"
install -m 0755 /src/spike/knowledge-kap2-two-host/acquire_mariadb.sh /tmp/acquire_mariadb.sh
cd /home/kap2-probe
su kap2-probe -c 'sh /tmp/acquire_mariadb.sh' | tail -3
echo "ACQUIRE=PASS"
INNER
podman run --rm --network host -v "$repo":/src:ro -v "$inner":/inner.sh:ro "$image" bash /inner.sh
status=$?
echo "FRESH_HOST_ACQUISITION_EXIT=$status"
exit "$status"
