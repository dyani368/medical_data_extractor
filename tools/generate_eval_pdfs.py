"""Create the eight one-page synthetic documents listed in eval/corpus.json."""
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "eval" / "corpus.json").read_text(encoding="utf-8"))
OUT = ROOT / "output" / "pdf" / "eval_corpus"


def make_pdf(document):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / document["filename"]
    pdf = SimpleDocTemplate(str(path), pagesize=letter, rightMargin=0.7*inch,
                            leftMargin=0.7*inch, topMargin=0.65*inch, bottomMargin=0.65*inch)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="DocTitle", parent=styles["Title"], fontSize=17,
                              leading=21, alignment=TA_CENTER, textColor=colors.HexColor("#17365D"),
                              spaceAfter=7))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], fontSize=11,
                              leading=14, textColor=colors.HexColor("#176B72"), spaceBefore=9, spaceAfter=3))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontSize=9.5, leading=13))
    story = [Paragraph("SYNTHETIC DEMO RECORD - NOT REAL PATIENT DATA", styles["BodyText"]),
             Spacer(1, 8), Paragraph(document["title"], styles["DocTitle"]),
             Paragraph(f"Fictional record: {document['patient']}", styles["BodyText"]), Spacer(1, 9)]
    if document["style"] == "table":
        rows = [["Section", "Record details"]]
        rows.extend([[Paragraph(f"<b>{heading}</b>", styles["BodySmall"]),
                      Paragraph(body.replace("&", "&amp;"), styles["BodySmall"])]
                     for heading, body in document["sections"].items()])
        table = Table(rows, colWidths=[1.45*inch, 5.25*inch], repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE6F1")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#17365D")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#9AAFC4")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0,0),(-1,-1),7),
            ("RIGHTPADDING", (0,0),(-1,-1),7), ("TOPPADDING", (0,0),(-1,-1),7),
            ("BOTTOMPADDING", (0,0),(-1,-1),7),
        ]))
        story.append(table)
    else:
        for heading, body in document["sections"].items():
            story.append(KeepTogether([Paragraph(heading, styles["Section"]),
                                       Paragraph(body.replace("&", "&amp;"), styles["BodySmall"])]))
    story.extend([Spacer(1, 16), Paragraph("For software testing only. Fictional educational sample; not medical advice.",
                                           styles["Italic"])])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#C8D3DF"))
        canvas.line(0.7*inch, 0.48*inch, 7.8*inch, 0.48*inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#586879"))
        canvas.drawString(0.7*inch, 0.3*inch, "Synthetic RAG evaluation corpus")
        canvas.drawRightString(7.8*inch, 0.3*inch, f"Page {doc.page}")
        canvas.restoreState()

    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    print(path)


if __name__ == "__main__":
    for item in DATA["documents"]:
        make_pdf(item)
