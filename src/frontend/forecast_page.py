"""Page 1: the PM2.5 forecast for one city, written for non-technical users."""

import streamlit as st

from src.frontend import metrics
from src.frontend.client import BackendClient, BackendError
from src.frontend.helpers import card_html, nice_time

DOWN_MESSAGE = (
    "Sorry, the forecast service is not reachable right now. "
    "Nothing is wrong with your device. Please try again in a few minutes."
)
DEMO_NOTE = (
    "This is a demo. It replays real measurements from March to June 2020 as if "
    "they were happening now, so the dates you see are from 2020."
)
MODEL_DOWN_MESSAGE = (
    "The forecast model is taking a break, so there is no forecast at the moment. "
    "Please try again in a few minutes."
)


@st.cache_data(ttl=15, show_spinner=False)
def _forecast(_client: BackendClient, city: str) -> dict:
    """Fetch a forecast; cached for 15 s so a page refresh does not hit the model."""
    return _client.get("/forecast", params={"city": city})


@st.cache_data(ttl=300, show_spinner=False)
def _static(_client: BackendClient, path: str) -> dict:
    """Fetch data that hardly changes (cities, AQI categories)."""
    return _client.get(path)


def render_forecast(client: BackendClient) -> None:
    """Draw the forecast page."""
    metrics.page_views.labels("forecast").inc()
    st.title("Air quality forecast")
    st.write("Pick your city to see how much fine dust (PM2.5) to expect.")
    st.info(DEMO_NOTE, icon="ℹ️")
    try:
        cities = _static(client, "/cities")["cities"]
    except BackendError:
        st.error(DOWN_MESSAGE)
        return
    city = st.selectbox("City", cities)
    try:
        data = _forecast(client, city)
    except BackendError as exc:
        st.error(
            MODEL_DOWN_MESSAGE if exc.code == "MODEL_UNAVAILABLE" else DOWN_MESSAGE
        )
        return

    st.caption(f"Forecast made for {nice_time(data['issued_at'])}.")
    for item in data["forecasts"]:
        st.markdown(card_html(item), unsafe_allow_html=True)
    observed = data.get("latest_observed_pm25")
    if observed is not None:
        st.caption(f"Measured right now in {city}: {observed:.1f} µg/m³.")
    st.button("Refresh", on_click=st.cache_data.clear)

    with st.expander("What do the colours mean?"):
        try:
            info = _static(client, "/aqi/categories")
        except BackendError:
            st.write("The colour guide is not available right now.")
        else:
            for cat in info["categories"]:
                top = cat["max"] if cat["max"] is not None else "and above"
                st.markdown(
                    f'<span style="color:{cat["color"]};font-size:1.4rem">■</span> '
                    f"**{cat['name']}**: {cat['min']} to {top} µg/m³",
                    unsafe_allow_html=True,
                )
            st.caption(info["note"])
