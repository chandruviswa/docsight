"""Turns a PDF into lines of text, using OCR only for pages that need it."""

import io
from dataclasses import dataclass
from functools import lru_cache

import pdfplumber
import pypdfium2

MAX_PAGES = 20
# A page with less text than this is a scan, or a scan with a stray page number.
MIN_TEXT_CHARS = 25
OCR_SCALE = 2.0


class UnreadablePDF(Exception):
    pass


@dataclass
class ReadResult:
    lines: list[str]
    method: str  # "text", "ocr" or "mixed"
    page_count: int


@lru_cache(maxsize=1)
def _ocr_engine():
    # Takes about a second to load, so only do it when a scan actually shows up.
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def group_into_lines(boxes):
    """Rebuild reading order from OCR boxes, given as (x, y_center, height, text).

    OCR returns fragments in no useful order. Fragments belong to the same line
    when their vertical centres are close relative to the text height, which
    copes with the slight skew you get from a scanner.
    """
    lines = []
    for box in sorted(boxes, key=lambda b: b[1]):
        x, y, height, text = box
        if lines and abs(y - lines[-1]["y"]) < height * 0.6:
            lines[-1]["parts"].append((x, text))
        else:
            lines.append({"y": y, "parts": [(x, text)]})
    return [" ".join(text for _, text in sorted(line["parts"])) for line in lines]


def _ocr_page(pdf, index):
    image = pdf[index].render(scale=OCR_SCALE).to_numpy()
    results, _ = _ocr_engine()(image)
    boxes = []
    for corners, text, _score in results or []:
        ys = [point[1] for point in corners]
        boxes.append((corners[0][0], sum(ys) / 4, max(ys) - min(ys), text))
    return group_into_lines(boxes)


def read_pdf(data: bytes) -> ReadResult:
    if not data.startswith(b"%PDF"):
        raise UnreadablePDF("That file is not a PDF.")

    try:
        plumber = pdfplumber.open(io.BytesIO(data))
        rasteriser = pypdfium2.PdfDocument(data)
    except Exception as exc:
        raise UnreadablePDF("The PDF is damaged or password protected.") from exc

    with plumber:
        if len(plumber.pages) > MAX_PAGES:
            raise UnreadablePDF(f"PDFs are limited to {MAX_PAGES} pages.")

        lines, used = [], set()
        for index, page in enumerate(plumber.pages):
            text = (page.extract_text() or "").strip()
            if len(text) >= MIN_TEXT_CHARS:
                lines.extend(text.splitlines())
                used.add("text")
            else:
                lines.extend(_ocr_page(rasteriser, index))
                used.add("ocr")
        page_count = len(plumber.pages)

    rasteriser.close()
    method = used.pop() if len(used) == 1 else "mixed"
    return ReadResult([line.strip() for line in lines if line.strip()], method, page_count)
