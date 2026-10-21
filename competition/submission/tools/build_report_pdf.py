#!/usr/bin/env python3
"""Markdown -> PDF for the competition report.

Formatting follows附件2: A4; body 宋体(SimSun-like) 小四(12pt); 1.5 line spacing;
cover page, table of contents and a "第 X 页 共 Y 页" footer, matching the
official 作品报告 template. The 宋体 face is embedded from the macOS system
Songti collection so the PDF renders identically on any reader.

Usage:
  uv run --no-project --with reportlab python3 build_report_pdf.py <input.md> <output.pdf>
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    XPreformatted,
)
from reportlab.platypus.tableofcontents import TableOfContents

FONT = "SongtiSC"
FONT_BOLD = "SongtiSC-Bold"

# Portable 宋体 candidates: (path, regular subfont index, bold subfont index).
# Override with SUJIE_REPORT_FONT / SUJIE_REPORT_FONT_INDEX / _BOLD_ variants.
FONT_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Songti.ttc", 6, 1),  # macOS Songti SC
    ("/Library/Fonts/Songti.ttc", 6, 1),  # macOS (user-installed)
    ("C:/Windows/Fonts/simsun.ttc", 0, 0),  # Windows 宋体 SimSun
    ("C:/Windows/Fonts/msyh.ttc", 0, 0),  # Windows 微软雅黑
    ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", 0, 0),  # Linux Noto CJK
    ("/usr/share/fonts/truetype/arphic/uming.ttc", 0, 0),  # Linux AR PL UMing
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0, 0),  # Linux WenQuanYi
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0, 0),
]

BODY_PT = 12  # 小四
LEADING = 18  # 1.5 x
BODY_INDENT = 24
MARGIN_X = 3.17 * cm
MARGIN_Y = 2.54 * cm
CONTENT_W = A4[0] - 2 * MARGIN_X

TABLE_SEP_RE = re.compile(r"^[|\s:\-]+$")
COVER_RE = re.compile(r"^(作品名称|提交日期)\s*[:：]\s*(.*)$")


def register_fonts() -> None:
    override = os.environ.get("SUJIE_REPORT_FONT")
    if override:
        regular = (override, int(os.environ.get("SUJIE_REPORT_FONT_INDEX", "0")))
        bold = (
            os.environ.get("SUJIE_REPORT_BOLD_FONT", override),
            int(os.environ.get("SUJIE_REPORT_BOLD_INDEX", str(regular[1]))),
        )
    else:
        found = next((c for c in FONT_CANDIDATES if Path(c[0]).is_file()), None)
        if found is None:
            tried = "\n  ".join(c[0] for c in FONT_CANDIDATES)
            raise SystemExit(
                "No CJK font found. Set SUJIE_REPORT_FONT (and optionally "
                "SUJIE_REPORT_FONT_INDEX / SUJIE_REPORT_BOLD_FONT / SUJIE_REPORT_BOLD_INDEX).\n"
                f"Tried:\n  {tried}"
            )
        regular, bold = (found[0], found[1]), (found[0], found[2])
    pdfmetrics.registerFont(TTFont(FONT, regular[0], subfontIndex=regular[1]))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, bold[0], subfontIndex=bold[1]))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD, italic=FONT, boldItalic=FONT_BOLD)


def styles() -> dict[str, ParagraphStyle]:
    body = ParagraphStyle(
        "body", fontName=FONT, fontSize=BODY_PT, leading=LEADING,
        firstLineIndent=BODY_INDENT, spaceAfter=0, wordWrap="CJK",
    )
    return {
        "body": body,
        "h1": ParagraphStyle("h1", parent=body, fontName=FONT_BOLD, fontSize=16, leading=24,
                             alignment=TA_CENTER, firstLineIndent=0, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=body, fontName=FONT_BOLD, fontSize=14, leading=21,
                             firstLineIndent=0, spaceBefore=12, spaceAfter=6),
        "h3": ParagraphStyle("h3", parent=body, fontName=FONT_BOLD, fontSize=13, leading=20,
                             firstLineIndent=0, spaceBefore=8, spaceAfter=4),
        "h4": ParagraphStyle("h4", parent=body, fontName=FONT_BOLD, fontSize=12, leading=18,
                             firstLineIndent=0, spaceBefore=6, spaceAfter=3),
        "quote": ParagraphStyle("quote", parent=body, fontSize=10.5, leading=16,
                                leftIndent=18, firstLineIndent=0, textColor=colors.HexColor("#444444")),
        "list": ParagraphStyle("list", parent=body, leftIndent=30, bulletIndent=12, firstLineIndent=0),
        "code": ParagraphStyle("code", parent=body, fontName=FONT, fontSize=9, leading=13,
                               leftIndent=18, firstLineIndent=0, backColor=colors.HexColor("#F4F4F4"),
                               borderPadding=4, spaceBefore=4, spaceAfter=6),
        "cell": ParagraphStyle("cell", parent=body, fontSize=9.5, leading=14,
                               firstLineIndent=0, wordWrap="CJK"),
        "cellh": ParagraphStyle("cellh", parent=body, fontName=FONT_BOLD, fontSize=9.5, leading=14,
                                firstLineIndent=0, wordWrap="CJK"),
        "cover_org": ParagraphStyle("cover_org", parent=body, fontName=FONT_BOLD, fontSize=20,
                                    leading=30, alignment=TA_CENTER, firstLineIndent=0, spaceAfter=18),
        "cover_title": ParagraphStyle("cover_title", parent=body, fontName=FONT_BOLD, fontSize=34,
                                      leading=48, alignment=TA_CENTER, firstLineIndent=0),
        "cover_field": ParagraphStyle("cover_field", parent=body, fontSize=14, leading=30,
                                      firstLineIndent=0),
        "toc_head": ParagraphStyle("toc_head", parent=body, fontName=FONT_BOLD, fontSize=16,
                                   leading=24, alignment=TA_CENTER, firstLineIndent=0, spaceAfter=12),
    }


def inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`(.+?)`", lambda m: f'<font color="#555555">{m.group(1)}</font>', text)
    return text


def plain(text: str) -> str:
    return re.sub(r"[*`]", "", text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def display_width(text: str) -> float:
    return sum(2.0 if ord(ch) > 0x2E80 else 1.0 for ch in text)


def strip_comments(lines: list[str]) -> list[str]:
    out, in_comment = [], False
    for line in lines:
        if in_comment:
            in_comment = "-->" not in line
            continue
        if line.lstrip().startswith("<!--"):
            in_comment = "-->" not in line
            continue
        out.append(line)
    return out


class NumberedCanvas(pdfcanvas.Canvas):
    """Two-pass canvas that stamps '第 X 页 共 Y 页' on every page."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved: list[dict] = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self.setFont(FONT, 10.5)
            self.setFillColor(colors.black)
            self.drawCentredString(A4[0] / 2, 1.4 * cm, f"第 {self._pageNumber} 页  共 {total} 页")
            super().showPage()
        super().save()


class ReportDoc(BaseDocTemplate):
    def __init__(self, filename, **kw):
        super().__init__(filename, **kw)
        frame = Frame(MARGIN_X, MARGIN_Y, CONTENT_W, A4[1] - 2 * MARGIN_Y, id="normal")
        self.addPageTemplates([PageTemplate(id="all", frames=[frame])])
        toc = TableOfContents()
        toc.levelStyles = [
            ParagraphStyle("toc0", fontName=FONT, fontSize=12, leading=22, firstLineIndent=0),
            ParagraphStyle("toc1", fontName=FONT, fontSize=10.5, leading=18, leftIndent=18, firstLineIndent=0),
        ]
        self.toc = toc

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name in ("h2", "h3"):
            level = 0 if flowable.style.name == "h2" else 1
            self.notify("TOCEntry", (level, flowable.getPlainText(), self.page))


def build(md_path: Path, pdf_path: Path, plain_mode: bool = False) -> None:
    register_fonts()
    st = styles()
    lines = strip_comments(md_path.read_text("utf-8").splitlines())

    cover_fields: list[tuple[str, str]] = []
    story_body: list = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        m = COVER_RE.match(stripped)
        if m:
            cover_fields.append((m.group(1), plain(m.group(2))))
            i += 1
            continue

        if stripped == "---":
            i += 1
            continue

        if stripped.startswith("```"):
            i += 1
            block = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
                i += 1
            i += 1
            story_body.append(XPreformatted("\n".join(block), st["code"]))
            continue

        if stripped.startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i].strip())
                i += 1
            raw_rows = [r for r in block if not TABLE_SEP_RE.fullmatch(r.replace(" ", ""))]
            if not raw_rows:
                continue
            rows = [[c.strip() for c in r.strip("|").split("|")] for r in raw_rows]
            ncols = max(len(r) for r in rows)
            rows = [r + [""] * (ncols - len(r)) for r in rows]
            weights = [max(display_width(r[c]) for r in rows) + 2 for c in range(ncols)]
            total = sum(weights)
            col_widths = [CONTENT_W * w / total for w in weights]
            # Long description columns dominate the proportional split and can squeeze a short
            # label column below the width of an unbreakable word ("Node.js" -> "Node.j/s").
            min_w = 2.6 * cm
            for c in range(ncols):
                if col_widths[c] < min_w:
                    widest = max(range(ncols), key=lambda k: col_widths[k])
                    if widest == c:
                        continue
                    deficit = min_w - col_widths[c]
                    if col_widths[widest] - deficit >= min_w:
                        col_widths[c] = min_w
                        col_widths[widest] -= deficit
            data = [
                [Paragraph(inline(cell), st["cellh"] if r == 0 else st["cell"]) for cell in row]
                for r, row in enumerate(rows)
            ]
            table = Table(data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDEDED")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story_body.append(table)
            story_body.append(Spacer(1, 6))
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            title = plain(m.group(2))
            if len(m.group(1)) == 1 and title == "作品报告":
                i += 1
                continue  # rendered on the cover page
            level = min(len(m.group(1)), 4)
            story_body.append(Paragraph(inline(m.group(2)), st[f"h{level}"]))
            i += 1
            continue

        if stripped.startswith(">"):
            story_body.append(Paragraph(inline(stripped.lstrip("> ").strip()), st["quote"]))
            i += 1
            continue

        m = re.match(r"^([-*]|\d+\.)\s+(.*)$", stripped)
        if m:
            bullet = "•" if m.group(1) in ("-", "*") else m.group(1)
            story_body.append(Paragraph(inline(m.group(2)), st["list"], bulletText=bullet))
            i += 1
            continue

        story_body.append(Paragraph(inline(stripped), st["body"]))
        i += 1

    # ---- cover ----
    cover: list = []
    if not plain_mode:
        cover = [Spacer(1, 3.5 * cm), Paragraph("中国研究生网络安全创新大赛", st["cover_org"])]
        cover.append(Spacer(1, 1.2 * cm))
        cover.append(Paragraph("作品报告", st["cover_title"]))
        cover.append(Spacer(1, 3.0 * cm))
        fields = {k: v for k, v in cover_fields}
        rows = [
            [Paragraph(f"{k}：", st["cover_field"]), Paragraph(fields.get(k, ""), st["cover_field"])]
            for k in ("作品名称", "提交日期")
        ]
        tbl = Table(rows, colWidths=[3.2 * cm, CONTENT_W - 3.2 * cm], hAlign="CENTER")
        tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                 ("TOPPADDING", (0, 0), (-1, -1), 6),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        cover.append(tbl)
        cover.append(PageBreak())

    doc = ReportDoc(
        str(pdf_path), pagesize=A4, leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=MARGIN_Y, bottomMargin=MARGIN_Y,
        title="溯界（Sujie）", author="",
    )
    if plain_mode:
        story = story_body
    else:
        story = cover + [Paragraph("目　录", st["toc_head"]), Spacer(1, 6)]
        story.append(doc.toc)
        story.append(PageBreak())
        story += story_body

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc.multiBuild(story, canvasmaker=NumberedCanvas)
    print(f"OK -> {pdf_path} ({pdf_path.stat().st_size} bytes)")


if __name__ == "__main__":
    argv = [a for a in sys.argv[1:] if a != "--plain"]
    plain_mode = "--plain" in sys.argv
    if len(argv) != 2:
        sys.exit(__doc__)
    build(Path(argv[0]), Path(argv[1]), plain_mode=plain_mode)
