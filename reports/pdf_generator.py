"""PDF rendering of a ``Report`` with ReportLab (pure Python, no browser needed)."""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from reports.report_builder import Report

NAVY = colors.HexColor("#0d366b")
BLUE_TINT = colors.HexColor("#eef2f8")
GRID = colors.HexColor("#c3c2b7")
MAX_ROWS = 30   # rows per table in the PDF; the Excel export carries everything


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], textColor=NAVY, fontSize=22, alignment=0, spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], textColor=NAVY, spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("b", parent=base["BodyText"], fontSize=9, leading=12),
        "small": ParagraphStyle("s", parent=base["BodyText"], fontSize=7.5, leading=9.5, textColor=colors.HexColor("#52514e")),
        "cell": ParagraphStyle("c", parent=base["BodyText"], fontSize=7.5, leading=9),
    }


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "n/a"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def _table(df: pd.DataFrame, st, widths=None) -> Table:
    shown = df.head(MAX_ROWS)
    data = [[Paragraph(f"<b>{escape(str(c))}</b>", st["cell"]) for c in shown.columns]]
    for row in shown.itertuples(index=False):
        data.append([Paragraph(escape(_fmt(v)), st["cell"]) for v in row])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE_TINT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, NAVY),
        ("GRID", (0, 1), (-1, -1), 0.25, GRID), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#898781"))
    canvas.drawString(15 * mm, 9 * mm, "MarketPulse - historical Olist data (2016-2018); revenue is not profit")
    canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def report_to_pdf_bytes(report: Report) -> bytes:
    """Render the report: title block, limitations, KPIs, tables, findings."""
    st = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=16 * mm,
                            title=report.title, author="MarketPulse")
    width = A4[0] - 30 * mm
    story = [Paragraph(escape(report.title), st["title"]),
             Paragraph(f"Generated {report.generated_at:%Y-%m-%d %H:%M} &nbsp;|&nbsp; Data: {escape(report.period_text)}", st["body"]),
             Paragraph(f"Filters: {escape(report.filters_text)}", st["body"]), Spacer(1, 6),
             Paragraph("Read this first", st["h2"])]
    story += [Paragraph("&bull; " + escape(x), st["body"]) for x in report.limitations]

    story.append(Paragraph("Key performance indicators", st["h2"]))
    story.append(_table(report.kpis, st, [width * 0.22, width * 0.14, width * 0.64]))

    for name, df in report.tables.items():
        story.append(Paragraph(escape(name), st["h2"]))
        if df.empty:
            story.append(Paragraph("No rows for these filters.", st["body"]))
            continue
        story.append(_table(df, st))
        if len(df) > MAX_ROWS:
            story.append(Paragraph(f"Showing the first {MAX_ROWS} of {len(df)} rows; the Excel export has all rows.", st["small"]))

    if report.findings:
        story.append(PageBreak())
        story.append(Paragraph("Findings", st["h2"]))
        for section, items in report.findings.items():
            story.append(Paragraph(f"<b>{escape(section)}</b>", st["body"]))
            for i in items:
                story.append(Paragraph(f"&bull; <b>{escape(i.title)}</b> - {escape(i.detail)}", st["body"]))
                story.append(Paragraph(f"Rule: {escape(i.rule)}", st["small"]))
            story.append(Spacer(1, 4))
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
