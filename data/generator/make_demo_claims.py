"""Generate DEMO claim PDFs for manual testing in the web app.

These are separate from the 20 labeled test claims in data/claims, so the automated
tests are not affected. Every name, ID, and code is fictional.

Some claims leave out required fields (to test "documents requested"), one pair shows
a corrected resubmission, and two are scanned images (to test OCR with missing fields).

Run from the project root:

    python data/generator/make_demo_claims.py

Output: data/claims/demo*.pdf and data/claims/DEMO_GUIDE.md
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "claims"

# Full set of fields. A value of None means the line is left off the form entirely.
COMPLETE = {
    "Claim ID": "CLM-DEMO-0001",
    "Member ID": "MBR-DEMO-101",
    "Policy Number": "POL-HC-5599",
    "Provider ID": "PRV-0042",
    "Provider Name": "Sample City Clinic",
    "Service Date": "2026-10-05",
    "Diagnosis Code": "J06.9",
    "Procedure Code": "99213",
    "Billed Amount": "180.00 USD",
    "Claimed Amount": "180.00 USD",
    "Documents Attached": "Claim Form, Prescription",
}


def claim(**changes):
    """Start from the complete claim and apply changes. Use None to drop a field."""
    data = dict(COMPLETE)
    for key, value in changes.items():
        data[key.replace("_", " ").title().replace("Id", "ID")] = value
    return data


def lines_of(fields: dict):
    return [(k, v) for k, v in fields.items() if v is not None]


def write_text_pdf(path: Path, fields: dict) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 60
    c.setFont("Helvetica-Bold", 16)
    c.drawString(60, y, "SYNTHETIC Healthcare Insurance Claim Form")
    c.setFont("Helvetica", 9)
    c.drawString(60, y - 16, "Fictional demo data for a training project. Not a real claim.")
    y -= 50
    c.setFont("Helvetica", 12)
    for key, value in lines_of(fields):
        c.drawString(60, y, f"{key}: {value}")
        y -= 22
    c.save()


def write_scanned_pdf(path: Path, fields: dict) -> None:
    """Render the form to an image, so the PDF has no text layer and OCR is needed."""
    img = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 30)
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
        title_font = font
    draw.text((80, 80), "SYNTHETIC Healthcare Insurance Claim Form", fill="black", font=title_font)
    y = 220
    for key, value in lines_of(fields):
        draw.text((80, y), f"{key}: {value}", fill="black", font=font)
        y += 60
    tmp = path.with_suffix(".tmp.png")
    img.save(tmp)
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.drawImage(ImageReader(str(tmp)), 0, 0, width=w, height=h)
    c.save()
    tmp.unlink()


# (file name, fields, scanned?, what it tests, expected route, expected decision)
DEMOS = [
    ("demo01_complete_approve.pdf",
     claim(), False,
     "Complete claim, routine visit. Should be approved.",
     "approval", "APPROVED"),

    ("demo02_missing_diagnosis.pdf",
     claim(claim_id="CLM-DEMO-0002", diagnosis_code=None), False,
     "Diagnosis code missing. Should ask for documents.",
     "clarification", "PENDING_DOCUMENTS"),

    ("demo03_missing_diagnosis_CORRECTED.pdf",
     claim(claim_id="CLM-DEMO-0002"), False,
     "Corrected version of demo02 with the diagnosis added. Use it to test resubmission.",
     "approval", "APPROVED"),

    ("demo04_missing_policy_number.pdf",
     claim(claim_id="CLM-DEMO-0004", policy_number=None), False,
     "Policy number missing. Should ask for documents.",
     "clarification", "PENDING_DOCUMENTS"),

    ("demo05_missing_service_date.pdf",
     claim(claim_id="CLM-DEMO-0005", service_date=None), False,
     "Service date missing. Should ask for documents.",
     "clarification", "PENDING_DOCUMENTS"),

    ("demo06_missing_amounts.pdf",
     claim(claim_id="CLM-DEMO-0006", billed_amount=None, claimed_amount=None), False,
     "Both amounts missing. Should ask for documents and list both fields.",
     "clarification", "PENDING_DOCUMENTS"),

    ("demo07_missing_procedure_code.pdf",
     claim(claim_id="CLM-DEMO-0007", procedure_code=None), False,
     "Procedure code missing. Should ask for documents.",
     "clarification", "PENDING_DOCUMENTS"),

    ("demo08_several_missing_fields.pdf",
     claim(claim_id="CLM-DEMO-0008", member_id=None, diagnosis_code=None, service_date=None), False,
     "Three fields missing at once. Should list all three.",
     "clarification", "PENDING_DOCUMENTS"),

    ("demo09_blank_diagnosis_line.pdf",
     claim(claim_id="CLM-DEMO-0009", diagnosis_code="________"), False,
     "Diagnosis line present but left blank. Should count as missing.",
     "clarification", "PENDING_DOCUMENTS"),

    ("demo10_policy_waiting_period.pdf",
     claim(claim_id="CLM-DEMO-0010", service_date="2026-08-15",
           procedure_code="15820", billed_amount="2400.00 USD", claimed_amount="2400.00 USD"), False,
     "Service inside the waiting period and an excluded procedure. Should be rejected after review.",
     "rejection_review", "REJECTED"),

    ("demo11_duplicate_of_history.pdf",
     claim(claim_id="CLM-DEMO-0011", member_id="MBR-99901", policy_number="POL-HC-5599",
           provider_id="PRV-0042", service_date="2026-08-14", diagnosis_code="J06.9",
           procedure_code="99213", billed_amount="180.00 USD", claimed_amount="180.00 USD"), False,
     "Matches the seeded history claim CLM-2026-HIST-001. Should be escalated for investigation.",
     "investigation", "ESCALATED"),

    ("demo12_high_amount.pdf",
     claim(claim_id="CLM-DEMO-0012", procedure_code="99213",
           billed_amount="2100.00 USD", claimed_amount="2100.00 USD"), False,
     "Billed amount about eleven times the typical rate. Should be escalated.",
     "investigation", "ESCALATED"),

    ("demo13_scanned_missing_diagnosis.pdf",
     claim(claim_id="CLM-DEMO-0013", diagnosis_code=None), True,
     "Scanned image with diagnosis missing. Tests OCR together with missing fields.",
     "clarification", "PENDING_DOCUMENTS"),

    ("demo14_scanned_complete.pdf",
     claim(claim_id="CLM-DEMO-0014"), True,
     "Scanned image, complete claim. Tests OCR on a clean claim.",
     "approval", "APPROVED"),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, fields, scanned, purpose, route, decision in DEMOS:
        path = OUT / name
        if scanned:
            write_scanned_pdf(path, fields)
        else:
            write_text_pdf(path, fields)
        rows.append((name, purpose, route, decision))

    guide = [
        "# Demo claims guide",
        "",
        "All claims are synthetic. Upload each PDF in the web app and compare the result with the table.",
        "",
        "| File | What it tests | Expected route | Expected decision |",
        "|---|---|---|---|",
    ]
    for name, purpose, route, decision in rows:
        guide.append(f"| {name} | {purpose} | {route} | {decision} |")
    guide += [
        "",
        "Resubmission test: upload demo02 first, reject it with Request documents, then upload demo03 "
        "using the resubmit section. The new run should be linked to the original.",
    ]
    (OUT / "DEMO_GUIDE.md").write_text("\n".join(guide) + "\n")
    print(f"Generated {len(rows)} demo PDFs in {OUT}")


if __name__ == "__main__":
    main()
