"""Operator bootstrap CLI. Run on the node as the service user; it has no HTTP surface.

Keeping account and connection creation out of the API means a model or a remote caller
can never add an account. Every command is idempotent and audited as channel ``admin``.
Secrets are only ever read from, or written to, mode-600 files; nothing secret is printed.

    python -m app.admin init-workspace --name Home --owner PSN-...
    python -m app.admin claim-simplefin --setup-token-file T --out SECRETS/conn-1.simplefin
    python -m app.admin add-connection --id conn-1 --provider simplefin --owner PSN-...
    python -m app.admin link-account --id acc-1 --connection conn-1 --provider-ref ... ...
    python -m app.admin list
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections.abc import Mapping, Sequence

import httpx

from . import domain
from .config import SecretFileError, Settings, read_secret_file
from .connectors.base import ConnectorError
from .connectors.simplefin import TokenAlreadyClaimed, claim
from .store.repo import FinanceRepository, IdempotencyConflict
from .wiring import secret_path

MACHINE_CALLER = "svc-finance-admin"
CHANNEL = "admin"
_PROVIDERS = {"simplefin": domain.Provider.SIMPLEFIN,
              "enable_banking": domain.Provider.ENABLE_BANKING}


class AdminError(Exception):
    """A refusal with a static, secret-free message."""


def _values(enum) -> list[str]:
    return [e.value for e in enum]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.admin")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-workspace")
    p.add_argument("--name", required=True)
    p.add_argument("--owner", required=True)

    p = sub.add_parser("claim-simplefin")
    p.add_argument("--setup-token-file", required=True)
    p.add_argument("--out", required=True)

    p = sub.add_parser("add-connection")
    p.add_argument("--id", required=True)
    p.add_argument("--provider", required=True, choices=sorted(_PROVIDERS))
    p.add_argument("--owner", required=True)

    p = sub.add_parser("link-account")
    p.add_argument("--id", required=True)
    p.add_argument("--connection", required=True)
    p.add_argument("--provider-ref", required=True)
    p.add_argument("--institution", required=True)
    p.add_argument("--type", required=True, choices=_values(domain.AccountType))
    p.add_argument("--liquidity", required=True, choices=_values(domain.Liquidity))
    p.add_argument("--balance-authority", default="PROVIDER", choices=_values(domain.BalanceAuthority))
    p.add_argument("--preferred-kind", default="BOOKED", choices=_values(domain.BalanceKind))
    p.add_argument("--currency", required=True)
    p.add_argument("--owner", required=True, action="append")
    p.add_argument("--sla-hours", type=int, default=36)

    sub.add_parser("list")
    return parser


def _audited(repo: FinanceRepository, workspace_id: str, key: str, command: str,
             payload: dict, effect) -> dict:
    return repo.run_command(workspace_id, key, command, payload, effect,
                            human_actor=None, machine_caller=MACHINE_CALLER, channel=CHANNEL)


def _init_workspace(repo, settings, args) -> None:
    ws = domain.Workspace(settings.workspace_id, args.name, "PERSONAL", domain.WorkspaceStatus.ACTIVE)

    def effect(conn):
        repo.create_workspace_in_tx(conn, ws)
        repo.add_member_in_tx(conn, ws.id, args.owner, "OWNER")
        return {"workspace": ws.id}

    _audited(repo, ws.id, f"admin:init-workspace:{ws.id}", "init-workspace",
             {"name": args.name, "owner": args.owner}, effect)


def _add_connection(repo, settings, args) -> None:
    provider = _PROVIDERS[args.provider]
    if provider is domain.Provider.SIMPLEFIN:
        if not settings.secrets_dir:
            raise AdminError("FINANCE_SECRETS_DIR is required")
        read_secret_file(secret_path(settings.secrets_dir, args.id, provider))  # exists, 600, non-empty
    connection = domain.Connection(args.id, settings.workspace_id, provider, args.owner,
                                   domain.ConnectionStatus.OK)

    def effect(conn):
        repo.add_connection_in_tx(conn, connection)
        return {"connection": args.id}

    _audited(repo, settings.workspace_id, f"admin:add-connection:{args.id}", "add-connection",
             {"provider": args.provider, "owner": args.owner}, effect)


def _link_account(repo, settings, args) -> None:
    connection = next((c for c in repo.list_connections(settings.workspace_id)
                       if c.id == args.connection), None)
    if connection is None:
        raise AdminError("unknown connection")
    account = domain.Account(
        id=args.id, workspace_id=settings.workspace_id, owner_person_ids=tuple(args.owner),
        institution=args.institution, type=domain.AccountType(args.type),
        currency=args.currency, liquidity=domain.Liquidity(args.liquidity),
        balance_authority=domain.BalanceAuthority(args.balance_authority),
        movement_authority=connection.provider,
        preferred_balance_kind=domain.BalanceKind(args.preferred_kind),
        freshness_sla_hours=args.sla_hours, connection_id=connection.id,
        provider_account_ref=args.provider_ref)

    def effect(conn):
        repo.add_account_in_tx(conn, account)
        return {"account": account.id}

    _audited(repo, settings.workspace_id, f"admin:link-account:{args.id}", "link-account",
             vars(args) | {"owner": list(args.owner)}, effect)


def _claim(settings, args, transport) -> None:
    token = read_secret_file(args.setup_token_file).decode()
    # Create the destination FIRST (O_EXCL): claiming burns the token, so a destination
    # that cannot be written must be discovered before, not after.
    try:
        fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise AdminError("output file already exists; refusing to overwrite a secret") from None
    try:
        access_url = claim(token, transport=transport)
        with os.fdopen(fd, "w") as handle:
            handle.write(access_url + "\n")
    except BaseException:
        try:
            os.remove(args.out)
        except OSError:
            pass
        raise


def _list(repo, settings, out) -> None:
    ws = repo.get_workspace(settings.workspace_id)
    out(f"workspace {settings.workspace_id} status={ws.status.value if ws else 'MISSING'}")
    for c in repo.list_connections(settings.workspace_id):
        out(f"connection {c.id} provider={c.provider.value} status={c.status.value}")
    for a in repo.list_accounts(settings.workspace_id):
        out(f"account {a.id} institution={a.institution} currency={a.currency} "
            f"liquidity={a.liquidity.value} owners={len(a.owner_person_ids)}")


def run(argv: Sequence[str], env: Mapping[str, str] | None = None, *,
        transport: httpx.BaseTransport | None = None, out=print) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 2)
    try:
        settings = Settings.from_env(env)
        repo = FinanceRepository(settings.db_path, pepper=settings.pepper)
        if args.command == "init-workspace":
            _init_workspace(repo, settings, args)
        elif args.command == "claim-simplefin":
            _claim(settings, args, transport)
        elif args.command == "add-connection":
            _add_connection(repo, settings, args)
        elif args.command == "link-account":
            _link_account(repo, settings, args)
        else:
            _list(repo, settings, out)
    except (AdminError, SecretFileError, TokenAlreadyClaimed, ConnectorError, ValueError,
            KeyError, IdempotencyConflict, sqlite3.IntegrityError) as error:
        # Static, secret-free text only; the exception type is enough for the operator.
        print(f"error: {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run(sys.argv[1:]))
