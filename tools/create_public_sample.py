"""Generate the public, fictional project report used by the sample workspace."""
from pathlib import Path

import fitz


def main():
    destination = Path(__file__).resolve().parents[1] / "frontend/public/samples/project-status.pdf"
    pdf = fitz.open()
    page = pdf.new_page(width=612, height=792)

    def line(y, text, size=11, bold=False):
        page.insert_text((56, y), text, fontsize=size, fontname="helv" if not bold else "hebo", color=(0.12, 0.19, 0.15))

    line(68, "OPERATIONS / PROJECT REPORT", 10, True)
    line(105, "Q2 Service Reliability Review", 22, True)
    line(130, "Fictional sample document  |  April - June 2026", 10)
    page.draw_line((56, 150), (556, 150), color=(0.7, 0.76, 0.7), width=0.8)

    line(187, "Overview", 13, True)
    line(212, "The Atlas service handled 1.8 million requests during Q2.")
    line(231, "Availability was 99.93%, below the 99.95% quarterly target.")
    line(250, "The largest incident was a 37-minute outage on May 14.")

    line(296, "Incident review", 13, True)
    line(321, "A database connection pool limit caused the May 14 outage.")
    line(340, "The team increased the pool limit, added connection saturation")
    line(359, "alerts, and tested the fix under peak traffic.")

    line(405, "Quarterly measures", 13, True)
    top = 426
    lefts = [56, 280, 420, 556]
    for x in lefts:
        page.draw_line((x, top), (x, top + 122), color=(0.67, 0.73, 0.68), width=0.7)
    for y in [top, top + 31, top + 61, top + 91, top + 122]:
        page.draw_line((56, y), (556, y), color=(0.67, 0.73, 0.68), width=0.7)
    for y, values in [(447, ("Measure", "Result", "Target")), (478, ("Availability", "99.93%", "99.95%")), (508, ("Requests", "1.8 million", "1.5 million")), (538, ("P95 latency", "182 ms", "200 ms"))]:
        for x, value in zip([65, 289, 429], values):
            page.insert_text((x, y), value, fontsize=10, fontname="hebo" if y == 447 else "helv")

    line(600, "Next steps", 13, True)
    line(625, "Run a monthly saturation test and review alert thresholds.")
    line(644, "Owner: Platform Engineering. Due date: July 15, 2026.")
    line(735, "Fictional example for document review. No real company data.", 9)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(destination)
    pdf.close()

    for sample in destination.parent.glob("*.pdf"):
        with fitz.open(sample) as source:
            for number, page in enumerate(source, 1):
                image = sample.with_name(f"{sample.stem}-page-{number}.png")
                page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False).save(image)


if __name__ == "__main__":
    main()
