from app.validate import validate


def field(value, source="label"):
    return {"value": value, "source": source}


def good_fields(**overrides):
    fields = {
        "invoice_number": field("INV-1"),
        "invoice_date": field("2026-03-01"),
        "due_date": field("2026-03-31"),
        "vendor": field("Acme Ltd"),
        "customer": field("Initech"),
        "subtotal": field("100.00"),
        "tax": field("18.00"),
        "total": field("118.00"),
    }
    fields.update(overrides)
    return fields


def codes(issues):
    return {issue["code"] for issue in issues}


def test_consistent_invoice_passes():
    status, issues = validate(good_fields(), [{"amount": "100.00"}])
    assert status == "ok"
    assert issues == []


def test_total_that_does_not_add_up_goes_to_review():
    status, issues = validate(good_fields(total=field("181.00")), [])
    assert status == "needs_review"
    assert "total_mismatch" in codes(issues)


def test_rounding_difference_of_a_cent_is_allowed():
    status, _ = validate(good_fields(total=field("118.01")), [])
    assert status == "ok"


def test_line_items_must_match_subtotal():
    _, issues = validate(good_fields(), [{"amount": "60.00"}])
    assert "lines_mismatch" in codes(issues)


def test_missing_required_field_goes_to_review():
    status, issues = validate(good_fields(invoice_number=None), [])
    assert status == "needs_review"
    assert "missing_invoice_number" in codes(issues)


def test_missing_optional_field_is_only_a_warning():
    status, issues = validate(good_fields(customer=None), [])
    assert status == "ok"
    assert "missing_customer" in codes(issues)


def test_due_before_issue_goes_to_review():
    status, issues = validate(good_fields(due_date=field("2026-01-01")), [])
    assert status == "needs_review"
    assert "due_before_issue" in codes(issues)


def test_guessed_field_goes_to_review():
    status, issues = validate(good_fields(total=field("118.00", "heuristic")), [])
    assert status == "needs_review"
    assert "guessed_total" in codes(issues)


def test_high_tax_rate_warns():
    fields = good_fields(tax=field("60.00"), total=field("160.00"))
    assert "high_tax_rate" in codes(validate(fields, [])[1])


def test_zero_tax_is_fine():
    status, _ = validate(good_fields(tax=field("0.00"), total=field("100.00")), [])
    assert status == "ok"
