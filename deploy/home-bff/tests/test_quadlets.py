from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = (ROOT / "home-bff.container").read_text(encoding="utf-8")
MINT = (ROOT / "home-bff-mint.container").read_text(encoding="utf-8")
TMPFILES = (ROOT.parent / "gateway" / "home-bff-mint.tmpfiles.conf").read_text(
    encoding="utf-8"
)
SHARED_DATA_VOLUME = "Volume=/srv/episteck/services/home-bff/data:/data:z"
MINT_SOCKET_VOLUME = (
    "Volume=/run/episteck/home-bff-mint:/run/episteck/home-bff-mint:rw"
)


def test_public_quadlet_cannot_reach_the_mint_socket_directory():
    assert PUBLIC.count("PublishPort=") == 1
    assert "PublishPort=127.0.0.1:9933:9933" in PUBLIC
    assert "internal_main" not in PUBLIC
    assert "BFF_STORE_PATH=/data/bff.sqlite" in PUBLIC
    assert "BFF_MINT_SOCKET_PATH=/run/episteck/home-bff-mint/mint.sock" in PUBLIC
    public_mounts = [
        line
        for line in PUBLIC.splitlines()
        if line.startswith(("Volume=", "Mount="))
    ]
    assert all("/run/episteck/home-bff-mint" not in line for line in public_mounts)
    assert "GroupAdd=keep-groups" not in PUBLIC
    assert SHARED_DATA_VOLUME in PUBLIC
    assert "Volume=/srv/episteck/services/home-bff/data:/data:Z" not in PUBLIC


def test_mint_quadlet_has_no_tcp_publication_and_uses_internal_entrypoint():
    assert "PublishPort=" not in MINT
    assert "Exec=python -m home_bff.internal_main" in MINT
    assert "BFF_STORE_PATH=/data/bff.sqlite" in MINT
    assert "BFF_MINT_SOCKET_PATH=/run/episteck/home-bff-mint/mint.sock" in MINT
    assert MINT_SOCKET_VOLUME in MINT
    assert "GroupAdd=keep-groups" in MINT
    assert SHARED_DATA_VOLUME in MINT
    assert "Volume=/srv/episteck/services/home-bff/data:/data:Z" not in MINT


def test_tmpfiles_creates_setgid_group_gated_socket_directory():
    assert "d /run/episteck 0755 root root -" in TMPFILES
    assert "d /run/episteck/home-bff-mint 2770 svc-home-bff episteck-gw -" in TMPFILES
