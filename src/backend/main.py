"""Start the backend: ``python -m src.backend.main``.

If the certificate and key files exist (``TLS_CERT_FILE``, ``TLS_KEY_FILE``) the
server uses HTTPS; ``scripts/make_certs.sh`` creates them. Without them it falls
back to HTTP and says so in the log, so local runs and tests need no certificate.
"""

import os
from pathlib import Path

import uvicorn

from src.backend.app import create_app
from src.backend.settings import Settings
from src.common.config import load_env
from src.common.logging_setup import configure_logging, get_logger

log = get_logger(__name__)


def main() -> None:
    """Read settings, build the app and serve it."""
    configure_logging()
    load_env()
    app = create_app(Settings.from_env())
    cert = Path(os.environ.get("TLS_CERT_FILE", "/certs/server.crt"))
    key = Path(os.environ.get("TLS_KEY_FILE", "/certs/server.key"))
    tls = {}
    if cert.exists() and key.exists():
        tls = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
    else:
        log.warning("No TLS certificate at %s; serving plain HTTP", cert)
    uvicorn.run(
        app, host="0.0.0.0", port=int(os.environ.get("BACKEND_PORT", "8000")), **tls
    )  # noqa: S104


if __name__ == "__main__":
    main()
