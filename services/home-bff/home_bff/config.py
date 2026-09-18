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
        )
