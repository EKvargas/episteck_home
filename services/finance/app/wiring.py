"""Builds live connectors from the secret files the operator placed for each connection.

Convention: ``<secrets_dir>/<connection_id>.<provider>`` (mode 600; Enable Banking holds
JSON with the application id and private key). A connection whose
secret is missing or unusable gets no connector, and the sync engine reports it as failed.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from . import domain
from .config import SecretFileError, read_secret_file
from .connectors.base import Connector
from .connectors.eb_jwt import JwtSigner
from .connectors.enable_banking import (
    DEFAULT_CAP, EbClient, EnableBankingConnector, RepoBudget, SessionInfo,
)
from .connectors.simplefin import SimpleFinConnector
from .store.repo import FinanceRepository

logger = logging.getLogger("finance.wiring")


def secret_path(secrets_dir: str, connection_id: str, provider: domain.Provider) -> str:
    return os.path.join(secrets_dir, f"{connection_id}.{provider.value.lower()}")


def load_eb_credentials(path: str) -> tuple[str, bytes]:
    """JSON {"application_id", "private_key_pem"} from a mode-600 file."""
    try:
        data = json.loads(read_secret_file(path))
        app_id, pem = data["application_id"], data["private_key_pem"].encode()
    except (ValueError, KeyError, AttributeError, TypeError):
        raise SecretFileError("enable banking credentials are unusable") from None
    if not isinstance(app_id, str) or not app_id:
        raise SecretFileError("enable banking credentials are unusable")
    return app_id, pem


def _enable_banking(repo: FinanceRepository, connection: domain.Connection,
                    secrets_dir: str, workspace_id: str, cap: int) -> Connector | None:
    app_id, pem = load_eb_credentials(secret_path(secrets_dir, connection.id, connection.provider))
    session = repo.load_eb_session(connection.id)
    if session is None or session.valid_until <= datetime.now(timezone.utc):
        logger.warning("connector not built: no live authorization session")
        return None
    return EnableBankingConnector(
        EbClient(JwtSigner(app_id, pem)), SessionInfo(session.session_id, session.accounts),
        RepoBudget(repo, workspace_id, cap=cap))


def build_connectors(repo: FinanceRepository, workspace_id: str, secrets_dir: str, *,
                     eb_access_cap: int = DEFAULT_CAP) -> dict[str, Connector]:
    connectors: dict[str, Connector] = {}
    for connection in repo.list_connections(workspace_id):
        try:
            if connection.provider is domain.Provider.SIMPLEFIN:
                url = read_secret_file(secret_path(secrets_dir, connection.id, connection.provider))
                connectors[connection.id] = SimpleFinConnector(url.decode())
            elif connection.provider is domain.Provider.ENABLE_BANKING:
                built = _enable_banking(repo, connection, secrets_dir, workspace_id, eb_access_cap)
                if built is not None:
                    connectors[connection.id] = built
        except (SecretFileError, ValueError):
            logger.warning("connector not built: secret missing or unusable")
    return connectors
