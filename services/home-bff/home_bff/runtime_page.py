"""Server-rendered /runtime page (H5). Pure: no I/O, every dynamic value escaped.

Shows the grant's state and three actions. It never renders a token, a Home session
id, a delegation or the cookie: only the CSRF value tied to this browser session.
"""
from __future__ import annotations

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


def render(
    *,
    csrf_token: str,
    grant: RuntimeGrant | None,
    now: int,
    message: str | None = None,
) -> str:
    token = escape(csrf_token, quote=True)
    if grant is None:
        state = "<p>Olin <strong>no tiene permiso</strong> para actuar en tu nombre.</p>"
    else:
        state = (
            f"<p>Olin en Telegram <strong>puede actuar en tu nombre</strong> hasta el "
            f"{escape(_date(grant.expires_at))}.</p>"
            f"<p>Último uso: {escape(_last_use(grant, now))}.</p>"
        )
    note = f'<p role="alert">{escape(message)}</p>' if message else ""
    revoke = (
        f'<form method="post" action="/runtime/revoke">'
        f'<input type="hidden" name="csrf" value="{token}">'
        f'<button type="submit">Revocar permiso</button></form>'
        if grant is not None
        else ""
    )
    label = "Renovar permiso (90 días)" if grant is not None else "Conceder permiso (90 días)"
    return (
        "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Permiso de Olin</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:34rem;margin:2rem auto;"
        "padding:0 1rem}button{padding:.6rem 1rem;margin:.25rem 0}</style></head><body>"
        "<h1>Permiso de Olin</h1>"
        f"{note}{state}"
        f'<form method="post" action="/runtime/grant">'
        f'<input type="hidden" name="csrf" value="{token}">'
        f'<button type="submit">{label}</button></form>'
        f"{revoke}"
        "<hr><p>Cerrar sesión en todas partes también revoca este permiso.</p>"
        f'<form method="post" action="/logout/all">'
        f'<input type="hidden" name="csrf" value="{token}">'
        '<button type="submit">Cerrar sesión y revocar permiso</button></form>'
        "</body></html>"
    )
