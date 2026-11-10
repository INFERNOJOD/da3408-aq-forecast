"""Page 2: the pipeline console for the operator.

Everything that only reads pipeline state is public (the same data as the
public ``/pipeline/*`` endpoints). Drift status and the ops buttons need the
API key, which the operator types in; the frontend never stores it in a file
and sends it only to ``/ops/*``.
"""

import os

import pandas as pd
import streamlit as st

from src.frontend import metrics
from src.frontend.client import BackendClient, BackendError
from src.frontend.helpers import (
    count_runs,
    dag_dot,
    drift_rows,
    nice_time,
    ops_message,
    short_time,
    table_rows,
)

LINKS = {
    "MLflow": ("MLFLOW_URL", "http://localhost:5000"),
    "Grafana": ("GRAFANA_URL", "http://localhost:3000"),
    "Prometheus": ("PROMETHEUS_URL", "http://localhost:9090"),
}


def _show_error(exc: BackendError) -> None:
    """Show a failed call in plain words."""
    if exc.code == "UNAUTHORIZED":
        st.error("The API key is wrong.")
    elif exc.code == "UNREACHABLE":
        st.error("The backend does not answer.")
    else:
        st.error(f"{exc.code}: {exc}")


def _public(client: BackendClient, path: str, **params) -> dict | None:
    """GET a public endpoint; show an error and return None on failure."""
    try:
        return client.get(path, params=params or None)
    except BackendError as exc:
        _show_error(exc)
        return None


def _status_section(client: BackendClient) -> None:
    """Show the backend health, the replay clock and the champion version."""
    health = _public(client, "/health")
    if health is None:
        return
    # Two rows of two boxes. In one row of four, each box is a quarter of the
    # centred page and "25 Mar, 00:00" was still cut off to "25 Mar, ..." in a
    # real browser (screenshot 08). AppTest cannot see widths, so it missed it.
    top = st.columns(2)
    top[0].metric("Backend", health["status"])
    top[1].metric("Model server", health["model_server"])
    bottom = st.columns(2)
    bottom[0].metric("Champion version", health.get("model_version") or "none")
    bottom[1].metric("Replay time", short_time(health["sim_time"]))
    state = "running" if health["replay_running"] else "stopped"
    st.caption(f"Replay is {state} at {nice_time(health['sim_time'])}.")


def _pipeline_section(client: BackendClient) -> None:
    """Show the DAG, the stage table, the run history and the model versions."""
    st.subheader("Pipeline")
    stages = _public(client, "/pipeline/stages")
    if stages:
        st.caption(f"Last run: {stages.get('run_id') or 'none yet'}")
        st.graphviz_chart(dag_dot(stages["stages"]))
        frame = pd.DataFrame(table_rows(stages["stages"]))[
            ["name", "status", "duration_s", "rows_out", "rows_per_sec"]
        ]
        st.dataframe(frame, hide_index=True, width="stretch")
    runs = _public(client, "/pipeline/runs", limit=20)
    if runs:
        ok, failed = count_runs(runs["runs"])
        st.markdown(f"**Runs:** {ok} successful, {failed} failed (last 20)")
        if failed:
            # Errors first, in their own short table, so they are not lost in
            # the wide run table.
            st.markdown("**Failed runs**")
            failed_runs = [r for r in runs["runs"] if r["status"] == "failed"]
            frame = pd.DataFrame(table_rows(failed_runs))
            st.dataframe(
                frame[["run_id", "started_at", "failed_stage", "error"]],
                hide_index=True,
                width="stretch",
            )
        if runs["runs"]:
            st.markdown("**All runs**")
            frame = pd.DataFrame(table_rows(runs["runs"]))
            st.dataframe(frame, hide_index=True, width="stretch")
    models = _public(client, "/pipeline/models")
    if models:
        st.markdown("**Model versions**")
        frame = pd.DataFrame(table_rows(models["models"]))
        st.dataframe(frame, hide_index=True, width="stretch")


def _drift_section(client: BackendClient, key: str) -> bool:
    """Show the live drift status. Return False if the key was refused.

    This call doubles as the key check, so the buttons appear only for a key
    the backend accepts.
    """
    st.subheader("Drift")
    try:
        drift = client.get("/ops/drift", api_key=key)
    except BackendError as exc:
        _show_error(exc)
        return exc.code != "UNAUTHORIZED"
    cols = st.columns(3)
    cols[0].metric("Drift detected", "YES" if drift["any_drift"] else "no")
    cols[1].metric(
        "Cities above threshold", f"{drift['cities_exceeding']} / {drift['min_cities']}"
    )
    pooled = drift["mae_ratio_pooled"]
    cols[2].metric("Error ratio (72 h)", "n/a" if pooled is None else f"{pooled:.2f}")
    st.caption(
        f"As of {nice_time(drift['sim_time'])}. Drift needs "
        f"{drift['min_cities']} cities above their own threshold."
    )
    st.dataframe(pd.DataFrame(drift_rows(drift["cities"])), hide_index=True,
                 width="stretch")  # fmt: skip
    return True


def _ops_section(client: BackendClient, key: str) -> None:
    """Replay, retrain and rollback buttons (need the key)."""
    st.subheader("Operations")

    def act(label: str, path: str, body: dict) -> None:
        try:
            result = client.post(path, body, api_key=key)
        except BackendError as exc:
            _show_error(exc)
        else:
            st.success(ops_message(label, path, result))

    st.markdown("**Replay of the 2020 lockdown**")
    speed = st.slider("Speed (simulated hours per second)", 0.1, 20.0, 1.0, 0.1)
    c1, c2, c3 = st.columns(3)
    if c1.button("Start replay"):
        act("Replay started", "/ops/replay", {"action": "start", "speed_hps": speed})
    if c2.button("Stop replay"):
        act("Replay stopped", "/ops/replay", {"action": "stop"})
    if c3.button("Reset replay"):
        act("Replay reset", "/ops/replay", {"action": "reset"})

    st.markdown("**Retrain**")
    reason = st.text_input("Reason", "manual retrain from the console", max_chars=200)
    if st.button("Retrain now") and reason.strip():
        act("Retrain requested", "/ops/retrain", {"reason": reason.strip()})

    st.markdown("**Rollback**")
    version = st.text_input("Version to restore (empty = the previous one)")
    if st.button("Roll back"):
        act("Rolled back", "/ops/rollback", {"version": version.strip()} if version
            else {})  # fmt: skip


def render_console(client: BackendClient) -> None:
    """Draw the pipeline console."""
    metrics.page_views.labels("console").inc()
    st.title("Pipeline console")
    st.write("For the operator. Links to the other tools:")
    cols = st.columns(len(LINKS))
    for col, (name, (var, default)) in zip(cols, LINKS.items(), strict=True):
        col.link_button(name, os.environ.get(var, default))
    _status_section(client)
    _pipeline_section(client)

    key = st.text_input(
        "Operator API key (for drift and the buttons below)", type="password"
    )
    if not key:
        st.info("Enter the API key to see drift and to use the operations buttons.")
        return
    if _drift_section(client, key):
        _ops_section(client, key)
