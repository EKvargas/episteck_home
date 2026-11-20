import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNITS = {
    "nutrition": (ROOT / "nutrition.container").read_text(encoding="utf-8"),
    "nutrition-mcp": (ROOT / "nutrition-mcp.container").read_text(encoding="utf-8"),
}
DATA_ENV_FILES = [
    "EnvironmentFile=/srv/episteck/services/nutrition/secrets/mealie.env",
    "EnvironmentFile=/srv/episteck/services/nutrition/secrets/providers.env",
    "EnvironmentFile=/srv/episteck/services/nutrition/secrets/home-auth.env",
]


def lines(text):
    return text.splitlines()


def test_both_units_carry_the_image_placeholder_once():
    for text in UNITS.values():
        images = [l for l in lines(text) if l.startswith("Image=")]
        assert images == ["Image=localhost/episteck-nutrition:REPLACE_WITH_COMMIT_SHA"]


def test_bls_is_mounted_read_only_and_bls_db_points_inside_the_mount():
    for text in UNITS.values():
        volumes = [l for l in lines(text) if l.startswith("Volume=")]
        ref = [v for v in volumes if v.split(":")[1] == "/reference"]
        assert ref == ["Volume=/srv/episteck/services/nutrition/reference:/reference:ro"]
        assert "Environment=BLS_DB=/reference/bls-4.0.sqlite" in lines(text)
        bls = [l for l in lines(text) if l.startswith("Environment=BLS_DB=")]
        assert bls[0].removeprefix("Environment=BLS_DB=").startswith("/reference/")


def test_both_units_share_data_env_files_and_timezone():
    for text in UNITS.values():
        ls = lines(text)
        assert "Volume=/srv/episteck/services/nutrition/data:/data:Z" in ls
        assert "Environment=NUTRITION_DB=/data/nutrition.sqlite" in ls
        assert "Environment=DIARY_TZ=Europe/Berlin" in ls
        for env in DATA_ENV_FILES:
            assert env in ls


def test_ports_are_loopback_only_and_the_mcp_runs_the_mcp_server():
    web = lines(UNITS["nutrition"])
    mcp = lines(UNITS["nutrition-mcp"])
    assert [l for l in web if l.startswith("PublishPort=")] == [
        "PublishPort=127.0.0.1:9930:9930"
    ]
    assert [l for l in mcp if l.startswith("PublishPort=")] == [
        "PublishPort=127.0.0.1:9931:9931"
    ]
    assert "Environment=MCP_PORT=9931" in mcp
    assert "Exec=python -m app.mcp.server" in mcp
    assert not any(l.startswith("Exec=") for l in web)


def test_no_secret_value_is_inline():
    pattern = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD)=", re.I)
    for text in UNITS.values():
        for line in lines(text):
            if line.startswith("EnvironmentFile="):
                continue
            assert not pattern.search(line), line
