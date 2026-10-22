"""OCR Agent: returns raw text for a claim PDF.

Strategy:
1. Read the embedded text layer with PyMuPDF (fast, exact for digital PDFs).
2. If a page has no text layer (scanned PDF), render it to an image and run
   RapidOCR. RapidOCR is pip-installable and bundles its models, so it works
   on machines that block the Tesseract installer.
"""

import tempfile
from pathlib import Path
from typing import Optional, Tuple

import fitz  # PyMuPDF

MIN_TEXT_CHARS = 20
_engine = None


def _get_engine():
    """Load RapidOCR once; model load is slow."""
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    return _engine


def _ocr_page(page: fitz.Page) -> str:
    pix = page.get_pixmap(dpi=200)
    with tempfile.TemporaryDirectory() as tmp:
        img_path = Path(tmp) / "page.png"
        pix.save(str(img_path))
        result, _ = _get_engine()(str(img_path))
    if not result:
        return ""
    # Each detection is [box, text, confidence]; keep one text line per detection.
    return "\n".join(item[1] for item in result)


def extract_text(pdf_path: str) -> Tuple[str, str]:
    """Return (raw_text, source_format). source_format is 'text_pdf' or 'scanned_pdf'."""
    doc = fitz.open(pdf_path)
    try:
        pages_text = []
        used_ocr = False
        for page in doc:
            text = page.get_text("text")
            if len(text.strip()) < MIN_TEXT_CHARS:
                text = _ocr_page(page)
                used_ocr = True
            pages_text.append(text)
        raw = "\n".join(pages_text)
        return raw, ("scanned_pdf" if used_ocr else "text_pdf")
    finally:
        doc.close()