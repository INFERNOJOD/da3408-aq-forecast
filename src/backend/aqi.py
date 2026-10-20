"""CPCB PM2.5 categories (docs/HLD.md section 4)."""

# (name, lowest value, colour, advice). The upper edge of a category is the
# lowest value of the next one, so 30.5 is "Good" and 31 is "Satisfactory".
_TABLE = [
    ("Good", 0, "#00B050", "Minimal impact."),
    (
        "Satisfactory",
        31,
        "#92D050",
        "Minor breathing discomfort to sensitive people.",
    ),
    (
        "Moderate",
        61,
        "#FFFF00",
        "Breathing discomfort to people with lung disease such as asthma, and "
        "discomfort to people with heart disease, children and older adults.",
    ),
    (
        "Poor",
        91,
        "#FF9900",
        "Breathing discomfort to most people on prolonged exposure.",
    ),
    ("Very Poor", 121, "#FF0000", "Respiratory illness on prolonged exposure."),
    (
        "Severe",
        251,
        "#C00000",
        "Affects healthy people and seriously impacts those with existing diseases.",
    ),
]

NOTE = "Indicative: official AQI uses 24-hour averages."


def categories() -> list[dict]:
    """Return the table as served by GET /aqi/categories."""
    rows = []
    for i, (name, low, color, advice) in enumerate(_TABLE):
        high = _TABLE[i + 1][1] - 1 if i + 1 < len(_TABLE) else None
        rows.append(
            {"name": name, "min": low, "max": high, "color": color, "advice": advice}
        )
    return rows


def categorize(pm25: float) -> dict:
    """Return name, colour and advice for a PM2.5 value in ug/m3."""
    chosen = _TABLE[0]
    for entry in _TABLE:
        if pm25 >= entry[1]:
            chosen = entry
    name, _, color, advice = chosen
    return {"aqi_category": name, "aqi_color": color, "advice": advice}
