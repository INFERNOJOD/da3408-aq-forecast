"""One place to configure logging, so every module logs the same way."""

import logging
import os

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: str | None = None) -> None:
    """Set up root logging once.

    The level comes from the argument, then the LOG_LEVEL env var, then INFO.
    An invalid level name falls back to INFO instead of crashing.
    """
    name = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    numeric = logging.getLevelName(name)
    if not isinstance(numeric, int):
        numeric = logging.INFO
    # force=True replaces handlers from earlier calls (safe to call twice).
    logging.basicConfig(level=numeric, format=LOG_FORMAT, force=True)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger (use ``get_logger(__name__)``)."""
    return logging.getLogger(name)
