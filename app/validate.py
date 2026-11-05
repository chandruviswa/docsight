"""Checks whether the extracted values make sense together.

An extractor can't know when it's wrong, but an invoice is full of redundancy that it
can be checked against. A misread total usually stops adding up.
"""

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation

REQUIRED = ["invoice_number", "invoice_date", "vendor", "total"]
EXPECTED = ["customer", "due_date", "subtotal", "tax"]
TOLERANCE = Decimal("0.02")
HIGHEST_NORMAL_TAX_RATE = Decimal("40")


@dataclass
class Issue:
    code: str
    severity: str  # "error" sends the document to review, "warning" doesn't
    message: str


def _value(fields, name):
    field = fields.get(name)
    return field["value"] if field else None


def _amount(fields, name):
    raw = _value(fields, name)
    if raw is None:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def validate(fields, line_items):
    issues = []

    for name in REQUIRED:
        if not fields.get(name):
            issues.append(Issue(f"missing_{name}", "error", f"Could not find {name}."))
    for name in EXPECTED:
        if not fields.get(name):
            issues.append(Issue(f"missing_{name}", "warning", f"Could not find {name}."))

    for name, field in fields.items():
        if field and field["source"] == "heuristic":
            issues.append(
                Issue(f"guessed_{name}", "error", f"{name} was guessed, not read from a label.")
            )

    subtotal, tax, total = (_amount(fields, n) for n in ("subtotal", "tax", "total"))

    if subtotal is not None and tax is not None and total is not None:
        if abs(subtotal + tax - total) > TOLERANCE:
            issues.append(
                Issue(
                    "total_mismatch",
                    "error",
                    f"Subtotal {subtotal} plus tax {tax} does not equal total {total}.",
                )
            )

    if line_items and subtotal is not None:
        line_sum = sum(Decimal(item["amount"]) for item in line_items)
        if abs(line_sum - subtotal) > TOLERANCE:
            issues.append(
                Issue(
                    "lines_mismatch",
                    "error",
                    f"Line items add up to {line_sum} but the subtotal is {subtotal}.",
                )
            )

    if subtotal and tax is not None and tax / subtotal * 100 > HIGHEST_NORMAL_TAX_RATE:
        issues.append(Issue("high_tax_rate", "warning", "Tax rate looks unusually high."))

    issued, due = _value(fields, "invoice_date"), _value(fields, "due_date")
    # ISO dates sort correctly as strings.
    if issued and due and due < issued:
        issues.append(Issue("due_before_issue", "error", "Due date is before the invoice date."))

    status = "needs_review" if any(i.severity == "error" for i in issues) else "ok"
    return status, [asdict(issue) for issue in issues]
