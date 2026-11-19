"""Service settings. Secrets come from mode-600 files and never appear in repr or logs."""
from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field


class SecretFileError(Exception):
    """A secret file is missing, empty, or readable by group/other."""


def read_secret_file(path: str) -> bytes:
    try:
        st = os.stat(path)
    except OSError:
        raise SecretFileError("secret file is not readable") from None
    if sys.platform != "win32" and st.st_mode & 0o077:
        raise SecretFileError("secret file must not be accessible by group or other (use 600)")
    with open(path, "rb") as handle:
        value = handle.read().strip()
    if not value:
        raise SecretFileError("secret file is empty")
    return value


MAX_ACCESS_CAP = 12  # sanity bound: PSD2 allows 4 unattended accesses a day, some banks fewer


def _access_cap(raw: str) -> int:
    """Per-account unattended data requests per rolling 24 h. Strict: no silent default."""
    if not raw.isdigit() or not 1 <= int(raw) <= MAX_ACCESS_CAP:
        raise ValueError(f"FINANCE_EB_ACCESS_CAP must be an integer from 1 to {MAX_ACCESS_CAP}")
    return int(raw)


_FLAGS = {"on": True, "true": True, "1": True, "off": False, "false": False, "0": False}


def _flag(name: str, raw: str) -> bool:
    try:
        return _FLAGS[raw.strip().lower()]
    except KeyError:
        raise ValueError(f"{name} must be on or off") from None


@dataclass(frozen=True)
class Settings:
    db_path: str
    workspace_id: str
    pepper: bytes = field(repr=False)
    secrets_dir: str | None = None
    eb_access_cap: int = 4
    description_rules: bool = False  # I2: payer rules keyed by a bank description (spike S2)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        return cls(
            db_path=env["FINANCE_DB"],
            workspace_id=env["FINANCE_WORKSPACE_ID"],
            pepper=read_secret_file(env["FINANCE_PEPPER_FILE"]),
            secrets_dir=env.get("FINANCE_SECRETS_DIR"),
            eb_access_cap=_access_cap(env.get("FINANCE_EB_ACCESS_CAP", "4")),
            description_rules=_flag("FINANCE_DESCRIPTION_RULES",
                                    env.get("FINANCE_DESCRIPTION_RULES", "off")),
        )
