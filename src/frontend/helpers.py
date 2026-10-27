"""Pure helpers for the pages: text, colours and the DAG drawing.

They hold no Streamlit code, so the unit tests can run them directly.
"""

import html
from datetime import datetime

STATUS_COLORS = {
    "success": "#2e7d32",
    "failed": "#c62828",
    "running": "#f9a825",
    "skipped": "#78909c",
    "not_run": "#b0bec5",
}


def text_color(background: str) -> str:
    """Return black or white, whichever reads better on ``background`` (#RRGGBB)."""
    value = background.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#000000" if luminance > 150 else "#ffffff"


def nice_time(iso: str | None) -> str:
    """Return ``25 Mar 2020, 14:00`` for an ISO time, or ``unknown``."""
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y, %H:%M")
    except (TypeError, ValueError):
        return "unknown"


def short_time(iso: str | None) -> str:
    """Return ``25 Mar, 14:00``, short enough for a status box, or ``unknown``.

    The full ``nice_time`` value was cut off to "25 Mar 2…" in the console's
    four status boxes at the default page width (final audit).
    """
    try:
        return datetime.fromisoformat(iso).strftime("%d %b, %H:%M")
    except (TypeError, ValueError):
        return "unknown"


def horizon_label(hours: int) -> str:
    """Return the plain-language name of a forecast horizon."""
    return "In 1 hour" if hours == 1 else f"In {hours} hours"


def card_html(item: dict) -> str:
    """Return the HTML of one colour-coded forecast card (values are escaped)."""
    color = item["aqi_color"]
    fg = text_color(color)
    return (
        f'<div style="background:{html.escape(color)};color:{fg};'
        'padding:1rem 1.2rem;border-radius:12px;margin-bottom:0.5rem">'
        f'<div style="font-size:0.95rem">{horizon_label(item["horizon_h"])} '
        f"({html.escape(nice_time(item['valid_at']))})</div>"
        f'<div style="font-size:2.4rem;font-weight:700;line-height:1.2">'
        f'{item["pm25"]:.1f} <span style="font-size:1rem">µg/m³</span></div>'
        f'<div style="font-size:1.3rem;font-weight:600">'
        f"{html.escape(item['aqi_category'])}</div>"
        f'<div style="margin-top:0.4rem">{html.escape(item["advice"])}</div></div>'
    )


def dag_dot(stages: list[dict]) -> str:
    """Return Graphviz source for the DVC DAG, each stage coloured by its status."""
    lines = [
        "digraph dag {",
        "rankdir=LR;",
        'node [shape=box, style="filled,rounded", fontname="Helvetica", '
        'fontcolor="white"];',
    ]
    for stage in stages:
        status = stage.get("status", "not_run")
        color = STATUS_COLORS.get(status, STATUS_COLORS["not_run"])
        lines.append(
            f'"{stage["name"]}" [fillcolor="{color}", '
            f'label="{stage["name"]}\\n{status}"];'
        )
    for stage in stages:
        for dep in stage.get("deps", []):
            lines.append(f'"{dep}" -> "{stage["name"]}";')
    lines.append("}")
    return "\n".join(lines)


def count_runs(runs: list[dict]) -> tuple[int, int]:
    """Return (successful, failed) run counts."""
    failed = sum(1 for r in runs if r.get("status") == "failed")
    return len(runs) - failed, failed
