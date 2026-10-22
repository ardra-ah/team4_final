"""Generate SYNTHETIC claim PDFs, a policy PDF, labels, and Postgres seed SQL.

Every name, ID, and code here is fictional. No real patient or government
identifiers are produced. Run from the project root:

    python3 data/generator/generate_claims.py
"""

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parents[2]
CLAIMS_DIR = ROOT / "data" / "claims"
POLICY_DIR = ROOT / "data" / "policies"
DB_DIR = ROOT / "data" / "db"

random.seed(42)

CLAIM_LIMIT_USD = 5000.00
WAITING_PERIOD_DAYS = 30
POLICY_EFFECTIVE = "2026-08-01"

PROVIDERS = [
    ("PRV-0042", "Sample City Clinic"),
    ("PRV-0107", "Demo General Hospital"),
    ("PRV-0215", "Fictional Diagnostics Lab"),
]

# (scenario, count) -- 20 claims total
SCENARIOS = [
    ("clean", 8),
    ("missing_field", 4),
    ("policy_violation", 4),
    ("duplicate", 2),
    ("high_fraud", 2),
]

EXPECTED = {
    "clean": ("approval", "APPROVED", []),
    "missing_field": ("clarification", "PENDING_DOCUMENTS", ["diagnosis_code"]),
    "policy_violation": ("rejection_review", "REJECTED", []),
    "duplicate": ("investigation", "ESCALATED", []),
    "high_fraud": ("investigation", "ESCALATED", []),
}


def claim_lines(claim: dict) -> list:
    """Render the claim as label: value lines. Extraction parses these labels."""
    lines = [
        ("Claim ID", claim["claim_id"]),
        ("Member ID", claim["member_id"]),
        ("Policy Number", claim["policy_number"]),
        ("Member Name", claim["member_name"]),
        ("Provider ID", claim["provider_id"]),
        ("Provider Name", claim["provider_name"]),
        ("Service Date", claim["service_date"]),
        ("Diagnosis Code", claim["diagnosis_code"]),
        ("Procedure Code", claim["procedure_code"]),
        ("Billed Amount", f"{claim['billed_amount']:.2f} USD"),
        ("Claimed Amount", f"{claim['claimed_amount']:.2f} USD"),
        ("Documents Attached", ", ".join(claim["documents_attached"]) or "None"),
    ]
    return [(k, v) for k, v in lines if v is not None]


def write_text_pdf(path: Path, claim: dict) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 60
    c.setFont("Helvetica-Bold", 16)
    c.drawString(60, y, "SYNTHETIC Healthcare Insurance Claim Form")
    c.setFont("Helvetica", 9)
    c.drawString(60, y - 16, "Fictional test data for a training project. Not a real claim.")
    y -= 50
    c.setFont("Helvetica", 12)
    for key, value in claim_lines(claim):
        c.drawString(60, y, f"{key}: {value}")
        y -= 22
    c.save()


def write_scanned_pdf(path: Path, claim: dict) -> None:
    """Render claim text to an image and embed it, so the PDF has no text layer."""
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
    for key, value in claim_lines(claim):
        draw.text((80, y), f"{key}: {value}", fill="black", font=font)
        y += 60
    tmp = path.with_suffix(".tmp.png")
    img.save(tmp)
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.drawImage(ImageReader(str(tmp)), 0, 0, width=w, height=h)
    c.save()
    tmp.unlink()


def write_policy_pdf(path: Path) -> str:
    styles = getSampleStyleSheet()
    body = [
        Paragraph("SYNTHETIC Healthcare Policy Guidelines (Fictional)", styles["Title"]),
        Spacer(1, 12),
        Paragraph("<b>1. Coverage Limit.</b> The maximum payable amount per claim is "
                  f"USD {CLAIM_LIMIT_USD:,.2f}. Amounts above this limit are not covered.", styles["BodyText"]),
        Paragraph("<b>2. Waiting Period.</b> Services dated within "
                  f"{WAITING_PERIOD_DAYS} days of the policy effective date ({POLICY_EFFECTIVE}) "
                  "are not covered. Services dated after the waiting period are eligible.", styles["BodyText"]),
        Paragraph("<b>3. Exclusions.</b> Cosmetic procedures, including CPT 15820 and 15821, are excluded "
                  "from coverage.", styles["BodyText"]),
        Paragraph("<b>4. Covered Procedures.</b> CPT 99213 (office visit), 80053 (metabolic panel), "
                  "71046 (chest X-ray), and 27447 (knee replacement) are covered subject to limits.",
                  styles["BodyText"]),
        Paragraph("<b>5. Required Documents.</b> Every claim requires a completed claim form and a diagnosis "
                  "code. Procedures billed above USD 1,000 also require a prescription or referral.",
                  styles["BodyText"]),
        Paragraph("<b>6. Fraud Guidance.</b> A claim whose billed amount is more than ten times the typical "
                  "rate for its procedure, or that duplicates an existing claim (same member, provider, "
                  "service date, and procedure), must be routed to investigation.", styles["BodyText"]),
        Paragraph("<b>7. Decisions.</b> Coverage-valid, low-risk claims may be approved. Policy failures are "
                  "rejected after review. Missing required information is returned as PENDING_DOCUMENTS.",
                  styles["BodyText"]),
    ]
    SimpleDocTemplate(str(path), pagesize=A4).build(body)
    return str(path)


def build_claims() -> tuple:
    claims, labels, history = [], [], []
    seq = 0
    base_history_id = 0

    # Pre-existing claim history used for duplicate detection (seeded into Postgres).
    history_claim = {
        "claim_id": "CLM-2026-HIST-001", "member_id": "MBR-99901", "policy_number": "POL-HC-5599",
        "member_name": "Synthetic Member 03", "provider_id": "PRV-0042", "provider_name": PROVIDERS[0][1],
        "service_date": "2026-08-14", "diagnosis_code": "J06.9", "procedure_code": "99213",
        "billed_amount": 180.00, "claimed_amount": 180.00, "documents_attached": ["Claim Form", "Prescription"],
    }
    history.append(history_claim)

    for scenario, count in SCENARIOS:
        for i in range(count):
            seq += 1
            cid = f"CLM-2026-{seq:04d}"
            member_num = 10001 + seq
            provider_id, provider_name = PROVIDERS[seq % len(PROVIDERS)]
            claim = {
                "claim_id": cid,
                "member_id": f"MBR-{member_num}",
                "policy_number": f"POL-HC-{5500 + seq}",
                "member_name": f"Synthetic Member {seq:02d}",
                "provider_id": provider_id,
                "provider_name": provider_name,
                "service_date": f"2026-{random.randint(8, 10):02d}-{random.randint(1, 28):02d}",
                "diagnosis_code": random.choice(["J06.9", "E11.9", "M17.11", "I10"]),
                "procedure_code": "99213",
                "billed_amount": 180.00,
                "claimed_amount": 180.00,
                "documents_attached": ["Claim Form", "Prescription"],
            }
            expected_missing = []

            if scenario == "clean":
                claim["procedure_code"] = random.choice(["99213", "80053", "71046"])
                claim["billed_amount"] = claim["claimed_amount"] = round(random.uniform(90, 400), 2)
                claim["service_date"] = f"2026-{random.randint(9, 10):02d}-{random.randint(10, 28):02d}"

            elif scenario == "missing_field":
                claim["diagnosis_code"] = None
                claim["documents_attached"] = ["Claim Form"]
                expected_missing = ["diagnosis_code"]

            elif scenario == "policy_violation":
                # Service inside the waiting period (policy effective 2026-08-01 + 30 days).
                claim["service_date"] = "2026-08-15"
                claim["procedure_code"] = "15820"  # cosmetic exclusion
                claim["billed_amount"] = claim["claimed_amount"] = 2400.00

            elif scenario == "duplicate":
                claim.update({
                    "member_id": history_claim["member_id"],
                    "member_name": history_claim["member_name"],
                    "policy_number": history_claim["policy_number"],
                    "provider_id": history_claim["provider_id"],
                    "provider_name": history_claim["provider_name"],
                    "service_date": history_claim["service_date"],
                    "procedure_code": "99213",
                    "billed_amount": 180.00,
                    "claimed_amount": 180.00,
                })

            elif scenario == "high_fraud":
                claim["procedure_code"] = "99213"
                claim["billed_amount"] = claim["claimed_amount"] = 2100.00  # ~11x typical rate

            claims.append((claim, scenario, expected_missing))

    # Expected labels
    for claim, scenario, expected_missing in claims:
        path_name, decision, _ = EXPECTED[scenario]
        labels.append({
            "claim_id": claim["claim_id"],
            "scenario": scenario,
            "expected_path": path_name,
            "expected_decision": decision,
            "expected_missing_fields": expected_missing,
        })
    return [c for c, _, _ in claims], labels, history


def write_seed_sql(history: list) -> None:
    rows = []
    for h in history:
        rows.append(
            "INSERT INTO claims_history (claim_id, member_id, policy_number, provider_id, service_date, "
            "procedure_code, billed_amount, claimed_amount) VALUES "
            f"('{h['claim_id']}', '{h['member_id']}', '{h['policy_number']}', '{h['provider_id']}', "
            f"'{h['service_date']}', '{h['procedure_code']}', {h['billed_amount']}, {h['claimed_amount']});"
        )
    for pid, pname in PROVIDERS:
        rows.append(f"INSERT INTO providers (provider_id, provider_name) VALUES ('{pid}', '{pname}');")
    rows.append(
        "INSERT INTO policy_master (policy_number, effective_date, claim_limit_usd, waiting_period_days) VALUES "
        f"('POL-HC-5599', '{POLICY_EFFECTIVE}', {CLAIM_LIMIT_USD}, {WAITING_PERIOD_DAYS});"
    )
    (DB_DIR / "seed.sql").write_text("\n".join(rows) + "\n")


def main() -> None:
    for d in (CLAIMS_DIR, POLICY_DIR, DB_DIR):
        d.mkdir(parents=True, exist_ok=True)

    claims, labels, history = build_claims()

    for idx, claim in enumerate(claims):
        label_scenario = labels[idx]["scenario"]
        name = f"{claim['claim_id']}_{label_scenario}"
        if idx == 0:
            write_scanned_pdf(CLAIMS_DIR / f"{name}.pdf", claim)  # one scanned claim tests OCR fallback
        else:
            write_text_pdf(CLAIMS_DIR / f"{name}.pdf", claim)

    (CLAIMS_DIR / "labels.json").write_text(json.dumps(labels, indent=2) + "\n")
    write_policy_pdf(POLICY_DIR / "policy_guidelines.pdf")
    write_seed_sql(history)
    print(f"Generated {len(claims)} claim PDFs, labels.json, policy PDF, and seed.sql")


if __name__ == "__main__":
    main()
