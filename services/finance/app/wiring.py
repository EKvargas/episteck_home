"""Builds live connectors from the secret files the operator placed for each connection.

Convention: ``<secrets_dir>/<connection_id>.<provider>`` (mode 600). A connection whose
secret is missing or unusable gets no connector, and the sync engine reports it as failed.
"""
from __future__ import annotations

import logging
import os

from . import domain
from .config import SecretFileError, read_secret_file
from .connectors.base import Connector
from .connectors.simplefin import SimpleFinConnector
from .store.repo import FinanceRepository

logger = logging.getLogger("finance.wiring")


def secret_path(secrets_dir: str, connection_id: str, provider: domain.Provider) -> str:
    return os.path.join(secrets_dir, f"{connection_id}.{provider.value.lower()}")


def build_connectors(repo: FinanceRepository, workspace_id: str,
                     secrets_dir: str) -> dict[str, Connector]:
    connectors: dict[str, Connector] = {}
    for connection in repo.list_connections(workspace_id):
        if connection.provider is not domain.Provider.SIMPLEFIN:
            continue  # Enable Banking is added with its own secrets in a later change
        try:
            url = read_secret_file(secret_path(secrets_dir, connection.id, connection.provider))
            connectors[connection.id] = SimpleFinConnector(url.decode())
        except (SecretFileError, ValueError):
            logger.warning("connector not built: secret missing or unusable")
    return connectors
