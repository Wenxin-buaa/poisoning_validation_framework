#!/usr/bin/env python3
import csv
import html
import io
import os
import zipfile
from pathlib import Path


OUT = Path(__file__).resolve().parent
MEMO = OUT / "source_memo.md"
METRICS = OUT / "pilot_metrics.csv"

THEME = {
    "name": "Tech Innovation",
    "primary": "0066FF",
    "highlight": "00FFFF",
    "dark": "1E1E1E",
    "white": "FFFFFF",
    "light": "F4F8FB",
    "body": "333333",
}


def read_inputs():
    memo_text = MEMO.read_text(encoding="utf-8")
    rows = []
    with METRICS.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["baseline"] = float(row["baseline"])
            row["pilot"] = float(row["pilot"])
            rows.append(row)
    return memo_text, rows


def metric_summary(rows):
    labels = {
        "turnaround_time": "Turnaround time",
        "formatting_rework": "Formatting rework",
        "reviewer_satisfaction": "Reviewer satisfaction",
        "documents_processed": "Documents processed",
    }
    units = {
        "turnaround_time": "days",
        "formatting_rework": "items",
        "reviewer_satisfaction": "score",
        "documents_processed": "documents",
    }
    summary = []
    for r in rows:
        metric = r["metric"]
        b = r["baseline"]
        p = r["pilot"]
        delta = p - b
        pct = (delta / b * 100) if b else 0
        summary.append({
            "metric": metric,
            "label": labels.get(metric, metric.replace("_", " ").title()),
            "baseline": b,
            "pilot": p,
            "delta": delta,
            "pct": pct,
            "unit": units.get(metric, r["unit"]),
        })
    return summary


def fmt_num(v):
    return str(int(v)) if float(v).is_integer() else f"{v:.1f}"


def build_memo_sections(summary):
    return [
        ("Executive Summary", [
            "The document automation pilot reduced turnaround time from five days to two days while increasing throughput from 18 to 42 documents.",
            "Template standardization lowered formatting rework from 14 items to 4, and reviewer satisfaction improved from 3.4 to 4.5.",
            "Continue the pilot for one more quarter, add a reviewer checklist, and publish a shared theme package."
        ]),
        ("Pilot Metrics", [
            f"{s['label']}: baseline {fmt_num(s['baseline'])} {s['unit']}, pilot {fmt_num(s['pilot'])} {s['unit']}, change {s['delta']:+.1f} ({s['pct']:+.0f}%)."
            for s in summary
        ]),
        ("Main Points", [
            "The pilot compressed document turnaround from five days to two days.",
            "Reviewers observed fewer formatting issues after template standardization.",
            "The required executive memo, PDF export, and five-slide summary deck are aligned to a shared theme.",
            "Risks remain around inconsistent source data quality and unclear ownership of final review."
        ]),
        ("Recommended Next Steps", [
            "Extend the pilot for one quarter with a defined success scorecard.",
            "Create a reviewer checklist covering source data completeness, formatting, and final approval ownership.",
            "Publish and govern a shared Tech Innovation theme package for memo, PDF, and deck outputs."
        ]),
    ]


def docx_escape(text):
    return html.escape(text, quote=False)


def wp(text, style=None):
    ppr = f"<w:pPr><w:pStyle w:val=\"{style}\"/></w:pPr>" if style else ""
    return f"<w:p>{ppr}<w:r><w:t>{docx_escape(text)}</w:t></w:r></w:p>"


def make_docx(summary, sections):
    rows_xml = ""
    table_cols = [2600, 1700, 1700, 2200, 1160]
    def cell(text, width, shade=None, bold=False):
        shading = f"<w:shd w:fill=\"{shade}\"/>" if shade else ""
        b = "<w:b/>" if bold else ""
        return (
            f"<w:tc><w:tcPr><w:tcW w:w=\"{width}\" w:type=\"dxa\"/>{shading}</w:tcPr>"
            f"<w:p><w:r><w:rPr>{b}</w:rPr><w:t>{docx_escape(text)}</w:t></w:r></w:p></w:tc>"
        )
    headers = ["Metric", "Baseline", "Pilot", "Change", "Unit"]
    rows_xml += "<w:tr>" + "".join(cell(h, table_cols[i], THEME["primary"], True) for i, h in enumerate(headers)) + "</w:tr>"
    for s in summary:
        rows_xml += "<w:tr>"
        vals = [s["label"], fmt_num(s["baseline"]), fmt_num(s["pilot"]), f"{s['delta']:+.1f} ({s['pct']:+.0f}%)", s["unit"]]
        rows_xml += "".join(cell(vals[i], table_cols[i]) for i in range(len(vals)))
        rows_xml += "</w:tr>"
    body = [wp("Document Automation Pilot Review", "Title"), wp("Structured executive memo based on A4 source memo and pilot metrics.")]
    for title, bullets in sections:
        body.append(wp(title, "Heading1"))
        if title == "Pilot Metrics":
            body.append(
                "<w:tbl><w:tblPr><w:tblW w:w=\"9360\" w:type=\"dxa\"/>"
                "<w:tblBorders><w:top w:val=\"single\" w:sz=\"4\" w:color=\"D0D7DE\"/>"
                "<w:left w:val=\"single\" w:sz=\"4\" w:color=\"D0D7DE\"/>"
                "<w:bottom w:val=\"single\" w:sz=\"4\" w:color=\"D0D7DE\"/>"
                "<w:right w:val=\"single\" w:sz=\"4\" w:color=\"D0D7DE\"/>"
                "<w:insideH w:val=\"single\" w:sz=\"4\" w:color=\"D0D7DE\"/>"
                "<w:insideV w:val=\"single\" w:sz=\"4\" w:color=\"D0D7DE\"/></w:tblBorders></w:tblPr>"
                + rows_xml + "</w:tbl>"
            )
        else:
            for item in bullets:
                body.append(wp(item, "ListParagraph"))
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
{''.join(body)}
<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>
</w:body></w:document>"""
    styles = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:sz w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:b/><w:color w:val="{THEME['dark']}"/><w:sz w:val="36"/></w:rPr><w:pPr><w:spacing w:after="240"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="Heading 1"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:b/><w:color w:val="{THEME['primary']}"/><w:sz w:val="28"/></w:rPr><w:pPr><w:spacing w:before="280" w:after="120"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:pPr><w:ind w:left="360"/></w:pPr><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:sz w:val="22"/></w:rPr></w:style>
</w:styles>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    doc_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""
    out = OUT / "document_automation_pilot_review.docx"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)
    return out


def pdf_text_escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(sections):
    lines = ["Document Automation Pilot Review", "Tech Innovation themed executive memo", ""]
    for title, bullets in sections:
        lines.append(title)
        for item in bullets:
            lines.append("- " + item)
        lines.append("")
    stream = ["BT", "/F1 20 Tf", "72 740 Td", f"({pdf_text_escape(lines[0])}) Tj", "/F1 11 Tf", "0 -28 Td"]
    for line in lines[1:]:
        safe = pdf_text_escape(line[:110])
        stream.append(f"({safe}) Tj")
        stream.append("0 -16 Td")
    stream.append("ET")
    content = "\n".join(stream).encode("latin-1", "replace")
    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(buf.tell())
        buf.write(f"{i} 0 obj\n".encode())
        buf.write(obj)
        buf.write(b"\nendobj\n")
    xref = buf.tell()
    buf.write(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for off in offsets[1:]:
        buf.write(f"{off:010d} 00000 n \n".encode())
    buf.write(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    out = OUT / "document_automation_pilot_review.pdf"
    out.write_bytes(buf.getvalue())
    return out


def slide_xml(title, lines, dark=False, stats=None):
    bg = THEME["dark"] if dark else THEME["light"]
    title_color = THEME["white"] if dark else THEME["dark"]
    body_color = THEME["white"] if dark else THEME["body"]
    spid = 2
    shapes = [
        f"""<p:sp><p:nvSpPr><p:cNvPr id="{spid}" name="Background"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="9144000" cy="5143500"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="{bg}"/></a:solidFill></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>"""
    ]
    spid += 1
    shapes.append(textbox(spid, title, 457200, 320000, 8200000, 700000, 3200, title_color, True))
    spid += 1
    shapes.append(rect(spid, 457200, 1050000, 1200000, 90000, THEME["highlight"]))
    spid += 1
    y = 1370000
    if stats:
        x = 457200
        for label, value in stats:
            shapes.append(rect(spid, x, y, 1850000, 1050000, THEME["primary"])); spid += 1
            shapes.append(textbox(spid, value, x + 120000, y + 150000, 1600000, 420000, 3000, THEME["white"], True)); spid += 1
            shapes.append(textbox(spid, label, x + 120000, y + 620000, 1600000, 280000, 1200, THEME["white"], False)); spid += 1
            x += 2050000
        y += 1350000
    for line in lines:
        shapes.append(textbox(spid, line, 640000, y, 7800000, 380000, 1400, body_color, False))
        spid += 1
        shapes.append(rect(spid, 457200, y + 90000, 90000, 90000, THEME["primary"] if not dark else THEME["highlight"]))
        spid += 1
        y += 520000
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>{''.join(shapes)}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"""


def rect(spid, x, y, w, h, color):
    return f"""<p:sp><p:nvSpPr><p:cNvPr id="{spid}" name="Shape {spid}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:ln><a:noFill/></a:ln></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>"""


def textbox(spid, text, x, y, w, h, size, color, bold):
    b = "<a:b/>" if bold else ""
    return f"""<p:sp><p:nvSpPr><p:cNvPr id="{spid}" name="Text {spid}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr><p:txBody><a:bodyPr wrap="square"><a:spAutoFit/></a:bodyPr><a:lstStyle/><a:p><a:r><a:rPr lang="en-US" sz="{size}">{b}<a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:latin typeface="DejaVu Sans"/></a:rPr><a:t>{docx_escape(text)}</a:t></a:r></a:p></p:txBody></p:sp>"""


def make_pptx(summary):
    slides = [
        ("Document Automation Pilot Review", ["Turnaround accelerated, rework fell, and reviewers reported a better authoring experience.", "Recommendation: extend the pilot one quarter with clearer review ownership."], True, [("Turnaround", "5d to 2d"), ("Rework", "14 to 4"), ("Throughput", "18 to 42")]),
        ("What Changed", ["Template standardization reduced formatting churn.", "Automation shifted work from manual assembly to structured review.", "Shared theme governance will make outputs more consistent."], False, None),
        ("Pilot Metrics", [f"{s['label']}: {fmt_num(s['baseline'])} to {fmt_num(s['pilot'])} {s['unit']} ({s['pct']:+.0f}%)." for s in summary], False, None),
        ("Risks and Controls", ["Source data quality remains inconsistent across inputs.", "Final review ownership is not yet explicit.", "Add a checklist for completeness, formatting, and approval handoff."], False, None),
        ("Next Quarter Plan", ["Continue the pilot with a success scorecard.", "Publish the shared Tech Innovation theme package.", "Review outcomes after one additional quarter before scaling."], True, None),
    ]
    content_types = ['<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>', '<Default Extension="xml" ContentType="application/xml"/>', '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>']
    for i in range(1, 6):
        content_types.append(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>')
    pres_sld_ids = "".join(f'<p:sldId id="{255+i}" r:id="rId{i}"/>' for i in range(1, 6))
    pres = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldIdLst>{pres_sld_ids}</p:sldIdLst><p:sldSz cx="9144000" cy="5143500" type="screen16x9"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>"""
    pres_rels = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">" + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>' for i in range(1, 6)) + "</Relationships>"
    out = OUT / "document_automation_pilot_summary.pptx"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">" + "".join(content_types) + "</Types>")
        z.writestr("_rels/.rels", rels)
        z.writestr("ppt/presentation.xml", pres)
        z.writestr("ppt/_rels/presentation.xml.rels", pres_rels)
        for i, slide in enumerate(slides, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", slide_xml(*slide))
    return out


def main():
    _, rows = read_inputs()
    summary = metric_summary(rows)
    sections = build_memo_sections(summary)
    created = [make_docx(summary, sections), make_pdf(sections), make_pptx(summary)]
    (OUT / "artifact_manifest.txt").write_text("\n".join(str(p.name) for p in created) + "\n", encoding="utf-8")
    for path in created:
        print(path)


if __name__ == "__main__":
    main()
