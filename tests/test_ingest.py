import random
import sys
from pathlib import Path

import pytest

from app.ingest import UnreadablePDF, group_into_lines, read_pdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "samples"))
from generate import make_invoice, to_pdf, to_scan  # noqa: E402


def test_fragments_are_put_back_in_reading_order():
    boxes = [
        (300, 101, 20, "Total"),
        (500, 103, 20, "99.00"),
        (100, 50, 20, "Invoice"),
        (250, 52, 20, "INV-1"),
    ]
    assert group_into_lines(boxes) == ["Invoice INV-1", "Total 99.00"]


def test_rejects_files_that_are_not_pdfs():
    with pytest.raises(UnreadablePDF):
        read_pdf(b"this is a text file")


def test_rejects_a_corrupt_pdf():
    with pytest.raises(UnreadablePDF):
        read_pdf(b"%PDF-1.7 and then nothing useful")


def test_digital_pdf_uses_the_text_layer():
    inv = make_invoice(random.Random(1))
    result = read_pdf(to_pdf(inv, "A"))
    assert result.method == "text"
    assert any(inv["invoice_number"] in line for line in result.lines)


def test_scanned_pdf_goes_through_ocr():
    rng = random.Random(1)
    inv = make_invoice(rng)
    result = read_pdf(to_scan(to_pdf(inv, "A"), rng))
    assert result.method == "ocr"
    assert any(inv["invoice_number"] in line for line in result.lines)
