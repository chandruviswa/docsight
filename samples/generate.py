"""Generates labelled invoice PDFs for the evaluation set.

Templates A, B and C are what the extractor was written against. Template D is
held out: its layout and wording were never used while writing the rules, so its
score is the closest thing here to "what happens on an invoice we haven't seen".

    python samples/generate.py --out samples/data --per-template 25
"""

import argparse
import io
import json
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pypdfium2
from PIL import Image, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

VENDORS = [
    "Northwind Traders Ltd", "Bluewater Logistics LLC", "Kaveri Industrial Supplies Pvt Ltd",
    "Halden Print Works GmbH", "Summit Office Solutions Inc", "Redwood Packaging Co",
    "Meridian Electrical Ltd", "Orchard Lane Foods LLC", "Tessera Software Inc",
    "Coastal Marine Parts Ltd", "Ironbridge Tools Pvt Ltd", "Lumen Lighting GmbH",
]
CUSTOMERS = [
    "Fairview Hospital Trust", "Atlas Construction Group", "Greenfield Retail Ltd",
    "Sundar Textiles Pvt Ltd", "Harbor Point Hotels Inc", "Delta Freight Services LLC",
    "Willow Creek Schools", "Pinnacle Engineering Co", "Vega Pharma Ltd",
    "Oakline Furniture Inc",
]
ITEMS = [
    "Packing tape, 48mm", "A4 copier paper", "Safety gloves, large", "LED panel 40W",
    "Steel shelving unit", "Toner cartridge", "Cable ties, pack of 100", "Annual support plan",
    "Hand sanitizer, 5L", "Pallet wrap film", "Label printer", "Consulting, per day",
]
STREETS = ["14 Mill Road", "220 Harbor Ave", "7 Station Street", "88 Anna Salai", "3 Kings Way"]
CITIES = ["Leeds", "Portland", "Chennai", "Hamburg", "Austin"]
CENT = Decimal("0.01")


def make_invoice(rng):
    issued = date(2025, 1, 1) + timedelta(days=rng.randint(0, 600))
    lines = []
    for item in rng.sample(ITEMS, rng.randint(2, 6)):
        qty = rng.randint(1, 40)
        price = Decimal(rng.randint(250, 90000)) / 100
        lines.append(
            {"description": item, "qty": qty, "price": price, "amount": (qty * price).quantize(CENT)}
        )
    subtotal = sum(line["amount"] for line in lines)
    rate = rng.choice([0, 5, 8, 12, 18, 20])
    tax = (subtotal * rate / 100).quantize(CENT, ROUND_HALF_UP)
    prefix = rng.choice(["INV", "INV", "BILL", "SI", "A"])
    return {
        "invoice_number": f"{prefix}-{rng.randint(1000, 99999)}",
        "invoice_date": issued,
        "due_date": issued + timedelta(days=rng.choice([14, 30, 45, 60])),
        "po_number": f"PO{rng.randint(10000, 99999)}" if rng.random() < 0.6 else None,
        "vendor": rng.choice(VENDORS),
        "customer": rng.choice(CUSTOMERS),
        "currency": rng.choice(["USD", "EUR", "INR", "GBP"]),
        "subtotal": subtotal,
        "tax": tax,
        "rate": rate,
        "total": subtotal + tax,
        "lines": lines,
        "address": f"{rng.choice(STREETS)}, {rng.choice(CITIES)}",
    }


def m(value):
    return f"{value:,.2f}"


def items_table(c, inv, y, x=20):
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x * mm, y, "Description")
    c.drawRightString(125 * mm, y, "Qty")
    c.drawRightString(155 * mm, y, "Unit Price")
    c.drawRightString(190 * mm, y, "Amount")
    c.line(x * mm, y - 3, 190 * mm, y - 3)
    c.setFont("Helvetica", 9)
    for line in inv["lines"]:
        y -= 16
        c.drawString(x * mm, y, line["description"])
        c.drawRightString(125 * mm, y, str(line["qty"]))
        c.drawRightString(155 * mm, y, m(line["price"]))
        c.drawRightString(190 * mm, y, m(line["amount"]))
    return y - 10


def template_a(c, inv):
    w, h = A4
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20 * mm, h - 25 * mm, inv["vendor"])
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, h - 31 * mm, inv["address"])
    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(190 * mm, h - 25 * mm, "INVOICE")
    c.setFont("Helvetica", 10)
    y = h - 48 * mm
    rows = [
        f"Invoice Number: {inv['invoice_number']}",
        f"Invoice Date: {inv['invoice_date']:%B %d, %Y}",
        f"Due Date: {inv['due_date']:%B %d, %Y}",
    ]
    if inv["po_number"]:
        rows.append(f"PO Number: {inv['po_number']}")
    for row in rows:
        c.drawString(20 * mm, y, row)
        y -= 14
    y -= 8
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Bill To:")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y - 14, inv["customer"])
    y = items_table(c, inv, y - 44)
    cur = inv["currency"]
    c.drawRightString(190 * mm, y - 6, f"Subtotal: {cur} {m(inv['subtotal'])}")
    c.drawRightString(190 * mm, y - 20, f"Tax ({inv['rate']}%): {cur} {m(inv['tax'])}")
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(190 * mm, y - 36, f"Total: {cur} {m(inv['total'])}")


def template_b(c, inv):
    w, h = A4
    c.setFillGray(0.15)
    c.rect(0, h - 28 * mm, w, 28 * mm, fill=1, stroke=0)
    c.setFillGray(1)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(20 * mm, h - 18 * mm, "TAX INVOICE")
    c.setFillGray(0)
    c.setFont("Helvetica", 10)
    y = h - 40 * mm
    c.drawString(20 * mm, y, "From")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y - 13, inv["vendor"])
    c.setFont("Helvetica", 10)
    y -= 38
    c.drawString(20 * mm, y, "Billed To")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y - 13, inv["customer"])
    c.setFont("Helvetica", 10)
    y -= 38
    c.drawString(20 * mm, y, f"Inv #: {inv['invoice_number']}")
    c.drawString(20 * mm, y - 13, f"Date: {inv['invoice_date']:%d-%b-%Y}")
    c.drawString(20 * mm, y - 26, f"Payment Due: {inv['due_date']:%d-%b-%Y}")
    if inv["po_number"]:
        c.drawString(20 * mm, y - 39, f"Purchase Order: {inv['po_number']}")
    y = items_table(c, inv, y - 66)
    symbol = {"USD": "$", "EUR": "€", "GBP": "GBP ", "INR": "INR "}[inv["currency"]]
    c.drawRightString(190 * mm, y - 6, f"Sub Total {symbol}{m(inv['subtotal'])}")
    c.drawRightString(190 * mm, y - 20, f"GST {symbol}{m(inv['tax'])}")
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(190 * mm, y - 36, f"Amount Due {symbol}{m(inv['total'])}")


def template_c(c, inv):
    w, h = A4
    c.setFont("Helvetica", 9)
    y = h - 20 * mm
    meta = (
        f"Invoice {inv['invoice_number']} | Issued {inv['invoice_date']:%Y-%m-%d}"
        f" | Due {inv['due_date']:%Y-%m-%d}"
    )
    if inv["po_number"]:
        meta += f" | PO: {inv['po_number']}"
    c.drawString(20 * mm, y, meta)
    c.line(20 * mm, y - 5, 190 * mm, y - 5)
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y - 22, f"Seller: {inv['vendor']}")
    c.drawString(20 * mm, y - 36, f"Customer: {inv['customer']}")
    c.drawString(20 * mm, y - 50, f"Currency: {inv['currency']}")
    y = items_table(c, inv, y - 80)
    c.setFont("Helvetica", 10)
    c.drawRightString(190 * mm, y - 6, f"Net {m(inv['subtotal'])}")
    c.drawRightString(190 * mm, y - 20, f"VAT {inv['rate']}% {m(inv['tax'])}")
    c.drawRightString(190 * mm, y - 36, f"Grand Total {m(inv['total'])}")


def template_d(c, inv):
    """Held out. Two column header, unusual labels, dates like 03.11.2025."""
    w, h = A4
    c.setFont("Helvetica-Bold", 12)
    c.drawString(20 * mm, h - 22 * mm, inv["vendor"])
    c.setFont("Helvetica", 10)
    c.drawString(115 * mm, h - 22 * mm, f"Sold To: {inv['customer']}")
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, h - 28 * mm, inv["address"])
    y = h - 42 * mm
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, f"Document No. {inv['invoice_number']}")
    c.drawString(115 * mm, y, f"Dated {inv['invoice_date']:%d.%m.%Y}")
    c.drawString(20 * mm, y - 14, f"Pay by {inv['due_date']:%d.%m.%Y}")
    if inv["po_number"]:
        c.drawString(115 * mm, y - 14, f"Your ref {inv['po_number']}")
    y = items_table(c, inv, y - 44)
    cur = inv["currency"]
    c.drawString(120 * mm, y - 6, f"Goods value {m(inv['subtotal'])} {cur}")
    c.drawString(120 * mm, y - 20, f"Sales tax {m(inv['tax'])} {cur}")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(120 * mm, y - 36, f"Payable {m(inv['total'])} {cur}")


TEMPLATES = {"A": template_a, "B": template_b, "C": template_c, "D": template_d}


def to_pdf(inv, template):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle("Invoice")
    TEMPLATES[template](c, inv)
    c.save()
    return buffer.getvalue()


def to_scan(pdf_bytes, rng):
    """Rasterise a page and rough it up a bit, like a cheap office scanner."""
    page = pypdfium2.PdfDocument(pdf_bytes)[0]
    image = page.render(scale=150 / 72).to_pil().convert("L")
    image = image.rotate(rng.uniform(-1.2, 1.2), fillcolor=255, resample=Image.BICUBIC)
    image = image.filter(ImageFilter.GaussianBlur(rng.uniform(0.2, 0.6)))

    jpeg = io.BytesIO()
    image.save(jpeg, "JPEG", quality=rng.randint(45, 70))
    jpeg.seek(0)

    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4)
    c.drawImage(ImageReader(jpeg), 0, 0, width=A4[0], height=A4[1])
    c.save()
    return out.getvalue()


def truth(inv, template, kind):
    fields = {
        "invoice_number": inv["invoice_number"],
        "invoice_date": inv["invoice_date"].isoformat(),
        "due_date": inv["due_date"].isoformat(),
        "po_number": inv["po_number"],
        "vendor": inv["vendor"],
        "customer": inv["customer"],
        "currency": inv["currency"],
        "subtotal": str(inv["subtotal"]),
        "tax": str(inv["tax"]),
        "total": str(inv["total"]),
    }
    return {
        "template": template,
        "kind": kind,
        "line_item_count": len(inv["lines"]),
        "fields": fields,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="samples/data")
    parser.add_argument("--per-template", type=int, default=25)
    parser.add_argument("--scans-per-template", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260301)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for template in TEMPLATES:
        for i in range(args.per_template):
            inv = make_invoice(rng)
            pdf = to_pdf(inv, template)
            name = f"{template}_{i:03d}"
            (out / f"{name}.pdf").write_bytes(pdf)
            (out / f"{name}.json").write_text(json.dumps(truth(inv, template, "digital"), indent=1))
        for i in range(args.scans_per_template):
            inv = make_invoice(rng)
            pdf = to_scan(to_pdf(inv, template), rng)
            name = f"{template}_scan_{i:03d}"
            (out / f"{name}.pdf").write_bytes(pdf)
            (out / f"{name}.json").write_text(json.dumps(truth(inv, template, "scanned"), indent=1))

    print(f"Wrote {len(list(out.glob('*.pdf')))} PDFs to {out}")


if __name__ == "__main__":
    main()
