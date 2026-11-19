from __future__ import annotations

import os
import sys

import pytest

from app.config import SecretFileError, Settings, read_secret_file

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")


def _secret(tmp_path, content="s3cret\n", mode=0o600):
    path = tmp_path / "pepper"
    path.write_text(content)
    if sys.platform != "win32":
        os.chmod(path, mode)
    return str(path)


def test_secret_file_is_read_and_stripped(tmp_path):
    assert read_secret_file(_secret(tmp_path)) == b"s3cret"


def test_empty_or_missing_secret_file_is_rejected(tmp_path):
    with pytest.raises(SecretFileError):
        read_secret_file(_secret(tmp_path, content="  \n"))
    with pytest.raises(SecretFileError):
        read_secret_file(str(tmp_path / "missing"))


@posix_only
def test_group_or_world_readable_secret_file_is_rejected(tmp_path):
    with pytest.raises(SecretFileError):
        read_secret_file(_secret(tmp_path, mode=0o640))


def test_settings_load_from_env_and_never_print_secrets(tmp_path):
    env = {"FINANCE_DB": str(tmp_path / "f.sqlite"), "FINANCE_WORKSPACE_ID": "ws-1",
           "FINANCE_PEPPER_FILE": _secret(tmp_path)}
    settings = Settings.from_env(env)
    assert settings.workspace_id == "ws-1"
    assert settings.pepper == b"s3cret"
    assert "s3cret" not in repr(settings) and "s3cret" not in str(settings)


def test_description_rules_flag_defaults_off_and_is_strict(tmp_path):
    env = {"FINANCE_DB": str(tmp_path / "f.sqlite"), "FINANCE_WORKSPACE_ID": "ws-1",
           "FINANCE_PEPPER_FILE": _secret(tmp_path)}
    assert Settings.from_env(env).description_rules is False
    for raw, expected in (("on", True), ("OFF", False), ("true", True), ("False", False),
                          ("1", True), ("0", False), (" on ", True)):
        settings = Settings.from_env({**env, "FINANCE_DESCRIPTION_RULES": raw})
        assert settings.description_rules is expected, raw
    with pytest.raises(ValueError):
        Settings.from_env({**env, "FINANCE_DESCRIPTION_RULES": "maybe"})


def test_missing_required_setting_fails_fast(tmp_path):
    with pytest.raises(KeyError):
        Settings.from_env({"FINANCE_DB": "x"})
