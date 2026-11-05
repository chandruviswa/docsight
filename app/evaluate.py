"""Scores the pipeline against labelled documents and saves the result.

    python -m app.evaluate --data samples/data

A wrong value counts against both precision and recall: it's a false positive (we
claimed something untrue) and a false negative (the real value wasn't found). A
blank is only a false negative. So a system that leaves things blank when unsure
scores higher precision than one that guesses, which is what you want from this.
"""

import argparse
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .pipeline import process_pdf

FIELDS = [
    "invoice_number", "invoice_date", "due_date", "po_number", "vendor",
    "customer", "currency", "subtotal", "tax", "total",
]
RESULTS_DIR = Path(__file__).resolve().parent.parent / "eval_results"
HELD_OUT_TEMPLATES = {"D"}


def same_value(field, predicted, expected):
    if field in ("subtotal", "tax", "total"):
        try:
            return Decimal(predicted) == Decimal(expected)
        except InvalidOperation:
            return False
    # OCR spacing and capitals aren't worth failing a name over.
    squash = lambda text: re.sub(r"\s+", "", text).casefold()  # noqa: E731
    return squash(predicted) == squash(expected)


def outcome(field, predicted, expected):
    """Returns (tp, fp, fn) for a single field on a single document."""
    if predicted is None and expected is None:
        return 0, 0, 0
    if predicted is None:
        return 0, 0, 1
    if expected is None:
        return 0, 1, 0
    if same_value(field, predicted, expected):
        return 1, 0, 0
    return 0, 1, 1


def prf(tp, fp, fn):
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "support": tp + fn,
    }


class Tally:
    """Counts for one slice of the data, such as "scanned, held-out template"."""

    def __init__(self):
        self.counts = defaultdict(lambda: [0, 0, 0])
        self.documents = 0
        self.fully_correct = 0
        self.wrong_and_flagged = 0
        self.wrong_and_passed = 0
        self.right_and_flagged = 0
        self.right_and_passed = 0
        self.seconds = 0.0

    def add(self, per_field, flagged, seconds):
        self.documents += 1
        self.seconds += seconds
        any_wrong = False
        for field, (tp, fp, fn) in per_field.items():
            counts = self.counts[field]
            counts[0] += tp
            counts[1] += fp
            counts[2] += fn
            any_wrong = any_wrong or fp > 0 or fn > 0
        self.fully_correct += not any_wrong
        if any_wrong:
            self.wrong_and_flagged += flagged
            self.wrong_and_passed += not flagged
        else:
            self.right_and_flagged += flagged
            self.right_and_passed += not flagged

    def summary(self):
        totals = [sum(self.counts[f][i] for f in FIELDS) for i in range(3)]
        wrong = self.wrong_and_flagged + self.wrong_and_passed
        right = self.right_and_flagged + self.right_and_passed
        return {
            "documents": self.documents,
            "fully_correct": self.fully_correct,
            "overall": prf(*totals),
            "fields": {f: prf(*self.counts[f]) for f in FIELDS},
            # Of the documents with a mistake, how many did validation send to review?
            "errors_caught": round(self.wrong_and_flagged / wrong, 4) if wrong else None,
            "documents_with_errors": wrong,
            "errors_missed": self.wrong_and_passed,
            # Of the perfect documents, how many were sent to review for nothing?
            "false_alarms": round(self.right_and_flagged / right, 4) if right else None,
            "avg_seconds": round(self.seconds / self.documents, 3) if self.documents else None,
        }


def evaluate(data_dir):
    tallies = defaultdict(Tally)
    mistakes = []

    for pdf_path in sorted(Path(data_dir).glob("*.pdf")):
        label = json.loads(pdf_path.with_suffix(".json").read_text())

        started = time.perf_counter()
        result = process_pdf(pdf_path.read_bytes())
        elapsed = time.perf_counter() - started

        per_field = {}
        for field in FIELDS:
            found = result["fields"].get(field)
            predicted = found["value"] if found else None
            expected = label["fields"].get(field)
            per_field[field] = outcome(field, predicted, expected)
            if per_field[field][1] or per_field[field][2]:
                mistakes.append(
                    {
                        "document": pdf_path.name,
                        "field": field,
                        "expected": expected,
                        "got": predicted,
                        "caught": result["status"] == "needs_review",
                    }
                )

        split = "held_out" if label["template"] in HELD_OUT_TEMPLATES else "seen"
        flagged = result["status"] == "needs_review"
        for key in ("all", f"{split}/{label['kind']}"):
            tallies[key].add(per_field, flagged, elapsed)

    return {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "slices": {key: tally.summary() for key, tally in sorted(tallies.items())},
        "mistakes": mistakes[:200],
        "mistake_count": len(mistakes),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="samples/data")
    parser.add_argument("--note", default="", help="What changed since the last run")
    args = parser.parse_args()

    report = evaluate(args.data)
    report["note"] = args.note

    RESULTS_DIR.mkdir(exist_ok=True)
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + ".json"
    (RESULTS_DIR / name).write_text(json.dumps(report, indent=1))

    for key, summary in report["slices"].items():
        overall = summary["overall"]
        print(
            f"{key:20} docs={summary['documents']:4} f1={overall['f1']:.3f} "
            f"precision={overall['precision']:.3f} recall={overall['recall']:.3f} "
            f"perfect={summary['fully_correct']:3} caught={summary['errors_caught']} "
            f"false_alarms={summary['false_alarms']} sec={summary['avg_seconds']}"
        )
    print(f"Saved {name}")


if __name__ == "__main__":
    main()
