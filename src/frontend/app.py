"""Frontend entry point: ``PYTHONPATH=. streamlit run src/frontend/app.py``.

Two pages: Forecast (for everyone) and Pipeline console (for the operator).
The backend address comes from ``BACKEND_URL``.
"""

import streamlit as st

from src.common.logging_setup import configure_logging
from src.frontend import metrics
from src.frontend.client import BackendClient
from src.frontend.console_page import render_console
from src.frontend.forecast_page import render_forecast

configure_logging()
metrics.start_exporter()

st.set_page_config(page_title="Air quality forecast", page_icon="🌫️", layout="centered")


@st.cache_resource
def get_client() -> BackendClient:
    """One backend client (and HTTP session) for the whole process."""
    return BackendClient()


client = get_client()

# Streamlit always serves the default page at "/" and ignores its url_path,
# so "/forecast" did not exist and showed "Page not found". The default page is
# now a hidden redirect, and both real pages have their own paths:
# /forecast and /console (docs/LLD.md, "Frontend pages").
forecast = st.Page(
    lambda: render_forecast(client), title="Forecast", url_path="forecast", icon="🌫️"
)
console = st.Page(
    lambda: render_console(client),
    title="Pipeline console",
    url_path="console",
    icon="⚙️",
)
home = st.Page(lambda: st.switch_page(forecast), title="Home", default=True)

page = st.navigation([home, forecast, console], position="hidden")
with st.sidebar:
    st.page_link(forecast)
    st.page_link(console)
page.run()
