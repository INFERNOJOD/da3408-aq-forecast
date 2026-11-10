"""Capture the rubric evidence gallery in ``docs/evidence/`` with Playwright.

This script runs inside the official Playwright image, never on the host, so
no browser is installed on the VM:

    docker run -d --name aq-evidence --network host --ipc host \
        -e TZ=Asia/Kolkata -v "$PWD:/repo" -w /repo \
        mcr.microsoft.com/playwright/python:v1.49.1-noble sleep infinity
    docker exec aq-evidence pip install markdown==3.7 pygments==2.18.0 pillow==11.0.0
    docker exec -e OPS_API_KEY aq-evidence python scripts/capture_evidence.py ui

Jobs: ``ui``, ``console``, ``design``, ``implementation``, ``testing``,
``data``, ``ci``, ``mlflow``, ``monitoring``, ``packaging``, ``guidelines``,
``terminals`` (renders every ``.txt`` that has no ``.png`` yet) and ``page``
(one screenshot, used by the live story in
``scripts/capture_evidence_host.sh``).

Each PNG gets a caption strip on top: the capture time, the URL or command,
and one line saying what the image proves. The operator API key is read from
the ``OPS_API_KEY`` environment variable only to type it into the console's
masked field. Before every screenshot the visible page text is checked for
the key, and the script stops if it is there.
"""

from __future__ import annotations

import argparse
import html
import io
import json
import logging
import os
import re
import sys
import tempfile
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:  # Playwright exists only in the capture container
    from playwright.sync_api import Page

log = logging.getLogger("capture_evidence")

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence"
FRONTEND = "https://localhost"
BACKEND = "https://localhost:8000"
MLFLOW = "http://localhost:5000"
GRAFANA = "http://localhost:13000"
PROMETHEUS = "http://localhost:19090"
ALERTMANAGER = "http://localhost:19093"
PUSHGATEWAY = "http://localhost:19091"
CITIES = ["Delhi", "Chennai", "Lucknow", "Hyderabad", "Bengaluru", "Jaipur", "Kolkata"]
CHAMPION_RUN = "498b149f78e2418695c3bf7e01b91615"  # v4, the current champion
MERMAID_JS = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"
WIDTH = 1280
MAX_HEIGHT = 16000  # Chromium refuses larger captures; long pages are cut here
FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FONT_MONO = "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"


class SecretOnPageError(RuntimeError):
    """The API key was visible on a page that was about to be captured."""


# --------------------------------------------------------------------------
# Image helpers
# --------------------------------------------------------------------------


def _font(path: str, size: int) -> ImageFont.ImageFont:
    """Load a TrueType font, or Pillow's default if the file is missing."""
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def add_caption(
    png: bytes, source: str, proves: str, stamp: str | None = None
) -> Image.Image:
    """Return the screenshot with a caption strip burned in on top."""
    shot = Image.open(io.BytesIO(png)).convert("RGB")
    width = max(shot.width, 900)
    small, bold = _font(FONT_MONO, 14), _font(FONT, 17)
    stamp = stamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
    lines = [(f"{stamp}   {source}", small, "#cfd8dc")]
    for part in textwrap.wrap(f"Proves: {proves}", width=width // 9):
        lines.append((part, bold, "#ffffff"))
    height = 14 + 24 * len(lines)
    out = Image.new("RGB", (width, shot.height + height), "#eceff1")
    draw = ImageDraw.Draw(out)
    draw.rectangle([0, 0, width, height - 1], fill="#263238")
    y = 8
    for text, font, color in lines:
        draw.text((12, y), text, font=font, fill=color)
        y += 24
    out.paste(shot, ((width - shot.width) // 2, height))
    return out


def save_png(img: Image.Image, path: Path) -> None:
    """Save as a 256-colour PNG, which keeps screenshots small and readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img.quantize(colors=256, method=Image.Quantize.FASTOCTREE).save(path, optimize=True)
    log.info("saved %s (%d KB)", path.relative_to(ROOT), path.stat().st_size // 1024)


# --------------------------------------------------------------------------
# Page helpers
# --------------------------------------------------------------------------


def assert_no_secret(page: Page) -> None:
    """Stop if the API key is part of the visible text of the page."""
    key = os.environ.get("OPS_API_KEY", "")
    if not key:
        return
    text = page.evaluate("() => document.body ? document.body.innerText : ''")
    if key in text or key in page.url:
        raise SecretOnPageError(f"API key visible on {page.url}; not capturing it")


def fit_viewport(page: Page) -> None:
    """Grow the viewport to the tallest scrolling element.

    Streamlit, Grafana and MLflow scroll inside an inner element, so a plain
    full-page screenshot would only show the first screen.
    """
    height = page.evaluate(
        """() => {
        let h = document.documentElement.scrollHeight;
        for (const el of document.querySelectorAll('*')) {
            const s = getComputedStyle(el);
            if ((s.overflowY === 'auto' || s.overflowY === 'scroll')
                && el.scrollHeight > el.clientHeight + 5) {
                h = Math.max(h, el.scrollHeight + el.getBoundingClientRect().top + 40);
            }
        }
        return Math.ceil(h);
    }"""
    )
    width = page.viewport_size["width"]
    page.set_viewport_size(
        {"width": width, "height": min(max(height, 600), MAX_HEIGHT)}
    )
    page.wait_for_timeout(800)


def shot(
    page: Page,
    target: str,
    source: str,
    proves: str,
    *,
    element: str | None = None,
    fit: bool = True,
    stamp: str | None = None,
) -> Path:
    """Capture the page (or one element) to ``docs/evidence/<target>.png``."""
    assert_no_secret(page)
    if page.url.startswith(MLFLOW):  # close the "MLflow Assistant" side panel
        close = page.get_by_role("button", name="Close", exact=True)
        if close.count():
            close.first.click()
            page.wait_for_timeout(800)
    if fit and element is None:
        fit_viewport(page)
    if element:
        png = page.locator(element).first.screenshot()
    else:
        png = page.screenshot(full_page=True)
    path = EVIDENCE / f"{target}.png"
    save_png(add_caption(png, source, proves, stamp), path)
    return path


def reset_viewport(page: Page, width: int = WIDTH, height: int = 900) -> None:
    """Back to a normal desktop window before the next page."""
    page.set_viewport_size({"width": width, "height": height})


def streamlit_ready(page: Page, text: str | None = None, timeout: int = 60000) -> None:
    """Wait until Streamlit has finished drawing the page.

    The app first shows an empty shell, then runs the script over the
    websocket. It is done when the status widget ("Running...") is gone and,
    if given, ``text`` is on the page.
    """
    page.wait_for_selector('[data-testid="stApp"]', timeout=timeout)
    if text:
        page.get_by_text(text, exact=False).first.wait_for(timeout=timeout)
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        busy = page.locator('[data-testid="stStatusWidget"]').count()
        skeleton = page.locator('[data-testid="stSkeleton"]').count()
        if not busy and not skeleton:
            break
        page.wait_for_timeout(300)
    page.wait_for_timeout(1500)  # graphviz and dataframes draw a little later


def goto_streamlit(page: Page, url: str, text: str | None = None) -> None:
    """Open a Streamlit page and wait for it."""
    page.goto(url, wait_until="domcontentloaded")
    streamlit_ready(page, text)


def pick_city(page: Page, city: str) -> None:
    """Choose a city in the forecast page's dropdown."""
    page.locator('[data-testid="stSelectbox"]').first.click()
    page.get_by_role("option", name=city, exact=True).click()
    page.wait_for_timeout(500)
    streamlit_ready(page, "In 24 hours")
    page.get_by_text(f"Measured right now in {city}").first.wait_for(timeout=30000)


def enter_key(page: Page) -> None:
    """Type the API key into the console's password field (shown as dots)."""
    key = os.environ.get("OPS_API_KEY")
    if not key:
        raise SystemExit("OPS_API_KEY is not set in this container")
    field = page.get_by_label("Operator API key (for drift and the buttons below)")
    field.fill(key)
    field.press("Enter")
    streamlit_ready(page, "Drift detected")


def scroll_to(page: Page, text: str) -> None:
    """Scroll the element with ``text`` into view."""
    target = page.get_by_text(text, exact=True)
    if not target.count():  # e.g. a success message that starts with the text
        target = page.get_by_text(text, exact=False)
    # Put the heading near the top of the frame, so the section is visible.
    target.first.evaluate("el => el.scrollIntoView({block: 'start'})")
    page.evaluate(
        "() => document.querySelectorAll('*').forEach(e => {"
        " if (e.scrollTop > 0) e.scrollTop -= 40; })"
    )
    page.wait_for_timeout(500)


# --------------------------------------------------------------------------
# Rendering local files as pages
# --------------------------------------------------------------------------

PAGE_CSS = """
body{font-family:'Liberation Sans',sans-serif;max-width:1180px;margin:24px auto;
     padding:0 24px;color:#1f2328;line-height:1.5;font-size:15px}
h1,h2{border-bottom:1px solid #d0d7de;padding-bottom:.3em}
table{border-collapse:collapse;margin:12px 0}
th,td{border:1px solid #d0d7de;padding:5px 10px;vertical-align:top}
th{background:#f6f8fa}
code{background:#f0f2f4;padding:1px 4px;border-radius:4px;font-size:90%}
pre{background:#f6f8fa;padding:12px;overflow:auto;border-radius:6px}
pre code{background:none;padding:0}
img{max-width:100%}
pre.mermaid{background:#fff;text-align:center}
.filehead{font-family:'Liberation Mono',monospace;background:#24292f;color:#fff;
          padding:8px 12px;border-radius:6px 6px 0 0;margin-bottom:0}
"""


def render_html(page: Page, body: str, title: str, base: Path) -> None:
    """Load an HTML body as a page whose relative links resolve under ``base``."""
    from pygments.formatters import HtmlFormatter

    style = HtmlFormatter(style="default").get_style_defs(".codehilite")
    doc = (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}"
        f"</title><base href='file://{base}/'><style>{PAGE_CSS}{style}</style>"
        f"</head><body>{body}</body></html>"
    )
    tmp = Path(tempfile.gettempdir()) / "evidence_page.html"
    tmp.write_text(doc, encoding="utf-8")
    page.goto(f"file://{tmp}")
    page.wait_for_timeout(300)


def render_markdown(page: Page, md_path: Path, anchor: str | None = None) -> None:
    """Render a Markdown file with its Mermaid diagrams drawn."""
    import markdown

    text = md_path.read_text(encoding="utf-8")
    if anchor and not anchor.startswith("#"):  # one bold-titled paragraph group
        start = text.index(anchor)
        stop = text.find("\n\n**", start + len(anchor))
        nxt = text.find("\n#", start)
        ends = [e for e in (stop, nxt) if e != -1]
        text = text[start : min(ends) if ends else len(text)]
        anchor = None
    if anchor:  # keep only the section that starts with this heading
        start = text.index(anchor)
        level = len(anchor) - len(anchor.lstrip("#"))
        rest = text[start + len(anchor) :]
        stop = re.search(rf"^#{{1,{level}}} ", rest, re.MULTILINE)
        text = anchor + (rest[: stop.start()] if stop else rest)
    blocks: list[str] = []

    def keep(match: re.Match) -> str:
        blocks.append(html.escape(match.group(1)))
        return f"MERMAIDBLOCK{len(blocks) - 1}"

    text = re.sub(r"```mermaid\n(.*?)```", keep, text, flags=re.DOTALL)
    body = markdown.markdown(
        text, extensions=["tables", "fenced_code", "codehilite", "sane_lists"]
    )
    for i, block in enumerate(blocks):
        body = re.sub(
            rf"(<p>)?MERMAIDBLOCK{i}(</p>)?",
            f'<pre class="mermaid">{block}</pre>',
            body,
        )
    head = f'<p class="filehead">{html.escape(str(md_path.relative_to(ROOT)))}</p>'
    if blocks:
        body += (
            f'<script src="{MERMAID_JS}"></script>'
            "<script>mermaid.initialize({startOnLoad:true,theme:'default'});</script>"
        )
    render_html(page, head + body, md_path.name, md_path.parent)
    if blocks:
        page.wait_for_function(
            "() => document.querySelectorAll('pre.mermaid svg').length"
            f" >= {len(blocks)}",
            timeout=30000,
        )
        page.wait_for_timeout(500)


def render_code(
    page: Page, path: Path, start: int = 1, end: int | None = None, note: str = ""
) -> None:
    """Render lines ``start..end`` of a source file with line numbers."""
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import TextLexer, get_lexer_for_filename

    lines = path.read_text(encoding="utf-8").splitlines()
    end = end or len(lines)
    code = "\n".join(lines[start - 1 : end])
    try:
        lexer = get_lexer_for_filename(path.name)
    except Exception:  # noqa: BLE001 - unknown extension: plain text is fine
        lexer = TextLexer()
    if path.name in {"Dockerfile", "Caddyfile", "MLproject"}:
        lexer = TextLexer() if path.name != "Dockerfile" else lexer
    out = highlight(
        code,
        lexer,
        HtmlFormatter(linenos="table", linenostart=start, cssclass="codehilite"),
    )
    rel = path.relative_to(ROOT)
    head = f'<p class="filehead">{html.escape(str(rel))}  (lines {start}-{end})</p>'
    extra = f"<p>{html.escape(note)}</p>" if note else ""
    render_html(page, head + out + extra, str(rel), path.parent)


def parse_transcript(raw: str) -> tuple[str, str]:
    """Return (command, what it proves) from a transcript's header lines."""
    proves, command = "", ""
    for line in raw.splitlines():
        if line.startswith("# what this proves:") and not proves:
            proves = line.split(":", 1)[1].strip()
        elif line.startswith("$ ") and not command:
            command = line[2:]
    return command, proves


def render_terminal(page: Page, txt: Path) -> tuple[str, str]:
    """Render a captured terminal transcript; return (command, proves)."""
    raw = txt.read_text(encoding="utf-8", errors="replace")
    key = os.environ.get("OPS_API_KEY", "")
    if key and key in raw:
        raise SecretOnPageError(f"API key found in {txt}")
    command, proves = parse_transcript(raw)
    lines = raw.splitlines()
    if len(lines) > 700:  # very long output: keep head and tail in the image
        lines = (
            lines[:400]
            + [f"... ({len(lines) - 600} lines cut, full text in {txt.name}) ..."]
            + lines[-200:]
        )
    body = (
        '<div style="background:#1e1e1e;color:#d4d4d4;padding:16px;border-radius:8px;'
        "font-family:'Liberation Mono',monospace;font-size:13px;white-space:pre-wrap;"
        'word-break:break-all">'
        + "\n".join(
            f'<span style="color:#6a9955">{html.escape(ln)}</span>'
            if ln.startswith("# ")
            else f'<span style="color:#4fc1ff">{html.escape(ln)}</span>'
            if ln.startswith("$ ")
            else html.escape(ln)
            for ln in lines
        )
        + "</div>"
    )
    render_html(page, body, txt.name, txt.parent)
    return command or txt.name, proves or "terminal output"


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------


def job_ui(page: Page) -> None:
    """Section 01: the forecast page."""
    goto_streamlit(page, f"{FRONTEND}/forecast", "In 24 hours")
    n = 1
    for city in CITIES:
        pick_city(page, city)
        shot(
            page,
            f"01_ui/{n:02d}_forecast_{city.lower()}",
            f"{FRONTEND}/forecast  (city: {city})",
            f"forecast page for {city}: 1 h and 24 h PM2.5 cards in the CPCB colour, "
            "category and health advice",
        )
        reset_viewport(page)
        n += 1
    page.get_by_text("What do the colours mean?").click()
    streamlit_ready(page, "Severe")
    shot(
        page,
        f"01_ui/{n:02d}_colour_legend",
        f"{FRONTEND}/forecast",
        "colour guide: the six CPCB categories with their colours and PM2.5 ranges",
    )
    n += 1
    reset_viewport(page)
    page.locator('[data-testid="stSelectbox"]').first.click()
    page.keyboard.type("Pune")
    page.wait_for_timeout(800)
    shot(
        page,
        f"01_ui/{n:02d}_unknown_city_typed",
        f"{FRONTEND}/forecast  (typed 'Pune')",
        "foolproof input: the city is a closed dropdown, typing an unsupported city "
        "finds no option",
        fit=False,
    )
    n += 1
    page.keyboard.press("Escape")
    # Phone width (iPhone 14 class, 393 x 852).
    mobile = page.context.browser.new_context(
        viewport={"width": 393, "height": 852},
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
        ignore_https_errors=True,
        locale="en-US",
        timezone_id="Asia/Kolkata",
    )
    mpage = mobile.new_page()
    goto_streamlit(mpage, f"{FRONTEND}/forecast", "In 24 hours")
    shot(
        mpage,
        f"01_ui/{n:02d}_mobile_393px",
        f"{FRONTEND}/forecast  (393 x 852, mobile)",
        "responsive: at phone width the cards stack and nothing is cut off",
        fit=False,
    )
    n += 1
    shot(
        mpage,
        f"01_ui/{n:02d}_mobile_393px_full",
        f"{FRONTEND}/forecast  (393 px wide)",
        "responsive: the whole forecast page at phone width",
    )
    n += 1
    mpage.set_viewport_size({"width": 393, "height": 852})
    mpage.get_by_text("What do the colours mean?").click()
    streamlit_ready(mpage, "Severe")
    shot(
        mpage,
        f"01_ui/{n:02d}_mobile_colour_legend",
        f"{FRONTEND}/forecast (393 px)",
        "responsive: the colour guide also fits at phone width",
    )
    n += 1
    mobile.close()
    # Unknown or missing input at the API, rendered by the browser.
    for path, proves in [
        (
            "/forecast?city=Pune",
            "unknown city gives 404 with the LLD error body, no crash",
        ),
        (
            "/forecast",
            "missing city gives 422 VALIDATION_ERROR in the same error shape",
        ),
        (
            "/forecast?city=delhi",
            "city names are checked exactly (case-sensitive, LLD)",
        ),
        ("/no-such-page", "unknown route gives 404 NOT_FOUND in the same error shape"),
    ]:
        page.goto(f"{BACKEND}{path}")
        shot(
            page,
            f"01_ui/{n:02d}_api{re.sub(r'[^a-z]+', '_', path.lower())}".rstrip("_"),
            f"GET {BACKEND}{path}",
            proves,
            fit=False,
        )
        n += 1
    # Backend down: a second frontend whose BACKEND_URL points nowhere
    # (started by the host script on port 18599, removed afterwards).
    try:
        goto_streamlit(page, "http://localhost:18599/forecast", "not reachable")
        shot(
            page,
            f"01_ui/{n:02d}_backend_down_message",
            "http://localhost:18599/forecast  (frontend with BACKEND_URL=https://nowhere.invalid:8000)",
            "backend down: the user gets one plain sentence, not a stack trace",
        )
    except Exception as exc:  # noqa: BLE001 - optional capture, reported below
        log.warning("backend-down frontend not available: %s", exc)
    n += 1
    reset_viewport(page)
    render_markdown(page, ROOT / "docs/user_manual.md")
    shot(
        page,
        f"01_ui/{n:02d}_user_manual",
        "docs/user_manual.md (rendered)",
        "the user manual exists, written for non-technical users, with screenshots",
    )


def job_console(page: Page) -> None:
    """Section 02: the pipeline console and the tools it links to."""
    goto_streamlit(page, f"{FRONTEND}/console", "Pipeline")
    page.locator('[data-testid="stGraphVizChart"] svg').first.wait_for(timeout=30000)
    page.wait_for_timeout(1500)
    shot(
        page,
        "02_pipeline_viz/01_console_top",
        f"{FRONTEND}/console",
        "separate pipeline screen: status, the 7-stage DVC DAG coloured by status, "
        "stage times, rows out and rows/sec",
        fit=False,
    )
    shot(
        page,
        "02_pipeline_viz/02_console_full_no_key",
        f"{FRONTEND}/console",
        "the whole console without the key: pipeline, runs, failures and model "
        "versions are public, drift and buttons are hidden",
    )
    reset_viewport(page)
    shot(
        page,
        "02_pipeline_viz/03_dag",
        f"{FRONTEND}/console",
        "DVC DAG: ingest -> validate -> features -> train -> evaluate -> test "
        "-> register",
        element='[data-testid="stGraphVizChart"]',
    )
    shot(
        page,
        "02_pipeline_viz/04_stage_table",
        f"{FRONTEND}/console",
        "per-stage duration, rows out and rows per second "
        "(pipeline speed and throughput)",
        element='[data-testid="stDataFrame"]',
    )
    scroll_to(page, "Failed runs")
    shot(
        page,
        "02_pipeline_viz/05_runs_and_failures",
        f"{FRONTEND}/console",
        "console of runs: success/failure counts, the failed runs with stage and error",
        fit=False,
    )
    scroll_to(page, "Model versions")
    shot(
        page,
        "02_pipeline_viz/06_model_versions",
        f"{FRONTEND}/console",
        "registered model versions with aliases (champion, previous) and gate result",
        fit=False,
    )
    # Wrong key first, then the real one.
    field = page.get_by_label("Operator API key (for drift and the buttons below)")
    field.fill("wrong-key")
    field.press("Enter")
    streamlit_ready(page, "The API key is wrong")
    scroll_to(page, "The API key is wrong.")
    shot(
        page,
        "02_pipeline_viz/07_wrong_key",
        f"{FRONTEND}/console  (wrong key typed)",
        "a wrong key shows no drift data and no buttons",
        fit=False,
    )
    enter_key(page)
    scroll_to(page, "Drift")
    shot(
        page,
        "02_pipeline_viz/08_drift_with_key",
        f"{FRONTEND}/console  (key entered, masked)",
        "with the key (masked field): live drift status and the per-city PSI table",
        fit=False,
    )
    scroll_to(page, "Operations")
    shot(
        page,
        "02_pipeline_viz/09_ops_section",
        f"{FRONTEND}/console  (key entered)",
        "pipeline management: replay start/stop/reset, retrain and rollback buttons",
        fit=False,
    )
    shot(
        page,
        "02_pipeline_viz/10_console_full_with_key",
        f"{FRONTEND}/console",
        "the whole operator console with the key entered (key shown only as dots)",
    )
    reset_viewport(page)
    page.goto(f"{GRAFANA}/d/aq-pipeline?orgId=1&from=now-7d&to=now&kiosk")
    page.wait_for_timeout(6000)
    shot(
        page,
        "02_pipeline_viz/11_grafana_pipeline",
        f"{GRAFANA}/d/aq-pipeline",
        "pipeline speed and throughput over time from the Pushgateway, in Grafana",
    )
    reset_viewport(page)
    page.goto(PUSHGATEWAY)
    page.wait_for_timeout(2000)
    shot(
        page,
        "02_pipeline_viz/12_pushgateway",
        PUSHGATEWAY,
        "every pipeline stage pushes duration, rows and rows/sec to the Pushgateway",
    )


def job_design(page: Page) -> None:
    """Section 03: architecture, HLD, LLD and the live API description."""
    n = 1
    for doc, proves in [
        ("architecture.md", "architecture diagram with an explanation of every block"),
        (
            "HLD.md",
            "HLD: lifecycle diagram, paradigm (functional stages, OO services), "
            "design choices with reasons",
        ),
        (
            "LLD.md",
            "LLD: every endpoint with request, response, status codes and error body",
        ),
    ]:
        reset_viewport(page)
        render_markdown(page, ROOT / "docs" / doc)
        shot(
            page,
            f"03_design/{n:02d}_{doc.split('.')[0].lower()}",
            f"docs/{doc} (rendered, Mermaid drawn)",
            proves,
        )
        n += 1
    reset_viewport(page)
    render_markdown(page, ROOT / "docs/HLD.md", "## 2. Lifecycle (HLD diagram)")
    shot(
        page,
        f"03_design/{n:02d}_hld_diagram",
        "docs/HLD.md section 2",
        "the HLD diagram on its own",
    )
    n += 1
    reset_viewport(page)
    render_markdown(page, ROOT / "docs/HLD.md", "## 3. Design decisions")
    page.get_by_text("Programming paradigm.").first.scroll_into_view_if_needed()
    shot(
        page,
        f"03_design/{n:02d}_paradigm",
        "docs/HLD.md section 3",
        "the paradigm is stated: functional pipeline stages, object-oriented services",
        fit=False,
    )
    n += 1
    reset_viewport(page)
    page.goto(f"{BACKEND}/docs")
    page.wait_for_selector(".opblock", timeout=30000)
    page.wait_for_timeout(1500)
    shot(
        page,
        f"03_design/{n:02d}_fastapi_docs",
        f"{BACKEND}/docs",
        "the FastAPI backend describes every endpoint (Swagger UI from /openapi.json)",
    )
    n += 1
    reset_viewport(page)
    blocks = page.locator(".opblock")
    for i in range(blocks.count()):
        block = blocks.nth(i)
        summary = block.locator(".opblock-summary").first
        method = summary.locator(".opblock-summary-method").inner_text().strip()
        path = summary.locator(".opblock-summary-path").inner_text().strip()
        summary.click()
        page.wait_for_timeout(700)
        block.scroll_into_view_if_needed()
        slug = re.sub(r"[^a-z0-9]+", "_", f"{method}_{path}".lower()).strip("_")
        png = block.screenshot()
        save_png(
            add_caption(
                png,
                f"{BACKEND}/docs  {method} {path}",
                f"{method} {path} expanded: parameters, request body and "
                "responses as in docs/LLD.md",
            ),
            EVIDENCE / f"03_design/{n:02d}_endpoint_{slug}.png",
        )
        summary.click()
        page.wait_for_timeout(300)
        n += 1
    # The LLD's endpoint list next to the live /openapi.json.
    page.goto(f"{BACKEND}/openapi.json")
    spec = json.loads(page.locator("body").inner_text())
    live = sorted((m.upper(), p) for p, ops in spec["paths"].items() for m in ops)
    lld = ROOT.joinpath("docs/LLD.md").read_text(encoding="utf-8")
    documented = set()
    for line in re.findall(r"^### (.+)$", lld, re.MULTILINE):
        for m, p in re.findall(r"(GET|POST)\s+`([^`?]+)", line):
            documented.add((m, p))
    rows = "".join(
        f"<tr><td>{m}</td><td><code>{html.escape(p)}</code></td>"
        f"<td>{'yes' if (m, p) in documented else '<b>NO</b>'}</td></tr>"
        for m, p in live
    )
    lld_rows = "".join(
        f"<tr><td>{m}</td><td><code>{html.escape(p)}</code></td>"
        f"<td>{'yes' if (m, p) in set(live) else '<b>NO</b>'}</td></tr>"
        for m, p in sorted(documented)
    )
    body = (
        "<h2>docs/LLD.md endpoints vs the running backend's /openapi.json</h2>"
        "<div style='display:flex;gap:32px'>"
        "<div><h3>docs/LLD.md (### headings)</h3><table><tr><th>Method</th>"
        f"<th>Path</th><th>In /openapi.json</th></tr>{lld_rows}</table></div>"
        f"<div><h3>{BACKEND}/openapi.json</h3><table><tr><th>Method</th>"
        f"<th>Path</th><th>In LLD</th></tr>{rows}</table></div></div>"
        f"<p>{len(documented)} endpoints in the LLD, {len(live)} in the live spec. "
        "The test <code>test_lld_lists_the_backend_routes</code> checks the same thing "
        "on every CI run.</p>"
    )
    reset_viewport(page)
    render_html(page, body, "LLD vs OpenAPI", ROOT / "docs")
    shot(
        page,
        f"03_design/{n:02d}_lld_vs_openapi",
        f"docs/LLD.md vs {BACKEND}/openapi.json (parsed side by side)",
        "the APIs follow the design doc: every LLD endpoint is live and every live one "
        "is in the LLD",
    )
    n += 1
    reset_viewport(page)
    render_markdown(page, ROOT / "docs/LLD.md", "## 1. Conventions")
    shot(
        page,
        f"03_design/{n:02d}_lld_error_contract",
        "docs/LLD.md section 1",
        "one error body for every non-2xx answer, with the code table",
    )
    n += 1
    reset_viewport(page)
    render_code(
        page,
        ROOT / "src/frontend/client.py",
        1,
        60,
        "The frontend's only door to the backend: BACKEND_URL from the environment.",
    )
    shot(
        page,
        f"03_design/{n:02d}_loose_coupling_client",
        "src/frontend/client.py",
        "loose coupling: the frontend talks to the backend only over REST, at the URL "
        "in BACKEND_URL",
    )


IMPLEMENTATION_SNIPPETS = [
    (
        "src/common/logging_setup.py",
        1,
        None,
        "logging: one setup for every module, "
        "level from LOG_LEVEL, Python logging module",
    ),
    (
        "src/backend/errors.py",
        1,
        None,
        "exception handling: every error becomes the "
        "LLD error body; validation and HTTP errors are overridden",
    ),
    ("src/common/errors.py", 1, None, "project exception types used across the code"),
    (
        "src/common/stage_runner.py",
        1,
        None,
        "a failing pipeline stage is logged, recorded "
        "as failed with its error, and re-raised",
    ),
    (
        "src/backend/app.py",
        100,
        140,
        "the API-key check on /ops/*: Bearer token compared with hmac.compare_digest",
    ),
    (
        "src/backend/forecaster.py",
        1,
        80,
        "docstrings and inline comments explain each class and decision",
    ),
    (
        "src/backend/ops.py",
        20,
        80,
        "object-oriented service with docstrings: the drift episode gate",
    ),
    (
        "src/pipeline/features.py",
        1,
        70,
        "functional pipeline stage: pure transforms f(DataFrame, params) -> DataFrame",
    ),
    (
        "pyproject.toml",
        1,
        None,
        "coding style: ruff rules incl. pycodestyle and pydocstyle",
    ),
]


def job_implementation(page: Page) -> None:
    """Section 04: code snippets that show the coding rules in practice."""
    n = 1
    for rel, start, end, proves in IMPLEMENTATION_SNIPPETS:
        path = ROOT / rel
        if not path.exists():
            log.warning("missing %s", rel)
            continue
        reset_viewport(page)
        render_code(page, path, start, end)
        stem = re.sub(
            r"[^a-z0-9]+", "_", f"{Path(rel).parent.name}_{Path(rel).stem}".lower()
        )
        shot(page, f"04_implementation/{n:02d}_{stem}", rel, proves)
        n += 1


def job_docs(page: Page, section: str, items: list[tuple]) -> None:
    """Render a list of (markdown file, heading or None, name, proves)."""
    for i, (rel, anchor, name, proves) in enumerate(items, 1):
        reset_viewport(page)
        render_markdown(page, ROOT / rel, anchor)
        where = f"{rel}" + (f"  {anchor.lstrip('# ')}" if anchor else "")
        shot(page, f"{section}/{i:02d}_{name}", f"{where} (rendered)", proves)


def job_testing(page: Page) -> None:
    """Section 05: test plan, cases, report and acceptance criteria."""
    job_docs(
        page,
        "05_testing",
        [
            (
                "docs/test_plan.md",
                None,
                "test_plan",
                "test plan: scope, levels, environment and how to run",
            ),
            (
                "docs/test_plan.md",
                "## 5. Acceptance criteria",
                "acceptance_criteria_defined",
                "acceptance criteria are defined up front",
            ),
            (
                "docs/test_plan.md",
                "## 6. Test cases",
                "test_case_list",
                "the list of test cases",
            ),
            (
                "docs/test_report.md",
                None,
                "test_report",
                "test report with the number of test cases passed and failed",
            ),
            (
                "docs/test_report.md",
                "## 1. Summary",
                "test_report_summary",
                "pass/fail counts",
            ),
            (
                "docs/test_report.md",
                "## 4. Acceptance criteria",
                "acceptance_criteria_met",
                "each acceptance criterion with its measured result: all met",
            ),
        ],
    )


def job_data(page: Page) -> None:
    """Section 06: Spark throughput documentation."""
    job_docs(
        page,
        "06_data_engineering",
        [
            (
                "docs/metrics.md",
                "## Stage 4: ingest (CSV to Parquet, Spark)",
                "metrics_ingest",
                "Spark ingest: rows, seconds and rows/sec, CSV to Parquet",
            ),
            (
                "docs/metrics.md",
                "### Benchmark: Spark vs pandas on the same ingest job",
                "spark_vs_pandas",
                "Spark vs pandas benchmark on the same ingest job",
            ),
            (
                "docs/metrics.md",
                "## Stage 5: validate (Spark)",
                "metrics_validate",
                "Spark validate: 48 checks, time and throughput",
            ),
            (
                "docs/metrics.md",
                "## Stage 6: features (Spark, driver 2g)",
                "metrics_features",
                "Spark features: time and throughput",
            ),
            (
                "docs/metrics.md",
                "## Driver memory 2g",
                "spark_driver_memory",
                "Spark settings for the 8 GB machine, measured",
            ),
        ],
    )
    for i, (rel, start, end, proves) in enumerate(
        [
            (
                "src/pipeline/ingest.py",
                1,
                80,
                "the ingest stage is Spark: CSV to Parquet",
            ),
            (
                "src/common/spark.py",
                1,
                None,
                "Spark session in local mode: driver 2g, 8 shuffle partitions",
            ),
            (
                "src/common/stage_runner.py",
                1,
                None,
                "every stage records duration, rows and "
                "rows/sec and pushes them to the Pushgateway",
            ),
        ],
        10,
    ):
        reset_viewport(page)
        render_code(page, ROOT / rel, start, end)
        shot(page, f"06_data_engineering/{i:02d}_{Path(rel).stem}", rel, proves)


def job_mlflow(page: Page) -> None:
    """Section 08: MLflow tracking and registry."""
    sec = "08_experiment_tracking"
    reset_viewport(page, 1600)
    page.goto(f"{MLFLOW}/#/experiments")
    page.wait_for_timeout(5000)
    shot(
        page,
        f"{sec}/01_experiments",
        f"{MLFLOW}/#/experiments",
        "MLflow tracking server with the aq-pm25 experiment",
    )
    reset_viewport(page, 1600)
    page.goto(f"{MLFLOW}/#/experiments/1/runs")
    page.wait_for_timeout(6000)
    shot(
        page,
        f"{sec}/02_runs",
        f"{MLFLOW}/#/experiments/1/runs",
        "every training run is tracked while the models are built",
    )
    reset_viewport(page, 1600)
    run = f"{MLFLOW}/#/experiments/1/runs/{CHAMPION_RUN}"
    page.goto(run)
    page.wait_for_timeout(6000)
    shot(
        page,
        f"{sec}/03_champion_run_overview",
        run,
        "the champion run (v4): parameters, metrics and tags (git commit, data hash, "
        "trigger, cutoff)",
    )
    reset_viewport(page, 1600)
    page.goto(run)
    page.wait_for_timeout(6000)
    page.get_by_placeholder("Search metrics").fill("lightgbm_mae")
    page.wait_for_timeout(1500)
    page.get_by_placeholder("Search metrics").scroll_into_view_if_needed()
    shot(
        page,
        f"{sec}/04_champion_run_metrics",
        f"{run}  (metrics filtered: lightgbm_mae)",
        "metrics logged beyond autolog: the LightGBM MAE per city and per horizon",
        fit=False,
    )
    reset_viewport(page, 1600)
    page.goto(f"{run}/artifacts/feature_importance.png")
    page.wait_for_timeout(6000)
    shot(
        page,
        f"{sec}/05_artifact_feature_importance",
        f"{run}/artifacts/feature_importance.png",
        "artifacts: the feature importance plot logged with the run",
    )
    reset_viewport(page, 1600)
    names = ["per_city_mae.csv", "drift_baseline.json", "residuals.png"]
    for name, proves in [
        ("per_city_mae.csv", "artifact: per-city error table"),
        (
            "drift_baseline.json",
            "artifact: drift baseline (PSI reference) logged with the model",
        ),
        ("residuals.png", "artifact: residual plot"),
    ]:
        page.goto(f"{run}/artifacts/{name}")
        page.wait_for_timeout(5000)
        stem = name.split(".")[0]
        shot(
            page,
            f"{sec}/{6 + names.index(name):02d}_artifact_{stem}",
            f"{run}/artifacts/{name}",
            proves,
        )
        reset_viewport(page, 1600)
    page.goto(f"{MLFLOW}/#/models")
    page.wait_for_timeout(5000)
    shot(
        page,
        f"{sec}/09_registry_models",
        f"{MLFLOW}/#/models",
        "model registry: the aq-pm25 model",
    )
    reset_viewport(page, 1600)
    page.goto(f"{MLFLOW}/#/models/aq-pm25")
    page.wait_for_timeout(5000)
    shot(
        page,
        f"{sec}/10_registry_versions",
        f"{MLFLOW}/#/models/aq-pm25",
        "version history with the champion and previous aliases",
    )
    reset_viewport(page, 1600)
    page.goto(f"{MLFLOW}/#/models/aq-pm25/versions/4")
    page.wait_for_timeout(5000)
    shot(
        page,
        f"{sec}/11_registry_v4",
        f"{MLFLOW}/#/models/aq-pm25/versions/4",
        "version 4: source run, aliases and signature",
    )
    reset_viewport(page, 1600)


def job_monitoring(page: Page) -> None:
    """Section 09: Prometheus, Alertmanager, Grafana and /metrics."""
    sec = "09_monitoring"
    for i, (url, wait, proves) in enumerate(
        [
            (
                f"{PROMETHEUS}/targets",
                4000,
                "Prometheus scrapes every component and all targets are up",
            ),
            (
                f"{PROMETHEUS}/rules",
                4000,
                "alert and recording rules: drift, error rate, "
                "model server, targets, pipeline",
            ),
            (f"{PROMETHEUS}/alerts", 4000, "the alerts and their current state"),
            (
                f"{PROMETHEUS}/query?g0.expr=up&g0.tab=table",
                5000,
                "up == 1 for every scrape job",
            ),
            (
                f"{PROMETHEUS}/query?g0.expr=rate(aq_http_requests_total%5B5m%5D)&g0.tab=graph"
                "&g0.range_input=1h",
                6000,
                "backend request rate graphed in near real time",
            ),
            (
                f"{ALERTMANAGER}/#/alerts",
                4000,
                "Alertmanager receives the alerts and sends "
                "them to the backend webhook",
            ),
            (
                f"{ALERTMANAGER}/#/status",
                4000,
                "Alertmanager config: route to the backend "
                "webhook over HTTPS, key read from a file",
            ),
        ],
        1,
    ):
        page.goto(url)
        page.wait_for_timeout(wait)
        slug = (
            re.sub(
                r"[^a-z]+",
                "_",
                url.split("//")[1].split("?")[0].split("/", 1)[1]
                if "/" in url.split("//")[1]
                else "home",
            ).strip("_")
            or "home"
        )
        slug = {"query": "query_up" if "expr=up" in url else "query_rate"}.get(
            slug, slug
        )
        shot(
            page,
            f"{sec}/{i:02d}_{'alertmanager_' if '19093' in url else 'prometheus_'}"
            f"{slug}",
            url,
            proves,
        )
        reset_viewport(page)
    n = 8
    for uid, name in [("aq-service", "AQ service"), ("aq-pipeline", "AQ pipeline")]:
        url = f"{GRAFANA}/d/{uid}?orgId=1&from=now-6h&to=now&kiosk"
        page.set_viewport_size({"width": 1600, "height": 2400})
        page.goto(url)
        page.wait_for_timeout(8000)
        shot(
            page,
            f"{sec}/{n:02d}_grafana_{uid.replace('-', '_')}",
            url,
            f"Grafana '{name}' dashboard, provisioned from JSON, live from Prometheus",
        )
        n += 1
        reset_viewport(page)
    # Key panels one by one.
    for uid in ["aq-service", "aq-pipeline"]:
        dash = json.loads(
            (
                ROOT / f"monitoring/grafana/dashboards/{uid.replace('-', '_')}.json"
            ).read_text()
        )
        panels = [p for p in dash["panels"] if p.get("type") != "row"]
        for p in panels[:6]:
            url = (
                f"{GRAFANA}/d/{uid}?orgId=1&from=now-6h&to=now"
                f"&viewPanel={p['id']}&kiosk"
            )
            page.goto(url)
            page.wait_for_timeout(5000)
            slug = re.sub(r"[^a-z0-9]+", "_", p["title"].lower()).strip("_")[:40]
            shot(
                page,
                f"{sec}/{n:02d}_panel_{slug}",
                url,
                f"Grafana panel '{p['title']}'",
                fit=False,
            )
            n += 1
    page.goto(f"{BACKEND}/metrics")
    page.wait_for_timeout(1500)
    shot(
        page,
        f"{sec}/{n:02d}_backend_metrics",
        f"GET {BACKEND}/metrics",
        "the backend exports its Prometheus metrics (requests, latency, drift, replay)",
    )
    reset_viewport(page)


def job_page(page: Page, args: argparse.Namespace) -> None:
    """One screenshot of a URL, for the live story."""
    if args.streamlit:
        goto_streamlit(page, args.url, args.wait_text)
        if args.key:
            enter_key(page)
        for label in args.click or []:
            page.get_by_role("button", name=label).click()
            streamlit_ready(page, args.after_text)
        if args.fill:
            label, value = args.fill.rsplit("=", 1)
            page.get_by_label(label).fill(value)
            page.get_by_label(label).press("Enter")
            streamlit_ready(page)
            for label in args.click2 or []:
                page.get_by_role("button", name=label).click()
                streamlit_ready(page, args.after_text)
        if args.scroll:
            scroll_to(page, args.scroll)
    else:
        page.goto(args.url)
        page.wait_for_timeout(args.wait_ms)
        if args.wait_text:
            page.get_by_text(args.wait_text).first.wait_for(timeout=60000)
    shot(page, args.target, args.source or args.url, args.proves, fit=args.full)


def job_terminals(page: Page, only: str | None) -> None:
    """Render every docs/evidence/**/*.txt that has no PNG yet."""
    for txt in sorted(EVIDENCE.glob("*/*.txt")):
        if only and only not in str(txt):
            continue
        png = txt.with_suffix(".png")
        if png.exists() and not only:
            continue
        reset_viewport(page)
        command, proves = render_terminal(page, txt)
        captured = re.search(
            r"^# captured (\S+ \S+ \S+)", txt.read_text(encoding="utf-8"), re.M
        )
        shot(
            page,
            str(txt.relative_to(EVIDENCE).with_suffix("")),
            f"$ {command}",
            proves,
            stamp=captured.group(1) if captured else None,
        )


def job_code(page: Page, args: argparse.Namespace) -> None:
    """One rendered source file (any section)."""
    render_code(page, ROOT / args.file, args.start, args.end or None)
    shot(page, args.target, args.file, args.proves)


def job_md(page: Page, args: argparse.Namespace) -> None:
    """One rendered Markdown file or section (any section)."""
    render_markdown(page, ROOT / args.file, args.anchor)
    shot(page, args.target, f"{args.file} (rendered)", args.proves)


def main() -> int:
    """Parse the job and run it in one headless Chromium."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("job")
    parser.add_argument("--url")
    parser.add_argument("--target")
    parser.add_argument("--source")
    parser.add_argument("--proves", default="")
    parser.add_argument("--streamlit", action="store_true")
    parser.add_argument("--key", action="store_true")
    parser.add_argument("--click", action="append")
    parser.add_argument("--click2", action="append")
    parser.add_argument("--fill")
    parser.add_argument("--after-text")
    parser.add_argument("--scroll")
    parser.add_argument("--wait-text")
    parser.add_argument("--wait-ms", type=int, default=3000)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--only")
    parser.add_argument("--file")
    parser.add_argument("--anchor")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=0)
    args = parser.parse_args()
    jobs = {
        "ui": job_ui,
        "console": job_console,
        "design": job_design,
        "implementation": job_implementation,
        "testing": job_testing,
        "data": job_data,
        "mlflow": job_mlflow,
        "monitoring": job_monitoring,
    }
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(
            viewport={"width": WIDTH, "height": 900},
            ignore_https_errors=True,
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )
        page = context.new_page()
        try:
            if args.job in jobs:
                jobs[args.job](page)
            elif args.job == "page":
                job_page(page, args)
            elif args.job == "terminals":
                job_terminals(page, args.only)
            elif args.job == "code":
                job_code(page, args)
            elif args.job == "md":
                job_md(page, args)
            else:
                parser.error(f"unknown job {args.job}")
        except SecretOnPageError as exc:
            log.error("%s", exc)
            return 3
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
