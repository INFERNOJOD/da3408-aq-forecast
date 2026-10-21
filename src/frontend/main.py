"""Start the frontend: the metrics exporter first, then Streamlit.

Streamlit runs ``app.py`` only when someone opens a page, so an exporter
started there is missing until the first visit, and Prometheus marks the
frontend as down. Starting it here, in the same process before Streamlit,
makes ``/metrics`` answer from boot. ``app.py`` still calls
``start_exporter()``, which does nothing the second time, so a plain
``streamlit run src/frontend/app.py`` keeps working in development.

Usage: ``python -m src.frontend.main [extra streamlit options]``.
"""

import sys
from pathlib import Path

from streamlit.web import cli as stcli

from src.common.logging_setup import configure_logging
from src.frontend import metrics

APP = Path(__file__).with_name("app.py")


def main() -> None:
    """Start the exporter, then hand the process over to Streamlit."""
    configure_logging()
    metrics.start_exporter()
    sys.argv = ["streamlit", "run", str(APP), *sys.argv[1:]]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
