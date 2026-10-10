"""BFF runtime configuration (G1.6).

Every secret arrives through the environment, supplied by a systemd/Quadlet
``EnvironmentFile`` that is root-owned and service-readable. Nothing here has a
default that would let the service start insecurely: a missing secret is a startup
failure, not a silent fallback.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Raised at startup when required configuration is absent."""


def _required(key: str) -> str:
    value = (os.environ.get(key) or "").strip()
    if not value:
        raise ConfigError(f"{key} is required")
    return value


def _optional(key: str, default: str) -> str:
    return (os.environ.get(key) or "").strip() or default


def _flag(key: str, default: bool) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    if raw in {"on", "true", "1"}:
        return True
    if raw in {"off", "false", "0"}:
        return False
    raise ConfigError(f"{key} must be on or off")


def _bounded_int(key: str, default: int, low: int, high: int) -> int:
    raw = _optional(key, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be an integer") from None
    if not low <= value <= high:
        raise ConfigError(f"{key} must be between {low} and {high}")
    return value


@dataclass(frozen=True)
class Settings:
    home_base_url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    delegation_secret: str
    delegation_issuer: str
    store_path: str
    mint_socket_path: str
    port: int
    scope: str
    # H5. Transition flag: while on, a browser login still claims the runtime and the
    # mint falls back to that binding when no grant exists. Off = grant only.
    runtime_legacy_binding: bool = True
    runtime_grant_days: int = 90

    @classmethod
    def from_env(cls) -> "Settings":
        redirect_uri = _required("BFF_REDIRECT_URI")
        if not redirect_uri.startswith("https://"):
            # The cookie is Secure; an http redirect would produce a login that
            # appears to work and then silently loses its session.
            raise ConfigError("BFF_REDIRECT_URI must be https")
        return cls(
            home_base_url=_required("HOME_BASE_URL").rstrip("/"),
            client_id=_required("BFF_CLIENT_ID"),
            client_secret=_required("BFF_CLIENT_SECRET"),
            redirect_uri=redirect_uri,
            delegation_secret=_required("HOME_DELEGATION_SECRET"),
            delegation_issuer=_optional("HOME_DELEGATION_ISSUER", "episteck-home-bff"),
            store_path=_optional("BFF_STORE_PATH", "/data/bff.sqlite"),
            mint_socket_path=_required("BFF_MINT_SOCKET_PATH"),
            port=int(_optional("BFF_PORT", "9933")),
            scope=_optional("BFF_SCOPE", "all openid"),
            runtime_legacy_binding=_flag("RUNTIME_LEGACY_BINDING", True),
            runtime_grant_days=_bounded_int("BFF_RUNTIME_GRANT_DAYS", 90, 1, 90),
        )
