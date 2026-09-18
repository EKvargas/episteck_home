"""Public TCP entrypoint: ``python -m home_bff``.

Configuration is read once at startup so a missing secret fails loudly here rather
than at the first login attempt. The internal mint app is never imported or served
by this process.
"""
from __future__ import annotations

import logging

import uvicorn

from .app import create_app
from .config import Settings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    settings = Settings.from_env()
    app = create_app(settings)
    # Bound to loopback inside the container; the reverse proxy is the only ingress.
    uvicorn.run(app, host="0.0.0.0", port=settings.port, access_log=False)


if __name__ == "__main__":
    main()
