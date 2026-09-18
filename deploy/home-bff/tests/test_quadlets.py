from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = (ROOT / "home-bff.container").read_text(encoding="utf-8")
MINT = (ROOT / "home-bff-mint.container").read_text(encoding="utf-8")
TMPFILES = (ROOT.parent / "gateway" / "home-bff-mint.tmpfiles.conf").read_text(
    encoding="utf-8"
)


def test_public_quadlet_only_publishes_browser_bff_and_shares_socket_path():
    assert PUBLIC.count("PublishPort=") == 1
    assert "PublishPort=127.0.0.1:9933:9933" in PUBLIC
    assert "internal_main" not in PUBLIC
    assert "BFF_STORE_PATH=/data/bff.sqlite" in PUBLIC
    assert "BFF_MINT_SOCKET_PATH=/run/episteck/home-bff-mint/mint.sock" in PUBLIC
    assert "Volume=/run/episteck/home-bff-mint:/run/episteck/home-bff-mint:rw" in PUBLIC
    assert "GroupAdd=keep-groups" in PUBLIC


def test_mint_quadlet_has_no_tcp_publication_and_uses_internal_entrypoint():
    assert "PublishPort=" not in MINT
    assert "Exec=python -m home_bff.internal_main" in MINT
    assert "BFF_STORE_PATH=/data/bff.sqlite" in MINT
    assert "BFF_MINT_SOCKET_PATH=/run/episteck/home-bff-mint/mint.sock" in MINT
    assert "Volume=/run/episteck/home-bff-mint:/run/episteck/home-bff-mint:rw" in MINT
    assert "GroupAdd=keep-groups" in MINT


def test_tmpfiles_creates_setgid_group_gated_socket_directory():
    assert "d /run/episteck 0755 root root -" in TMPFILES
    assert "d /run/episteck/home-bff-mint 2770 svc-home-bff episteck-gw -" in TMPFILES
