#!/usr/bin/env bash
set -euo pipefail

HOME_IP=100.71.79.33
TLS_PORT=18473
APP_PORT=18474
if ss -ltn | grep -Eq "(${HOME_IP}:${TLS_PORT}|127.0.0.1:${APP_PORT})"; then
  echo 'temporary port already occupied' >&2
  exit 1
fi
BASE=$(mktemp -d /home/frappe/knowledge-transport.XXXXXXXX)
chmod 700 "$BASE"
cp "$(dirname "$0")/server.py" "$BASE/server.py"
openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 2 \
  -keyout "$BASE/key.pem" -out "$BASE/cert.pem" \
  -subj '/CN=knowledge-transport-disposable' \
  -addext "subjectAltName=IP:${HOME_IP}" \
  -addext 'basicConstraints=critical,CA:TRUE' >/dev/null 2>&1
chmod 600 "$BASE/key.pem"
cat > "$BASE/nginx.conf" <<EOF
worker_processes 1;
pid ${BASE}/nginx.pid;
error_log ${BASE}/nginx-error.log notice;
events { worker_connections 128; }
http {
  default_type application/octet-stream;
  sendfile on;
  tcp_nopush on;
  gzip on;
  gzip_min_length 256;
  gzip_types application/json;
  server {
    listen ${HOME_IP}:${TLS_PORT} ssl;
    server_name knowledge-transport-disposable;
    ssl_certificate ${BASE}/cert.pem;
    ssl_certificate_key ${BASE}/key.pem;
    keepalive_timeout 15;
    client_body_buffer_size 16k;
    proxy_buffer_size 128k;
    proxy_buffers 4 256k;
    proxy_busy_buffers_size 256k;
    access_log off;
    location = /probe {
      proxy_http_version 1.1;
      proxy_set_header Host home.episteck.com;
      proxy_set_header Connection close;
      proxy_request_buffering on;
      proxy_buffering on;
      proxy_pass http://127.0.0.1:${APP_PORT};
    }
    location / { return 404; }
  }
}
EOF
nginx -p "$BASE/" -c nginx.conf -t
cd "$BASE"
nohup /home/frappe/frappe-bench/env/bin/gunicorn -b "127.0.0.1:${APP_PORT}" \
  -w 4 --max-requests 5000 --max-requests-jitter 500 -t 120 \
  server:application > "$BASE/gunicorn.log" 2>&1 &
echo $! > "$BASE/gunicorn.pid"
nohup nginx -p "$BASE/" -c nginx.conf -g 'daemon off;' \
  > "$BASE/nginx.log" 2>&1 &
echo $! > "$BASE/nginx-shell.pid"
sleep 1
ss -ltn | grep -F "${HOME_IP}:${TLS_PORT}" >/dev/null
ss -ltn | grep -F "127.0.0.1:${APP_PORT}" >/dev/null
printf '{"base":"%s","tls_port":%s,"app_port":%s}\n' "$BASE" "$TLS_PORT" "$APP_PORT"
