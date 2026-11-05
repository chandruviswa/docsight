import pytest

from app.evaluate import FIELDS, Tally, outcome, prf, same_value


@pytest.mark.parametrize(
    "predicted,expected,result",
    [
        ("A", "A", (1, 0, 0)),
        ("A", "B", (0, 1, 1)),   # wrong answer hurts both
        (None, "B", (0, 0, 1)),  # blank only hurts recall
        ("A", None, (0, 1, 0)),  # made something up
        (None, None, (0, 0, 0)),
    ],
)
def test_outcome(predicted, expected, result):
    assert outcome("vendor", predicted, expected) == result


def test_prf_known_values():
    assert prf(8, 2, 2) == {"precision": 0.8, "recall": 0.8, "f1": 0.8, "support": 10}


def test_prf_handles_no_data():
    assert prf(0, 0, 0)["f1"] == 0.0


def test_amounts_compare_as_numbers():
    assert same_value("total", "100.5", "100.50")
    assert not same_value("total", "garbage", "100.50")


def test_names_ignore_spacing_and_case():
    assert same_value("vendor", "NORTHWIND  Traders", "Northwind Traders")
    assert not same_value("vendor", "Northwind", "Northwind Traders")


def test_tally_separates_caught_and_missed_errors():
    tally = Tally()
    right = dict.fromkeys(FIELDS, (1, 0, 0))
    wrong = {**right, "total": (0, 1, 1)}

    tally.add(right, flagged=False, seconds=1)
    tally.add(right, flagged=True, seconds=1)
    tally.add(wrong, flagged=True, seconds=1)
    tally.add(wrong, flagged=False, seconds=1)

    summary = tally.summary()
    assert summary["fully_correct"] == 2
    assert summary["errors_caught"] == 0.5
    assert summary["errors_missed"] == 1
    assert summary["false_alarms"] == 0.5
