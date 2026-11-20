#!/usr/bin/env bash
# One image rollout for Nutrition, Home BFF and Home Hub (rootless Podman Quadlets on the node).
# NOT run by CI, NOT run by an agent: the owner runs the LIVE steps (apply, rollback).
#
#   ssh -F C:/Users/D064974/.ssh/config episteck-node1 'sudo -n bash -s -- <component> <step> [arg]' < deploy/ops/image-rollout.sh
#
# components: nutrition | home-bff | home-hub
# steps:
#   baseline            read-only: running image, ActiveState, NRestarts, sha256 of each live Quadlet
#   build <SHA>         PREP: rootless image build from /home/<account>/build/<SHA>; prints the image ID
#   preview <SHA>       read-only: diff -u of each live Quadlet against the rendered template
#   apply <SHA>         LIVE: back up, render the repo templates, install, diff, reload, restart
#   verify              read-only probes (no secret file or token is ever printed)
#   rollback <backup>   LIVE: restore the backed-up Quadlets byte for byte, reload, restart
# With --lib as the first argument the script only defines its functions (tests).
# Piped over ssh, stdin is the script itself: every command that might read stdin gets </dev/null.
set -euo pipefail

PLACEHOLDER=REPLACE_WITH_COMMIT_SHA

# Per component: ACCOUNT, UNITS (restart order), TEMPLATES (repo paths), IMAGE, BUILD_FILE/BUILD_CTX.
load_component() {
  COMPONENT=${1:-}
  case "$COMPONENT" in
    nutrition)
      ACCOUNT=svc-nutrition
      UNITS="nutrition nutrition-mcp"
      TEMPLATES="deploy/nutrition/nutrition.container deploy/nutrition/nutrition-mcp.container"
      IMAGE=localhost/episteck-nutrition
      BUILD_FILE=services/nutrition/Dockerfile; BUILD_CTX=. ;;
    home-bff)
      ACCOUNT=svc-home-bff
      UNITS="home-bff-mint home-bff"
      TEMPLATES="deploy/home-bff/home-bff-mint.container deploy/home-bff/home-bff.container"
      IMAGE=localhost/episteck-home-bff
      BUILD_FILE=services/home-bff/Dockerfile; BUILD_CTX=. ;;
    home-hub)
      ACCOUNT=svc-home-hub
      UNITS="svc-home-hub"
      TEMPLATES="deploy/home-hub/svc-home-hub.container"
      IMAGE=localhost/episteck-home-hub
      BUILD_FILE=apps/home-hub/Dockerfile; BUILD_CTX=apps/home-hub ;;
    *) echo "usage: <nutrition|home-bff|home-hub> <baseline|build SHA|preview SHA|apply SHA|verify|rollback BACKUP_DIR>" >&2; return 2 ;;
  esac
  QDIR=/home/$ACCOUNT/.config/containers/systemd
}

need_sha() { [[ "${1:-}" =~ ^[0-9a-f]{40}$ ]] || { echo "need the full 40-character lowercase hex merge SHA" >&2; return 2; }; }

# Rootless commands: stdin is /dev/null so nothing swallows the rest of this piped script.
as_account() {
  local account=$1 uid; shift
  uid=$(id -u "$account")
  sudo -n -u "$account" env "XDG_RUNTIME_DIR=/run/user/$uid" \
    "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$uid/bus" "$@" </dev/null
}

# Replace only the placeholder; refuse a template with none or with more than one.
render_quadlet() {
  local tpl=$1 sha=$2 out=$3 n
  n=$(grep -c "$PLACEHOLDER" "$tpl" || true)
  [ "$n" = 1 ] || { echo "STOP: $tpl has $n placeholder lines, need exactly 1" >&2; return 1; }
  sed "s|$PLACEHOLDER|$sha|" "$tpl" > "$out"
}

state() {
  local u
  for u in $UNITS; do
    echo "-- $u"
    as_account "$ACCOUNT" systemctl --user show "$u.service" -p ActiveState -p SubState -p NRestarts
  done
}
reload_restart() {  # returns 1 if any command failed, but always tries every unit and prints the state
  local u rc=0
  as_account "$ACCOUNT" systemctl --user daemon-reload || rc=1
  for u in $UNITS; do as_account "$ACCOUNT" systemctl --user restart "$u.service" || rc=1; done
  sleep 5
  state || true
  return $rc
}
own() { chown "$ACCOUNT:$ACCOUNT" "$1"; }
rollback_cmd() {
  echo "== rollback command"
  echo "ssh -F C:/Users/D064974/.ssh/config episteck-node1 'sudo -n bash -s -- $COMPONENT rollback $1' < deploy/ops/image-rollout.sh"
}

step_baseline() {
  local u t
  for u in $UNITS; do
    echo "== $u"
    as_account "$ACCOUNT" podman ps --filter "name=^$u\$" --format '{{.Image}} {{.ID}} {{.Status}}'
  done
  state
  echo "== live Quadlets (sha256)"
  for t in $TEMPLATES; do sha256sum "$QDIR/$(basename "$t")"; done
}

step_build() {
  local sha=${1:-} dir
  need_sha "$sha"
  dir=/home/$ACCOUNT/build/$sha
  [ -f "$dir/$BUILD_FILE" ] || { echo "STOP: archive not extracted at $dir (see deploy/ops/README.md)" >&2; return 1; }
  as_account "$ACCOUNT" bash -c "cd '$dir' && podman build -q -f $BUILD_FILE -t $IMAGE:$sha $BUILD_CTX"
  as_account "$ACCOUNT" podman image inspect "$IMAGE:$sha" --format '{{.Id}}'
}

# Read-only: show what apply would change. Run it before every apply and read the diff.
step_preview() {
  local sha=${1:-} dir t name tmp rc=0
  need_sha "$sha" || return 2
  dir=${BUILD_BASE:-/home/$ACCOUNT/build}/$sha
  [ -d "$dir" ] || { echo "STOP: archive not extracted at $dir (see deploy/ops/README.md)" >&2; return 1; }
  tmp=$(mktemp -d)
  for t in $TEMPLATES; do
    name=$(basename "$t")
    if [ ! -f "$dir/$t" ]; then echo "STOP: $dir/$t missing" >&2; rc=1; break; fi
    render_quadlet "$dir/$t" "$sha" "$tmp/$name" || { rc=1; break; }
    echo "== diff -u $name (live vs rendered)"
    diff -u "$QDIR/$name" "$tmp/$name" || true
  done
  rm -rf "$tmp"
  return $rc
}

step_apply() {
  local sha=${1:-} dir stamp bk t name live mode tmp
  need_sha "$sha" || return 2
  dir=${BUILD_BASE:-/home/$ACCOUNT/build}/$sha
  as_account "$ACCOUNT" podman image exists "$IMAGE:$sha" || { echo "STOP: image $IMAGE:$sha not built" >&2; return 1; }
  # render everything first: a bad template stops before any live file is touched
  tmp=$(mktemp -d)
  for t in $TEMPLATES; do
    [ -f "$dir/$t" ] || { echo "STOP: $dir/$t missing" >&2; rm -rf "$tmp"; return 1; }
    render_quadlet "$dir/$t" "$sha" "$tmp/$(basename "$t")" || { rm -rf "$tmp"; return 1; }
  done
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  bk=${BACKUP_ROOT:-/var/backups/episteck}/$COMPONENT-${sha:0:7}-$stamp
  install -d -m 700 "$bk"
  for t in $TEMPLATES; do
    name=$(basename "$t"); live=$QDIR/$name
    cp -p "$live" "$bk/$name"
    [ "$(sha256sum < "$live")" = "$(sha256sum < "$bk/$name")" ] || { echo "STOP: backup of $name differs" >&2; return 1; }
    echo "backup OK: $bk/$name  $(sha256sum < "$bk/$name" | cut -c1-64)"
  done
  rollback_cmd "$bk"
  for t in $TEMPLATES; do
    name=$(basename "$t"); live=$QDIR/$name
    mode=$(stat -c %a "$live")
    install -m "$mode" "$tmp/$name" "$live"
    own "$live"
  done
  rm -rf "$tmp"
  for t in $TEMPLATES; do
    name=$(basename "$t")
    echo "== diff -u $name (backup vs new)"; diff -u "$bk/$name" "$QDIR/$name" || true
  done
  if ! reload_restart; then
    echo "FAIL: a restart failed; state above. Roll back now:"
    rollback_cmd "$bk"
    return 1
  fi
  rollback_cmd "$bk"
}

step_verify() {
  local u
  for u in $UNITS; do
    as_account "$ACCOUNT" podman ps --filter "name=^$u\$" --format '{{.Image}} {{.Status}}'
  done
  state
  case "$COMPONENT" in
    nutrition) verify_nutrition ;;
    home-bff) verify_home_bff ;;
    home-hub) verify_home_hub ;;
  esac
  if [ "$FAILS" = 0 ]; then echo "verify: PASS"; else echo "verify: FAIL ($FAILS)"; return 1; fi
}

FAILS=0
check() {  # check <label> <status 0|1>
  if [ "$2" = 0 ]; then echo "ok   $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi
}
http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$@" </dev/null || true; }

verify_nutrition() {
  local c out code rc
  code=$(http_code http://127.0.0.1:9930/health); echo "9930 /health $code"
  rc=0; [ "$code" = 200 ] || rc=1; check "nutrition api health 200" $rc
  code=$(http_code http://127.0.0.1:9931/); echo "9931 / $code"
  rc=0; [ "$code" != 000 ] || rc=1; check "nutrition mcp answers" $rc
  code=$(http_code http://127.0.0.1:9930/profile/PSN-00013); echo "9930 /profile/PSN-00013 (no delegation) $code"
  rc=0; [ "$code" = 401 ] || rc=1; check "person probe without delegation is 401" $rc
  for c in nutrition nutrition-mcp; do
    echo "$c BLS_DB=$(as_account "$ACCOUNT" podman exec "$c" printenv BLS_DB || echo unset)"
    out=$(as_account "$ACCOUNT" podman exec "$c" python -c "from app.deps import _build_provider; print(_build_provider().search_food('Apfel')[0].food_id)" 2>/dev/null || true)
    case "$out" in bls:*) check "$c food id starts with bls:" 0 ;; *) FAILS=$((FAILS + 1)); echo "FAIL $c food id does not start with bls:" ;; esac
  done
}

verify_home_bff() {
  local code rc
  code=$(http_code http://127.0.0.1:9933/health); echo "9933 /health $code"
  rc=0; [ "$code" = 200 ] || rc=1; check "home-bff health 200" $rc
  code=$(sudo -n -u svc-home-gateway curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
    --unix-socket /run/episteck/home-bff-mint/mint.sock -X POST http://x/internal/mint </dev/null || true)
  echo "mint socket without X-Runtime-ID $code"
  rc=0; [ "$code" = 401 ] || rc=1; check "mint answers 401 without X-Runtime-ID" $rc
}

HUB_HEALTH='const p=process.argv[1]; fetch(`http://127.0.0.1:${p}/health`).then(r=>{console.log(p,r.status);process.exit(r.status===200?0:1)}).catch(()=>{console.log(p,"unreachable");process.exit(1)})'
HUB_REFUSED='const net=require("node:net");let bad=false;Promise.all([9931,9932,9934].map(port=>new Promise(res=>{const s=net.createConnection({host:"127.0.0.1",port,timeout:1500});s.once("connect",()=>{console.error("UNEXPECTED reachable",port);bad=true;s.destroy();res()});s.once("error",res);s.once("timeout",()=>{s.destroy();res()})}))).then(()=>{console.log(bad?"isolation FAIL":"9931 9932 9934 refused");process.exit(bad?1:0)})'

verify_home_hub() {
  local p code rc
  for p in 9933 9930; do
    rc=0; as_account "$ACCOUNT" podman exec svc-home-hub node -e "$HUB_HEALTH" "$p" || rc=1; check "hub reaches $p" $rc
  done
  rc=0; as_account "$ACCOUNT" podman exec svc-home-hub node -e "$HUB_REFUSED" || rc=1; check "9931 9932 9934 refused" $rc
  code=$(http_code http://127.0.0.1:9940/app/nutrition); echo "9940 /app/nutrition anonymous $code"
  rc=0; [ "$code" = 307 ] || rc=1; check "anonymous /app/nutrition is 307" $rc
}

step_rollback() {
  local bk=${1:-} t name base
  base=$(basename "$bk")
  case "$base" in "$COMPONENT"-*) ;; *) echo "STOP: $bk is not a $COMPONENT backup" >&2; return 1 ;; esac
  for t in $TEMPLATES; do
    [ -f "$bk/$(basename "$t")" ] || { echo "STOP: $bk/$(basename "$t") missing" >&2; return 1; }
  done
  for t in $TEMPLATES; do
    name=$(basename "$t")
    install -m "$(stat -c %a "$QDIR/$name")" "$bk/$name" "$QDIR/$name"
    own "$QDIR/$name"
    sha256sum "$bk/$name" "$QDIR/$name"
  done
  reload_restart || { echo "FAIL: a restart failed; state above" >&2; return 1; }
}

main() {
  load_component "${1:-}" || return $?
  case "${2:-}" in
    baseline) step_baseline ;;
    build) step_build "${3:-}" ;;
    preview) step_preview "${3:-}" ;;
    apply) step_apply "${3:-}" ;;
    verify) step_verify ;;
    rollback) step_rollback "${3:-}" ;;
    *) echo "unknown step: ${2:-}" >&2; return 2 ;;
  esac
}

if [ "${1:-}" = "--lib" ]; then
  return 0 2>/dev/null || exit 0
fi
# sudo -u into a service account cannot enter /home/episteck
cd /
main "$@"
