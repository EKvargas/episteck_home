set -eu
test "$(id -un)" = kap2-probe
base=/home/kap2-probe/mariadb-11.8.6
prefix="$base/root"
test ! -e "$base"
mkdir -m 0700 -p "$base/debs" "$prefix" "$base/bin"
cd "$base/debs"
apt download 'mariadb-server=1:11.8.6-5ubuntu0.1' 'mariadb-server-core=1:11.8.6-5ubuntu0.1' 'mariadb-client=1:11.8.6-5ubuntu0.1' 'mariadb-client-core=1:11.8.6-5ubuntu0.1' 'mariadb-common=1:11.8.6-5ubuntu0.1' 'libmariadb3=1:11.8.6-5ubuntu0.1' 'libpcre2-posix3=10.46-1build1'
for deb in ./*.deb; do dpkg-deb --extract "$deb" "$prefix"; done
test -x "$prefix/usr/sbin/mariadbd"
test -x "$prefix/usr/bin/mariadb"
test -x "$prefix/usr/bin/mariadb-admin"
test -x "$prefix/usr/bin/mariadb-install-db"
test -d "$prefix/usr/lib/mysql/plugin"
test -f "$prefix/usr/share/mariadb/mariadb_system_tables.sql"
cat > "$base/bin/mariadbd" <<'WRAP'
#!/bin/sh
exec /home/kap2-probe/mariadb-11.8.6/root/usr/sbin/mariadbd "$@" --basedir=/home/kap2-probe/mariadb-11.8.6/root/usr --plugin-dir=/home/kap2-probe/mariadb-11.8.6/root/usr/lib/mysql/plugin
WRAP
cat > "$base/bin/mariadb-install-db" <<'WRAP'
#!/bin/sh
exec /home/kap2-probe/mariadb-11.8.6/root/usr/bin/mariadb-install-db "$@" --basedir=/home/kap2-probe/mariadb-11.8.6/root/usr
WRAP
ln -s "$prefix/usr/bin/mariadb" "$base/bin/mariadb"
ln -s "$prefix/usr/bin/mariadb-admin" "$base/bin/mariadb-admin"
chmod 0700 "$base/bin/mariadbd" "$base/bin/mariadb-install-db"
export LD_LIBRARY_PATH="$prefix/usr/lib/x86_64-linux-gnu"
export PATH="$base/bin:$PATH"
for cmd in mariadbd mariadb mariadb-admin mariadb-install-db; do command -v "$cmd"; done
if ldd "$prefix/usr/sbin/mariadbd" "$prefix/usr/bin/mariadb" "$prefix/usr/bin/mariadb-admin" | grep 'not found'; then exit 1; fi
mariadbd --version
mariadb --version
mariadb-admin --version
# This pinned script's usage() intentionally exits 1; require real help too.
install_db_help_status=0
install_db_help=$(mariadb-install-db --help) || install_db_help_status=$?
test "$install_db_help_status" -eq 1
printf '%s\n' "$install_db_help" | grep -q '^Usage: .* \[OPTIONS\]$'
printf '%s\n' "$install_db_help" | grep -q -- '--auth-root-authentication-method=normal|socket'
printf '%s\n' "$install_db_help" | grep -q -- '--datadir'
