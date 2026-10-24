"""Operator command for Enable Banking consent. Run on the node as the service user.

    python -m app.connect banks --connection sparkasse --country DE --match sparkasse
    python -m app.connect authorize --connection sparkasse --aspsp "<exact bank name>" --country DE

``authorize`` prints the bank's consent link, waits up to 15 minutes for the owner to
approve it in the browser (the public callback stores the code), exchanges the code with
the application key, and prints the accounts the bank returned. Only this process and
the sync job read the application key; the API that serves the callback never does.
Nothing secret is printed: not the state, the code, the key or a balance.
"""
from __future__ import annotations

import argparse
import functools
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone

import httpx

from . import domain
from .config import SecretFileError, Settings
from .connectors.base import ConnectorError
from .connectors.eb_auth import (
    STATE_TTL, AuthorizationError, complete_authorization, start_authorization,
)
from .connectors.eb_jwt import JwtSigner
from .connectors.enable_banking import EbClient
from .store.repo import FinanceRepository
from .wiring import load_eb_credentials, secret_path

DEFAULT_REDIRECT_URL = "https://bff.home.episteck.com/finance/connect/callback"
POLL_SECONDS = 2.0


class ConnectError(Exception):
    """A refusal with a static, secret-free message."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.connect")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("banks")
    p.add_argument("--connection", required=True)
    p.add_argument("--country", required=True)
    p.add_argument("--match", default="")

    p = sub.add_parser("authorize")
    p.add_argument("--connection", required=True)
    p.add_argument("--aspsp", required=True)
    p.add_argument("--country", required=True)
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--redirect-url", default=None)
    return parser


def _client(repo, settings, connection_id, transport) -> EbClient:
    connection = next((c for c in repo.list_connections(settings.workspace_id)
                       if c.id == connection_id), None)
    if connection is None or connection.provider is not domain.Provider.ENABLE_BANKING:
        raise ConnectError("not an enable banking connection")
    if not settings.secrets_dir:
        raise ConnectError("FINANCE_SECRETS_DIR is required")
    app_id, pem = load_eb_credentials(
        secret_path(settings.secrets_dir, connection.id, connection.provider))
    return EbClient(JwtSigner(app_id, pem), transport=transport)


def _banks(client, args, out) -> None:
    banks = client.request("GET", "/aspsps", params={"country": args.country}).get("aspsps")
    for bank in banks or []:
        name = bank.get("name") if isinstance(bank, dict) else None
        if isinstance(name, str) and args.match.casefold() in name.casefold():
            seconds = bank.get("maximum_consent_validity")
            limit = f"{seconds // 86400} days" if type(seconds) is int else "unknown"
            out(f"{name} | consent up to {limit}")


def _authorize(repo, settings, client, args, env, out, sleep, clock) -> int:
    redirect = args.redirect_url or env.get("FINANCE_EB_REDIRECT_URL") or DEFAULT_REDIRECT_URL
    if not redirect.startswith("https://"):
        raise ConnectError("the redirect URL must be https")
    started = start_authorization(
        client, repo, settings.workspace_id, args.connection, aspsp_name=args.aspsp,
        country=args.country, redirect_url=redirect, requested_days=args.days, now=clock())
    out("Open this link in your browser and approve the access with your bank "
        "(valid 15 minutes):")
    out(started.url)
    deadline = clock() + STATE_TTL
    received = repo.take_callback(started.state_hash)
    while received is None:
        if clock() >= deadline:
            out("timed out: no answer from the bank within 15 minutes; nothing changed")
            return 1
        sleep(POLL_SECONDS)
        received = repo.take_callback(started.state_hash)
    try:
        result = complete_authorization(client, repo, received, now=clock())
    except AuthorizationError:
        raise ConnectError("authorization not completed; nothing changed") from None
    out(f"authorized {result.connection_id} until {result.consent_expires_at.date()}: "
        f"linked={result.linked} new={result.unexpected} missing={result.missing}")
    for account in result.accounts:
        status = "linked" if account.linked else "not linked"
        out(f"{account.ref} | {account.label} | {account.currency} | {status}")
    if result.unexpected:
        out("To read a 'not linked' account, run app.admin link-account with "
            "--provider-ref set to its reference (no new consent is needed).")
    return 0


def run(argv: Sequence[str], env: Mapping[str, str] | None = None, *,
        transport: httpx.BaseTransport | None = None,
        out: Callable[[str], None] = functools.partial(print, flush=True),
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 2)
    try:
        settings = Settings.from_env(env)
        repo = FinanceRepository(settings.db_path, pepper=settings.pepper)
        client = _client(repo, settings, args.connection, transport)
        if args.command == "banks":
            _banks(client, args, out)
            return 0
        return _authorize(repo, settings, client, args, env or {}, out, sleep, clock)
    except (ConnectError, AuthorizationError, SecretFileError, ConnectorError, ValueError,
            KeyError) as error:
        # Static messages only: these types never carry a payload, URL or credential.
        detail = f": {error}" if isinstance(error, (ConnectError, ConnectorError)) else ""
        print(f"error: {type(error).__name__}{detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run(sys.argv[1:], os.environ))
