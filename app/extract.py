"""Pulls invoice fields out of plain text lines.

Every pattern allows for missing whitespace (\\s*) because OCR on a poor scan often
returns things like "InvoiceDate:November27,2025".

Each field records how it was found. "label" means a label sat right next to it,
"ner" means the language model picked it out, and "heuristic" means an educated guess
that validation should treat with suspicion.
"""

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache

from dateutil import parser as dateparser

FLAGS = re.IGNORECASE

# O for 0 and . for a thousands comma are the two misreads OCR makes most on amounts.
MONEY = re.compile(r"[\dO][\dO,.]*\.[\dO]{2}(?![\dO])")
DATE = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[/.]\d{1,2}[/.]\d{4}"
    r"|\d{1,2}[-\s]?[A-Za-z]{3,9}[-\s]?\d{4}"
    r"|[A-Za-z]{3,9}\s*\d{1,2},?\s*\d{4}"
)
TOKEN = r"([A-Z0-9][A-Z0-9\-/]*\d[A-Z0-9\-/]*)"

INVOICE_NUMBER = re.compile(
    r"(?<![a-z])(?:invoice\s*(?:number|num|no\.?|#)|inv\.?\s*(?:#|no\.?)|invoice)\s*[:#]?\s*" + TOKEN,
    FLAGS,
)
PO_NUMBER = re.compile(
    r"(?<![a-z])(?:purchase\s*order(?:\s*(?:number|no\.?|#))?|p\.?o\.?(?:\s*(?:number|no\.?|#))?)"
    r"\s*[:#]?\s*" + TOKEN,
    FLAGS,
)
DUE_DATE = re.compile(r"(?<![a-z])(?:due\s*date|payment\s*due|due\s*by|due)\s*:?\s*", FLAGS)
INVOICE_DATE = re.compile(
    r"(?<![a-z])(?<!due\s)(?:invoice\s*date|date\s*of\s*issue|issued(?:\s*on)?|date)\s*:?\s*", FLAGS
)

VENDOR_LABEL = re.compile(r"^(?:from|seller|vendor|supplier)\b\s*:?\s*(.*)$", FLAGS)
CUSTOMER_LABEL = re.compile(r"(?<![a-z])(?:bill(?:ed)?\s*to|sold\s*to|customer|client)\s*:?\s*(.*)$", FLAGS)
DOCUMENT_TITLE = re.compile(r"\b(?:tax\s*)?invoice\s*$", FLAGS)
COMPANY_SUFFIX = re.compile(r"\b(?:ltd|llc|inc|gmbh|co|corp|plc|limited|pvt)\b\.?", FLAGS)

# First match wins, so the most specific wording goes first.
TOTAL_LABELS = [
    r"amount\s*due", r"balance\s*due", r"grand\s*total", r"total\s*due", r"invoice\s*total",
    r"total\s*amount", r"(?<!sub)(?<!sub\s)total",
]
SUBTOTAL_LABELS = [r"sub\s*total", r"net\s*(?:amount|total)?(?=[\s\d:])"]
TAX_LABELS = [r"sales\s*tax", r"vat", r"gst", r"tax"]

LINE_ITEM = re.compile(r"^(.+?)\s+(\d+(?:\.\d+)?)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})$")
# Case sensitive, and only uppercase neighbours are ruled out, because OCR gives "TotalGBP64".
ISO_CURRENCY = re.compile(r"(?<![A-Z])(USD|EUR|GBP|INR|AUD|CAD|JPY)(?![A-Z])")
SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}


@dataclass
class Field:
    value: str
    source: str


@lru_cache(maxsize=1)
def _nlp():
    import spacy

    return spacy.load("en_core_web_sm", disable=["lemmatizer", "attribute_ruler"])


def _tidy_name(text):
    """Undo OCR's habit of gluing words together, and trim stray punctuation."""
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    text = text.replace("Gmb H", "GmbH")
    # A capital I read as a lowercase L: "lronbridge". Names here start with a capital.
    text = re.sub(r"\bl(?=[a-z])", "I", text)
    return text.strip(" :,-|")


def _to_iso(raw):
    # dateutil with dayfirst=True reads 2026-03-04 as 3 April, so ISO goes straight through.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            return date.fromisoformat(raw).isoformat()
        except ValueError:
            return None
    spaced = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", raw).replace(",", " ")
    try:
        return dateparser.parse(spaced, dayfirst=True, default=datetime(2000, 1, 1)).date().isoformat()
    except (ValueError, OverflowError):
        return None


def _money_value(raw):
    whole, cents = raw.replace("O", "0").rsplit(".", 1)
    return str(Decimal(re.sub(r"[.,]", "", whole) + "." + cents))


def _find_token(lines, pattern):
    for line in lines:
        match = pattern.search(line)
        if match:
            return Field(match.group(1), "label")
    return None


def _find_labelled_date(lines, pattern):
    for line in lines:
        for label in pattern.finditer(line):
            match = DATE.match(line, label.end())
            if match and (iso := _to_iso(match.group())):
                return Field(iso, "label")
    return None


def _all_dates(lines):
    found = []
    for line in lines:
        for match in DATE.finditer(line):
            if (iso := _to_iso(match.group())) and iso not in found:
                found.append(iso)
    return found


def _find_amount(lines, labels):
    # Totals sit at the bottom, and "Net 30" style text further up shouldn't win.
    for label in labels:
        pattern = re.compile(r"(?<![a-z])" + label, FLAGS)
        for line in reversed(lines):
            match = pattern.search(line)
            if match:
                amounts = MONEY.findall(line[match.end():])
                if amounts:
                    return Field(_money_value(amounts[-1]), "label")
    return None


def _value_after_label(lines, index, inline):
    if inline.strip():
        return inline
    return lines[index + 1] if index + 1 < len(lines) else ""


def _find_customer(lines):
    for index, line in enumerate(lines):
        match = CUSTOMER_LABEL.search(line)
        if match:
            value = _value_after_label(lines, index, match.group(1))
            if value:
                return Field(_tidy_name(value), "label")
    return None


def _find_vendor(lines):
    for index, line in enumerate(lines):
        match = VENDOR_LABEL.match(line)
        if match:
            value = _value_after_label(lines, index, match.group(1))
            if value:
                return Field(_tidy_name(value), "label")

    # No label, so look for a company name in the letterhead.
    header = []
    for line in lines[:6]:
        line = CUSTOMER_LABEL.sub("", line)
        line = DOCUMENT_TITLE.sub("", line)
        line = _tidy_name(line)
        if line and ":" not in line:
            header.append(line)

    nlp = _nlp()
    for line in header:
        if any(ent.label_ == "ORG" for ent in nlp(line).ents) and len(line.split()) <= 7:
            return Field(line, "ner")
    for line in header:
        if COMPANY_SUFFIX.search(line):
            return Field(line, "heuristic")
    return None


def _find_currency(lines):
    text = "\n".join(lines)
    match = ISO_CURRENCY.search(text)
    if match:
        return Field(match.group(1), "label")
    for symbol, code in SYMBOLS.items():
        if symbol in text:
            return Field(code, "label")
    return None


def extract_line_items(lines):
    items = []
    for line in lines:
        match = LINE_ITEM.match(line)
        if not match:
            continue
        description, qty, price, amount = match.groups()
        qty = Decimal(qty)
        price = Decimal(price.replace(",", ""))
        amount = Decimal(amount.replace(",", ""))
        # Arithmetic doubles as a check that this really is a table row.
        if abs(qty * price - amount) <= Decimal("0.05"):
            items.append(
                {
                    "description": description,
                    "quantity": str(qty),
                    "unit_price": str(price),
                    "amount": str(amount),
                }
            )
    return items


def extract_fields(lines):
    fields = {
        "invoice_number": _find_token(lines, INVOICE_NUMBER),
        "po_number": _find_token(lines, PO_NUMBER),
        "invoice_date": _find_labelled_date(lines, INVOICE_DATE),
        "due_date": _find_labelled_date(lines, DUE_DATE),
        "vendor": _find_vendor(lines),
        "customer": _find_customer(lines),
        "currency": _find_currency(lines),
        "subtotal": _find_amount(lines, SUBTOTAL_LABELS),
        "tax": _find_amount(lines, TAX_LABELS),
        "total": _find_amount(lines, TOTAL_LABELS),
    }

    # Invoices nearly always show the issue date first and the due date later.
    dates = _all_dates(lines)
    if not fields["invoice_date"] and dates:
        fields["invoice_date"] = Field(dates[0], "heuristic")
    if not fields["due_date"] and len(dates) > 1:
        issued = fields["invoice_date"].value
        later = sorted(d for d in dates if d > issued)
        if later:
            fields["due_date"] = Field(later[-1], "heuristic")

    if not fields["total"]:
        amounts = [Decimal(_money_value(a)) for line in lines for a in MONEY.findall(line)]
        if amounts:
            fields["total"] = Field(str(max(amounts)), "heuristic")

    return {name: asdict(field) if field else None for name, field in fields.items()}
