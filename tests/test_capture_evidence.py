"""Tests for the pure helpers of scripts/capture_evidence.py.

The browser part needs the Playwright container, so only the caption,
compression and transcript parsing are tested here.
"""

import io

from PIL import Image
from scripts import capture_evidence as ce


def _png(width: int = 400, height: int = 200, color: str = "white") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def test_caption_is_added_on_top_and_keeps_the_screenshot():
    out = ce.add_caption(_png(1000, 300, "red"), "https://localhost/forecast", "x")
    assert out.width == 1000
    assert out.height > 300
    # The bottom row is the screenshot, the top row is the dark caption strip.
    assert out.getpixel((10, out.height - 1)) == (255, 0, 0)
    assert out.getpixel((2, 2)) != (255, 0, 0)


def test_caption_widens_narrow_screenshots_so_the_text_fits():
    out = ce.add_caption(_png(393, 100), "mobile", "a phone-width page")
    assert out.width >= 900


def test_save_png_writes_a_palette_png(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "ROOT", tmp_path)
    path = tmp_path / "docs/evidence/01_ui/01_x.png"
    ce.save_png(Image.new("RGB", (50, 50), "blue"), path)
    assert Image.open(path).mode == "P"


def test_parse_transcript_reads_command_and_claim():
    raw = (
        "# captured 2026-11-10 on the project VM\n"
        "# what this proves: all targets are up\n"
        "$ curl -s localhost:19090/api/v1/targets\n"
        "$ not the command\n"
        "output\n"
    )
    assert ce.parse_transcript(raw) == (
        "curl -s localhost:19090/api/v1/targets",
        "all targets are up",
    )


def test_parse_transcript_without_header_gives_empty_strings():
    assert ce.parse_transcript("plain output\n") == ("", "")
