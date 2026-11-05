import hashlib
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Document, get_session, init_db
from .evaluate import RESULTS_DIR
from .ingest import UnreadablePDF
from .pipeline import process_pdf

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(title="Docsight", lifespan=lifespan)


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


# Plain def, not async def: OCR takes seconds and would block the event loop.
@app.post("/api/documents", status_code=201)
def upload_document(file: UploadFile, session: Session = Depends(get_session)):
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Files are limited to 10 MB.")

    digest = hashlib.sha256(data).hexdigest()
    existing = session.scalar(select(Document).where(Document.sha256 == digest))
    if existing:
        return existing.as_dict()

    try:
        result = process_pdf(data)
    except UnreadablePDF as exc:
        raise HTTPException(422, str(exc)) from exc

    document = Document(
        filename=Path(file.filename or "upload.pdf").name[:255], sha256=digest, **result
    )
    session.add(document)
    session.commit()
    return document.as_dict()


@app.get("/api/documents")
def list_documents(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    query = select(Document).order_by(Document.id.desc()).limit(limit)
    if status:
        query = query.where(Document.status == status)
    return [document.as_dict() for document in session.scalars(query)]


@app.get("/api/documents/{document_id}")
def get_document(document_id: int, session: Session = Depends(get_session)):
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "No document with that id.")
    return document.as_dict()


def _run_files():
    return sorted(RESULTS_DIR.glob("*.json"), reverse=True) if RESULTS_DIR.exists() else []


@app.get("/api/evaluations")
def list_evaluations():
    runs = []
    for path in _run_files():
        report = json.loads(path.read_text())
        runs.append(
            {
                "name": path.stem,
                "created_at": report["created_at"],
                "note": report.get("note", ""),
                "slices": {
                    key: {"f1": s["overall"]["f1"], "documents": s["documents"]}
                    for key, s in report["slices"].items()
                },
            }
        )
    return runs


@app.get("/api/evaluations/{name}")
def get_evaluation(name: str):
    # The name ends up in a file path, so it only gets to be the timestamp format.
    if not re.fullmatch(r"\d{8}T\d{6}", name):
        raise HTTPException(404, "No such evaluation.")
    path = RESULTS_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(404, "No such evaluation.")
    return json.loads(path.read_text())
