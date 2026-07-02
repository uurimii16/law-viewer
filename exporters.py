#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exporters.py — 조합한 법령을 HTML / PDF 로 내보내기.

옵션(options dict):
  include_cites: 인용(법/영/규칙 제N조) 조문을 본문 아래 붙일지
  color:         제목(조 헤더) 색상 hex
  layout:        "기본" | "조밀"  (여백)
입력 sections: [law_engine.doc_sections(...) 결과, …]
"""
import io, html

# ── HTML ────────────────────────────────────────────────────────────────
def build_html(sections, options):
    color = options.get("color", "#2E5AAC")
    gap = "0.5em" if options.get("layout") == "조밀" else "1em"
    inc = options.get("include_cites", True)
    esc = html.escape
    out = [f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>법령 조합</title><style>
body{{font-family:'Malgun Gothic','맑은 고딕',sans-serif;max-width:900px;margin:2em auto;
padding:0 1em;line-height:1.6;color:#222}}
h1{{border-bottom:3px solid {color};padding-bottom:.3em}}
h2.jo{{color:{color};margin:{gap} 0 .2em;font-size:1.05em}}
.meta{{color:#888;font-size:.85em;margin-bottom:1em}}
.ln{{margin:.15em 0}}
details.cite{{margin:.2em 0 .2em 1.2em;border-left:3px solid {color}33;padding-left:.6em}}
details.cite>summary{{color:{color};cursor:pointer;font-size:.9em}}
details.cite p{{margin:.2em 0;color:#444;font-size:.92em}}
@media print{{details.cite{{border-left-color:#ccc}} details[open] summary{{font-weight:bold}}}}
</style></head><body>"""]
    for sec in sections:
        if not sec: continue
        out.append(f"<h1>{esc(sec['title'])}</h1>")
        date = sec.get("date", "")
        date = f"{date[:4]}.{date[4:6]}.{date[6:]}" if len(date) == 8 else date
        out.append(f'<div class="meta">시행 {esc(date)} · {esc(sec.get("kind",""))}</div>')
        for art in sec["articles"]:
            if art.get("header"):
                out.append(f'<h2 class="jo">{esc(art["header"])}</h2>')
            for line in art["lines"]:
                out.append(f'<div class="ln">{esc(line["text"])}</div>')
                if inc:
                    for label, body in line.get("cites", []):
                        inner = "".join(f"<p>{esc(x)}</p>" for x in body)
                        out.append(f'<details class="cite"><summary>📎 {esc(label)}</summary>{inner}</details>')
    out.append("</body></html>")
    return "\n".join(out)

# ── PDF (reportlab 내장 CID 한글폰트 — 외부 폰트파일 불필요) ──────────────────
def build_pdf(sections, options):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
    except Exception:
        pass
    F = "HYGothic-Medium"
    color = options.get("color", "#2E5AAC")
    inc = options.get("include_cites", True)
    lead = 14 if options.get("layout") == "조밀" else 16
    esc = html.escape
    S_title = ParagraphStyle("t", fontName=F, fontSize=15, leading=20, textColor=color, spaceBefore=10, spaceAfter=2)
    S_meta  = ParagraphStyle("m", fontName=F, fontSize=8, leading=11, textColor="#888888", spaceAfter=6)
    S_jo    = ParagraphStyle("j", fontName=F, fontSize=11, leading=15, textColor=color, spaceBefore=7, spaceAfter=1)
    S_body  = ParagraphStyle("b", fontName=F, fontSize=9.5, leading=lead)
    S_cite  = ParagraphStyle("c", fontName=F, fontSize=8.5, leading=12, textColor="#555555",
                             leftIndent=12, backColor="#F3F6FB", borderPadding=2)
    story = []
    for sec in sections:
        if not sec: continue
        story.append(Paragraph(esc(sec["title"]), S_title))
        date = sec.get("date", "")
        date = f"{date[:4]}.{date[4:6]}.{date[6:]}" if len(date) == 8 else date
        story.append(Paragraph(f"시행 {esc(date)} · {esc(sec.get('kind',''))}", S_meta))
        for art in sec["articles"]:
            if art.get("header"):
                story.append(Paragraph(esc(art["header"]), S_jo))
            for line in art["lines"]:
                story.append(Paragraph(esc(line["text"]) or " ", S_body))
                if inc:
                    for label, body in line.get("cites", []):
                        txt = f"<b>[인용] {esc(label)}</b><br/>" + "<br/>".join(esc(x) for x in body)
                        story.append(Paragraph(txt, S_cite))
        story.append(Spacer(1, 8))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4,
                      leftMargin=18*mm, rightMargin=18*mm, topMargin=16*mm, bottomMargin=16*mm
                      ).build(story)
    return buf.getvalue()
