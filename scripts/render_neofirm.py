#!/usr/bin/env python3
"""
render_neofirm.py — PPTX renderer for NeoFirm pipeline output.
Takes slides.json from a run directory and produces a .pptx file.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

try:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt
except ImportError:
    print("ERROR: python-pptx not installed. Run: pip install python-pptx", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
DARK_BG = RGBColor(0x1A, 0x1A, 0x2E)
ACCENT   = RGBColor(0x00, 0xD4, 0xFF)
WHITE    = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_GRAY = RGBColor(0xCC, 0xCC, 0xCC)
SLIDE_W  = Inches(13.33)
SLIDE_H  = Inches(7.5)


def _add_bg(slide, color: RGBColor = DARK_BG) -> None:
    from pptx.oxml.ns import qn
    import lxml.etree as etree
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def _add_textbox(
    slide, text: str,
    left: float, top: float, width: float, height: float,
    font_size: int = 18, bold: bool = False,
    color: RGBColor = WHITE,
    align: PP_ALIGN = PP_ALIGN.LEFT,
    wrap: bool = True,
) -> None:
    txBox = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    tf = txBox.text_frame
    tf.word_wrap = wrap
    para = tf.paragraphs[0]
    para.alignment = align
    run = para.add_run()
    run.text = text
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.color.rgb = color


def _slide_title_content(prs: Presentation, title: str, points: list[str],
                          body: str = "", source: str = "") -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _add_bg(slide)

    # Title bar
    _add_textbox(slide, title, 0.5, 0.3, 12.33, 0.8,
                 font_size=28, bold=True, color=ACCENT, align=PP_ALIGN.LEFT)

    # Horizontal rule simulation (thin box)
    from pptx.util import Inches, Pt
    rule = slide.shapes.add_shape(
        1,  # MSO_SHAPE_TYPE.RECTANGLE
        Inches(0.5), Inches(1.2), Inches(12.33), Inches(0.03)
    )
    rule.fill.solid()
    rule.fill.fore_color.rgb = ACCENT
    rule.line.fill.background()

    # Key points
    y = 1.4
    for i, pt in enumerate(points[:8]):
        text = f"• {pt}"
        _add_textbox(slide, text, 0.6, y, 11.5, 0.55, font_size=17, color=WHITE)
        y += 0.6

    # Body / source
    if body:
        _add_textbox(slide, body[:300], 0.6, max(y, 5.5), 11.5, 1.2,
                     font_size=14, color=LIGHT_GRAY)
    if source:
        _add_textbox(slide, f"출처: {source}", 0.6, 6.8, 11.5, 0.5,
                     font_size=12, color=ACCENT)


def render_pptx(run_dir: Path, sector: str, slides_data: dict) -> Path:
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    # ── Cover slide ──────────────────────────────────────────────────────────
    cover = prs.slides.add_slide(prs.slide_layouts[6])
    _add_bg(cover)
    _add_textbox(cover, "NeoFirm", 1.5, 1.5, 10, 1.2,
                 font_size=54, bold=True, color=ACCENT, align=PP_ALIGN.CENTER)
    _add_textbox(cover, slides_data.get("title", sector), 1.5, 2.9, 10, 0.8,
                 font_size=28, color=WHITE, align=PP_ALIGN.CENTER)
    _add_textbox(cover, f"영역: {sector}", 1.5, 3.9, 10, 0.6,
                 font_size=20, color=LIGHT_GRAY, align=PP_ALIGN.CENTER)
    ts = datetime.now().strftime("%Y-%m-%d")
    _add_textbox(cover, ts, 1.5, 6.5, 10, 0.5,
                 font_size=14, color=LIGHT_GRAY, align=PP_ALIGN.CENTER)

    # ── Content slides ────────────────────────────────────────────────────────
    for slide_info in slides_data.get("slides", []):
        title = slide_info.get("title", "Slide")
        points = slide_info.get("key_points", [])
        body = slide_info.get("body", "")
        source = slide_info.get("source", "")
        _slide_title_content(prs, title, points, body, source)

    # ── Debate summary slide ──────────────────────────────────────────────────
    debate_summary = slides_data.get("debate_summary", "")
    if debate_summary:
        _slide_title_content(
            prs,
            "AI 에이전트 토론 요약",
            [debate_summary[:600]],
        )

    # ── Conclusion slide ──────────────────────────────────────────────────────
    conclusion = slides_data.get("conclusion", "")
    if conclusion:
        _slide_title_content(
            prs,
            "결론",
            [conclusion[:600]],
        )

    # ── Save ──────────────────────────────────────────────────────────────────
    safe_sector = "".join(c if c.isalnum() or c in "-_ " else "_" for c in sector)[:30]
    ts2 = datetime.now().strftime("%Y%m%d_%H%M")
    fname = f"NeoFirm_{safe_sector}_{ts2}.pptx"
    out_path = run_dir / fname

    prs.save(str(out_path))

    # Also copy to project output dir
    out_dir = Path(__file__).parent.parent / "output"
    out_dir.mkdir(exist_ok=True)
    import shutil
    shutil.copy2(out_path, out_dir / fname)

    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    import argparse
    p = argparse.ArgumentParser(description="Render NeoFirm slides.json to PPTX")
    p.add_argument("run_dir", help="Path to run directory containing slides.json")
    args = p.parse_args()

    run_dir = Path(args.run_dir)
    slides_path = run_dir / "slides.json"
    if not slides_path.exists():
        print(f"ERROR: {slides_path} not found", file=sys.stderr)
        sys.exit(1)

    slides_data = json.loads(slides_path.read_text(encoding="utf-8"))
    sector = slides_data.get("sector", "unknown")
    pptx_path = render_pptx(run_dir, sector, slides_data)
    print(f"[OK] PPTX: {pptx_path}")


if __name__ == "__main__":
    main()
