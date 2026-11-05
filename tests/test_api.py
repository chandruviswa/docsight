import os
import random
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///./test_docsight.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import MAX_UPLOAD_BYTES, app  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "samples"))
from generate import make_invoice, to_pdf  # noqa: E402


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def invoice():
    inv = make_invoice(random.Random(7))
    return inv, to_pdf(inv, "A")


def upload(client, data, name="invoice.pdf"):
    return client.post("/api/documents", files={"file": (name, data, "application/pdf")})


def test_upload_extracts_and_stores(client, invoice):
    inv, pdf = invoice
    response = upload(client, pdf)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ok"
    assert body["method"] == "text"
    assert body["fields"]["invoice_number"]["value"] == inv["invoice_number"]
    assert len(body["line_items"]) == len(inv["lines"])

    assert client.get(f"/api/documents/{body['id']}").json() == body


def test_same_file_twice_returns_the_same_record(client, invoice):
    _, pdf = invoice
    first = upload(client, pdf).json()
    second = upload(client, pdf).json()
    assert first["id"] == second["id"]
    assert len(client.get("/api/documents").json()) == 1


def test_not_a_pdf_is_422(client):
    assert upload(client, b"hello").status_code == 422


def test_too_large_is_413(client):
    assert upload(client, b"%PDF" + b"0" * MAX_UPLOAD_BYTES).status_code == 413


def test_path_in_filename_is_stripped(client, invoice):
    _, pdf = invoice
    body = upload(client, pdf, name="../../etc/invoice.pdf").json()
    assert body["filename"] == "invoice.pdf"


def test_missing_document_is_404(client):
    assert client.get("/api/documents/999").status_code == 404


def test_filter_by_status(client, invoice):
    _, pdf = invoice
    upload(client, pdf)
    assert client.get("/api/documents", params={"status": "needs_review"}).json() == []
    assert len(client.get("/api/documents", params={"status": "ok"}).json()) == 1


def test_evaluation_name_cannot_escape_the_folder(client):
    assert client.get("/api/evaluations/..%2F..%2Fsecrets").status_code == 404
    assert client.get("/api/evaluations/not-a-run").status_code == 404


def test_dashboard_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Docsight" in response.text
