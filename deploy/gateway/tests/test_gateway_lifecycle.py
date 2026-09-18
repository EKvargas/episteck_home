"""Real nginx lifecycle proof for the dedicated gateway configuration."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

try:
    import pwd
except ImportError:  # pragma: no cover - Windows collection only.
    pwd = None


NGINX = shutil.which("nginx")
pytestmark = pytest.mark.skipif(
    os.name != "posix" or NGINX is None,
    reason="isolated Linux nginx binary unavailable",
)
CONFIG_SOURCE = Path(__file__).resolve().parents[1] / "nginx-mcp-gateway.conf"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _uid(pid: int) -> int:
    for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("Uid:"):
            return int(line.split()[1])
    raise AssertionError(f"process {pid} has no Uid status")


def _children(pid: int) -> set[int]:
    path = Path(f"/proc/{pid}/task/{pid}/children")
    if not path.exists():
        return set()
    return {int(value) for value in path.read_text(encoding="ascii").split()}


def _wait_for(predicate, message: str, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(message)


def test_start_reload_stop_as_dedicated_unprivileged_identity(tmp_path):
    runtime = tmp_path / "runtime"
    state = tmp_path / "state"
    prefix = tmp_path / "prefix"
    for path in (runtime, state, prefix / "conf"):
        path.mkdir(parents=True)

    listen_port = _free_port()
    config = CONFIG_SOURCE.read_text(encoding="utf-8")
    config = config.replace("/run/episteck-mcp-gateway", str(runtime))
    config = config.replace("/var/lib/episteck-mcp-gateway", str(state))
    config = config.replace("127.0.0.1:9934", f"127.0.0.1:{listen_port}")
    conf = prefix / "conf" / "gateway.conf"
    conf.write_text(config, encoding="utf-8")

    command = [NGINX, "-c", str(conf), "-p", str(prefix)]
    proc = subprocess.Popen(
        [*command, "-g", "daemon off;"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        pid_file = runtime / "nginx.pid"
        _wait_for(
            lambda: pid_file.exists() or proc.poll() is not None,
            "nginx did not create its dedicated PID file",
        )
        if proc.poll() is not None:
            _, stderr = proc.communicate()
            pytest.fail(f"nginx exited during startup: {stderr}")

        master_pid = int(pid_file.read_text(encoding="ascii").strip())
        assert master_pid == proc.pid
        for name in ("client_body", "proxy", "fastcgi", "uwsgi", "scgi"):
            assert (runtime / name).is_dir(), f"missing dedicated nginx temp dir: {name}"
        workers = _wait_for(
            lambda: _children(master_pid), "nginx did not start a worker"
        )
        service_uid = os.getuid()
        assert service_uid != 0, "lifecycle proof must run as an unprivileged identity"
        assert _uid(master_pid) == service_uid
        assert {_uid(worker) for worker in workers} == {service_uid}
        expected_user = os.environ.get("GATEWAY_EXPECTED_USER")
        if expected_user:
            assert pwd is not None
            assert pwd.getpwuid(service_uid).pw_name == expected_user
        assert pwd is not None
        service_user = pwd.getpwuid(service_uid).pw_name
        print(
            f"start: master={master_pid} workers={sorted(workers)} "
            f"uid={service_uid} user={service_user} pid={pid_file}"
        )

        reload_result = subprocess.run(
            [*command, "-s", "reload"], capture_output=True, text=True, check=False
        )
        assert reload_result.returncode == 0, reload_result.stderr
        replacement_workers = _wait_for(
            lambda: (_children(master_pid) - workers),
            "nginx reload did not start a replacement worker",
        )
        assert {_uid(worker) for worker in replacement_workers} == {service_uid}
        print(
            f"reload: master={master_pid} replacement_workers="
            f"{sorted(replacement_workers)} uid={service_uid}"
        )

        stop_result = subprocess.run(
            [*command, "-s", "quit"], capture_output=True, text=True, check=False
        )
        assert stop_result.returncode == 0, stop_result.stderr
        assert proc.wait(timeout=5) == 0
        assert not pid_file.exists()
        print(f"stop: master={master_pid} exit=0 pid_removed=true")
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
