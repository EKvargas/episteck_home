from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUADLET = (ROOT / 'svc-home-hub.container').read_text(encoding='utf-8')


def test_hub_quadlet_publishes_only_loopback_and_uses_single_port_pasta():
    assert QUADLET.count('PublishPort=') == 1
    assert 'PublishPort=127.0.0.1:9940:3000' in QUADLET
    assert 'Network=pasta:-T,9933' in QUADLET
    assert 'Network=host' not in QUADLET
    assert '--map-gw' not in QUADLET


def test_hub_quadlet_is_live_and_does_not_embed_upstream_secrets():
    assert 'HOME_HUB_DATA_MODE=LIVE' in QUADLET
    assert 'HOME_HUB_BFF_BASE_URL=http://127.0.0.1:9933' in QUADLET
    assert 'HOME_HUB_PUBLIC_ORIGIN=https://bff.home.episteck.com' in QUADLET
    assert 'TOKEN=' not in QUADLET
    assert 'SECRET=' not in QUADLET


def test_hub_quadlet_definition_is_not_activated_by_repo_files():
    assert 'systemctl --user start svc-home-hub' not in QUADLET
    assert 'WantedBy=default.target' in QUADLET


def test_deployment_runbook_contains_unrun_live_isolation_proofs():
    runbook = (ROOT / 'README.md').read_text(encoding='utf-8')
    assert 'VERIFY LIVE gate' in runbook
    assert '--network pasta:-T,9933' in runbook
    assert '9930,9931,9932,9934' in runbook
    assert 'HOST_PUBLIC_IP:9940' in runbook


def test_home_hub_dockerfile_builds_standalone_with_build_dependencies_only():
    dockerfile = (ROOT.parent.parent / 'apps' / 'home-hub' / 'Dockerfile').read_text(encoding='utf-8')
    assert 'AS deps' in dockerfile
    assert 'AS builder' in dockerfile
    assert 'AS runner' in dockerfile
    assert 'npm ci --include=dev' in dockerfile
    assert 'RUN npm run build' in dockerfile
    assert '/.next/standalone ./' in dockerfile
    assert '/.next/static ./.next/static' in dockerfile
    assert 'USER node' in dockerfile
    assert 'CMD ["node", "--experimental-strip-types", "prelisten.mjs"]' in dockerfile
    assert 'TOKEN=' not in dockerfile
    assert 'SECRET=' not in dockerfile


def test_docker_build_workdir_is_owned_before_switching_to_node():
    dockerfile = (ROOT.parent.parent / 'apps' / 'home-hub' / 'Dockerfile').read_text(encoding='utf-8')
    deps, builder_and_runner = dockerfile.split('FROM deps AS builder', 1)
    builder, runner = builder_and_runner.split('FROM node:22-bookworm-slim AS runner', 1)
    before_node, after_node = deps.split('USER node', 1)
    assert (
        'chown node:node /srv/home-hub' in before_node
        or 'install -d -o node -g node /srv/home-hub' in before_node
    )
    assert 'RUN npm ci --include=dev' in after_node
    assert 'RUN npm run build' in builder
    assert 'USER root' not in builder
    assert runner.index('USER node') < runner.index('CMD [')
    assert 'COPY --from=builder --chown=node:node' in runner
    assert 'npm ci' not in runner and 'npm install' not in runner
    assert 'chmod 777' not in dockerfile


def test_docker_context_excludes_local_credentials():
    patterns = set(
        line.strip()
        for line in (ROOT.parent.parent / 'apps' / 'home-hub' / '.dockerignore').read_text(encoding='utf-8').splitlines()
        if line.strip() and not line.startswith('#')
    )
    for pattern in (
        '.env', '.env.*', '**/.env', '**/.env.*',
        '.npmrc', '**/.npmrc',
        '*.pem', '*.key', '*.p12', '*.pfx',
        '**/*private*key*', '**/*credentials*',
    ):
        assert pattern in patterns


def test_nginx_app_routes_preserve_upstream_csp_and_inherited_security_headers():
    nginx = (ROOT.parent / 'home-bff' / 'nginx-home-bff.conf').read_text(encoding='utf-8')
    assert 'add_header X-Content-Type-Options "nosniff" always;' in nginx
    assert 'add_header X-Frame-Options "DENY" always;' in nginx
    assert 'add_header Referrer-Policy "no-referrer" always;' in nginx
    assert 'proxy_hide_header Content-Security-Policy' not in nginx
    for route in ('location = /app {', 'location ^~ /app/ {'):
        location = nginx.split(route, 1)[1].split('\n    }', 1)[0]
        assert 'add_header ' not in location
