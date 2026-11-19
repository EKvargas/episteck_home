"""A configured but missing BLS file keeps the fallback and says so once."""
import logging

from app import deps


def test_missing_bls_db_logs_one_warning_with_the_path_only(monkeypatch, caplog):
    monkeypatch.setenv("BLS_DB", "/nonexistent/bls.sqlite")
    monkeypatch.setenv("FOOD_PROVIDER", "auto")
    monkeypatch.delenv("USDA_API_KEY", raising=False)
    monkeypatch.delenv("OFF_BASE_URL", raising=False)
    deps._WARNED_MISSING_BLS.clear()
    with caplog.at_level(logging.WARNING, logger=deps.__name__):
        provider = deps._build_provider()
        deps._build_provider()  # the service and the diary both build one
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "/nonexistent/bls.sqlite" in warnings[0].getMessage()
    assert provider is not None  # the planned fallback still applies
