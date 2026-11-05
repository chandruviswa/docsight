import pytest

from app.extract import extract_fields, extract_line_items


def value(fields, name):
    return fields[name]["value"] if fields[name] else None


CLEAN = """Northwind Traders Ltd INVOICE
14 Mill Road, Leeds
Invoice Number: INV-1042
Invoice Date: March 03, 2026
Due Date: April 02, 2026
PO Number: PO55123
Bill To:
Fairview Hospital Trust
Description Qty Unit Price Amount
Toner cartridge 2 45.00 90.00
Subtotal: USD 90.00
Tax (10%): USD 9.00
Total: USD 99.00""".splitlines()

# The same invoice the way OCR returned it from a poor scan.
GLUED = """INVOICE
NorthwindTradersLtd
InvoiceNumber:INV-1042
InvoiceDate:March03,2026
DueDate:April02,2026
PONumber:PO55123
Bill To:
FairviewHospitalTrust
Tonercartridge 2 45.00 90.00
Subtotal:USD90.00
Tax(10%):USD9.00
Total:USD99.00""".splitlines()


@pytest.mark.parametrize("lines", [CLEAN, GLUED], ids=["clean", "ocr_glued"])
@pytest.mark.parametrize(
    "field,expected",
    [
        ("invoice_number", "INV-1042"),
        ("invoice_date", "2026-03-03"),
        ("due_date", "2026-04-02"),
        ("po_number", "PO55123"),
        ("customer", "Fairview Hospital Trust"),
        ("currency", "USD"),
        ("subtotal", "90.00"),
        ("tax", "9.00"),
        ("total", "99.00"),
    ],
)
def test_common_fields(lines, field, expected):
    assert value(extract_fields(lines), field) == expected


def test_vendor_comes_from_the_letterhead():
    fields = extract_fields(CLEAN)
    assert value(fields, "vendor") == "Northwind Traders Ltd"
    assert fields["vendor"]["source"] in ("ner", "heuristic")


def test_labelled_vendor_beats_the_letterhead():
    fields = extract_fields(["Some Header Co", "Seller: Tessera Software Inc", "Total 5.00"])
    assert value(fields, "vendor") == "Tessera Software Inc"
    assert fields["vendor"]["source"] == "label"


def test_subtotal_is_not_mistaken_for_total():
    fields = extract_fields(["Sub Total 10.00", "GST 1.00"])
    assert value(fields, "subtotal") == "10.00"
    assert fields["total"]["source"] == "heuristic"


def test_due_date_is_not_mistaken_for_invoice_date():
    fields = extract_fields(["Due Date: 2026-05-01", "Date: 2026-04-01"])
    assert value(fields, "invoice_date") == "2026-04-01"
    assert value(fields, "due_date") == "2026-05-01"


def test_iso_dates_are_not_read_day_first():
    fields = extract_fields(["Date: 2026-03-04"])
    assert value(fields, "invoice_date") == "2026-03-04"


def test_slash_dates_are_day_first():
    fields = extract_fields(["Date: 04/03/2026"])
    assert value(fields, "invoice_date") == "2026-03-04"


def test_nonsense_date_is_ignored():
    fields = extract_fields(["Date: 45/13/2026"])
    assert fields["invoice_date"] is None


def test_ocr_misreads_in_amounts_are_repaired():
    assert value(extract_fields(["GST$O.00"]), "tax") == "0.00"
    assert value(extract_fields(["SubTotalGBP59.321.36"]), "subtotal") == "59321.36"


def test_lowercase_l_for_capital_i_is_repaired():
    fields = extract_fields(["Seller: lronbridge Tools Pvt Ltd"])
    assert value(fields, "vendor") == "Ironbridge Tools Pvt Ltd"


def test_empty_document_finds_nothing():
    assert all(field is None for field in extract_fields([]).values())


def test_guesses_are_labelled_as_guesses():
    fields = extract_fields(["Thanks for your business", "1,200.00", "99.00", "12.03.2026"])
    assert value(fields, "total") == "1200.00"
    assert fields["total"]["source"] == "heuristic"
    assert fields["invoice_date"]["source"] == "heuristic"


def test_line_items():
    items = extract_line_items(["Toner cartridge 2 45.00 90.00", "Label printer 1 1,250.00 1,250.00"])
    assert [i["amount"] for i in items] == ["90.00", "1250.00"]
    assert items[0]["description"] == "Toner cartridge"


def test_row_that_does_not_multiply_out_is_not_a_line_item():
    assert extract_line_items(["Delivery 12 2026 5.00 99.00"]) == []
