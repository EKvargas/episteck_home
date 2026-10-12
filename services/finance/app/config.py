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


@dataclass(frozen=True)
class Settings:
    db_path: str
    workspace_id: str
    pepper: bytes = field(repr=False)
    secrets_dir: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        return cls(
            db_path=env["FINANCE_DB"],
            workspace_id=env["FINANCE_WORKSPACE_ID"],
            pepper=read_secret_file(env["FINANCE_PEPPER_FILE"]),
            secrets_dir=env.get("FINANCE_SECRETS_DIR"),
        )
