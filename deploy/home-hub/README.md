# Home Hub F2b deployment preparation

The `svc-home-hub.container` Quadlet is prepared for a dedicated rootless
`svc-home-hub` account. F2b does not install, reload, enable, or start it. Build
the image from the repository root with:

```bash
podman build -f apps/home-hub/Dockerfile \
  -t localhost/episteck-home-hub:COMMIT_SHA apps/home-hub
```

Replace `COMMIT_SHA` in the image tag and Quadlet with the reviewed commit SHA.
The Hub publishes host port 9940 only on `127.0.0.1`; the container reaches the
host BFF through the approved `pasta:-T,9933` forward. Do not change this network
topology in response to a failed proof; stop and return the evidence for review.

## VERIFY LIVE gate — run separately after independent review

These commands are prepared only. They were not run as part of F2b implementation.
Run them on the real host only after review, with the Quadlet installed but before
starting the service. If pasta/Podman versions, the BFF reachability check, or the
isolation checks fail, stop and return the output without trying another network
topology.

```bash
# Record installed versions and rootless network backend.
sudo -u svc-home-hub podman --version
sudo -u svc-home-hub podman info --format '{{.Host.NetworkBackend}}'
pasta --version

# The BFF health endpoint must be reachable from the isolated Hub container.
sudo -u svc-home-hub podman run --rm --network pasta:-T,9933 \
  --entrypoint node localhost/episteck-home-hub:COMMIT_SHA \
  -e 'fetch("http://127.0.0.1:9933/health").then(r => { console.log(r.status); process.exit(r.status === 200 ? 0 : 1) }).catch(() => process.exit(1))'

# No other tested host-loopback service may be reachable through this network.
sudo -u svc-home-hub podman run --rm --network pasta:-T,9933 \
  --entrypoint node localhost/episteck-home-hub:COMMIT_SHA \
  -e 'const net=require("node:net"); const ports=[9930,9931,9932,9934]; let failed=false; Promise.all(ports.map(port => new Promise(resolve => { const socket=net.createConnection({host:"127.0.0.1",port,timeout:1500}); socket.once("connect",()=>{console.error(`UNEXPECTED reachable port ${port}`); failed=true; socket.destroy(); resolve()}); socket.once("error",resolve); socket.once("timeout",()=>{socket.destroy();resolve()}) }))).then(()=>process.exit(failed?1:0))'

# On the host, verify the Hub bind is loopback-only and nginx proxies /app to it.
sudo ss -ltnp | grep ':9940'
sudo nginx -T 2>/dev/null | grep -A8 -E 'location = /app|location \^~ /app/'

# From a separate external machine, direct access to the host port must fail.
curl --connect-timeout 3 -v http://HOST_PUBLIC_IP:9940/app
```

Expected: BFF health returns 200; the other listed ports all refuse or time out;
`ss` shows only `127.0.0.1:9940`; nginx's exact `/app` and `/app/` locations
proxy to that loopback listener; the external direct-port probe cannot connect.
The public `/app` URL through nginx is expected to work after a separately approved
coordinated rollout.
