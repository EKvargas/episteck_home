"""Server-rendered /runtime page (H5). Pure: no I/O, every dynamic value escaped.

Shows one section per agent the viewer may grant, each with its grant's state and
actions. It never renders a token, a Home session id, a delegation, a person reference
or the cookie: only the CSRF value tied to this browser session.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape

from .store import RuntimeGrant

# Deliberately strict: no scripts at all. No form-action: Chrome and Safari apply it
# to every redirect after a form submit, which would block the stale-login hop to Home.
PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "frame-ancestors 'none'; base-uri 'none'"
    ),
}


@dataclass(frozen=True)
class AgentView:
    """One agent on the page. ``grant`` is the viewer's own grant, or None."""

    runtime_id: str
    grant: RuntimeGrant | None


def _date(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%d/%m/%Y")


def _last_use(grant: RuntimeGrant, now: int) -> str:
    if grant.last_mint_at is None:
        return "sin uso todavía"
    minutes = max(0, (now - grant.last_mint_at) // 60)
    if minutes < 60:
        return f"hace {minutes} min"
    if minutes < 60 * 48:
        return f"hace {minutes // 60} h"
    return f"hace {minutes // 1440} días"


def _state(grant: RuntimeGrant | None, now: int) -> str:
    if grant is None:
        return "<p>Olin <strong>no tiene permiso</strong> para actuar en tu nombre.</p>"
    return (
        f"<p>Olin en Telegram <strong>puede actuar en tu nombre</strong> hasta el "
        f"{escape(_date(grant.expires_at))}.</p>"
        f"<p>Último uso: {escape(_last_use(grant, now))}.</p>"
    )


def _agent_section(agent: AgentView, token: str, now: int) -> str:
    runtime_id = escape(agent.runtime_id, quote=True)
    hidden = (
        f'<input type="hidden" name="csrf" value="{token}">'
        f'<input type="hidden" name="agent" value="{runtime_id}">'
    )
    grant = agent.grant
    revoke = (
        f'<form method="post" action="/runtime/revoke">{hidden}'
        f'<button type="submit">Revocar permiso</button></form>'
        if grant is not None
        else ""
    )
    label = "Renovar permiso (90 días)" if grant is not None else "Conceder permiso (90 días)"
    return (
        f"<section><h2>Olin <small>{runtime_id}</small></h2>"
        f"{_state(grant, now)}"
        f'<form method="post" action="/runtime/grant">{hidden}'
        f'<button type="submit">{label}</button></form>'
        f"{revoke}</section>"
    )


def render(
    *,
    csrf_token: str,
    agents: Sequence[AgentView],
    now: int,
    message: str | None = None,
    home_unreachable: bool = False,
) -> str:
    token = escape(csrf_token, quote=True)
    note = f'<p role="alert">{escape(message)}</p>' if message else ""
    status = (
        '<p role="status">Home no responde. Solo se muestran los permisos que ya diste.</p>'
        if home_unreachable
        else ""
    )
    sections = (
        "".join(_agent_section(agent, token, now) for agent in agents)
        if agents
        else "<p>Esta cuenta no tiene ningún asistente que autorizar.</p>"
    )
    return (
        "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Permiso de Olin</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:34rem;margin:2rem auto;"
        "padding:0 1rem}button{padding:.6rem 1rem;margin:.25rem 0}</style></head><body>"
        "<h1>Permiso de Olin</h1>"
        f"{note}{status}{sections}"
        "<hr><p>Cerrar sesión en todas partes también revoca este permiso.</p>"
        f'<form method="post" action="/logout/all">'
        f'<input type="hidden" name="csrf" value="{token}">'
        '<button type="submit">Cerrar sesión y revocar permiso</button></form>'
        "</body></html>"
    )
