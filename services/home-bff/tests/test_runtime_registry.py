import pytest

from home_bff.config import ConfigError, parse_runtime_ids
from home_bff.runtime import grant_audiences_for
from tests.test_app import make_settings


def test_primary_keeps_all_three_audiences():
    assert grant_audiences_for("home-agent-primary") == {"home-control-plane", "svc-nutrition", "svc-finance"}


def test_other_runtimes_get_the_control_plane_only():
    assert grant_audiences_for("home-agent-ana") == {"home-control-plane"}


def test_runtime_ids_default_and_parse():
    assert parse_runtime_ids("") == ("home-agent-primary",)
    assert parse_runtime_ids(" home-agent-primary , home-agent-ana ") == ("home-agent-primary", "home-agent-ana")


@pytest.mark.parametrize("raw", ["home-agent-ana", "home-agent-primary,home-agent-primary", "home-agent-primary,Ana!", "home-agent-primary,-x"])
def test_bad_runtime_ids_fail_startup(raw):
    with pytest.raises(ConfigError):
        parse_runtime_ids(raw)


def test_legacy_binding_with_two_runtimes_fails_startup():
    with pytest.raises(ConfigError):
        make_settings(runtime_ids=("home-agent-primary", "home-agent-ana"), runtime_legacy_binding=True)


def test_two_runtimes_with_legacy_off_is_valid():
    assert make_settings(runtime_ids=("home-agent-primary", "home-agent-ana"), runtime_legacy_binding=False).runtime_ids[1] == "home-agent-ana"
