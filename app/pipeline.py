from .extract import extract_fields, extract_line_items
from .ingest import read_pdf
from .validate import validate


def process_pdf(data: bytes) -> dict:
    read = read_pdf(data)
    fields = extract_fields(read.lines)
    line_items = extract_line_items(read.lines)
    status, issues = validate(fields, line_items)
    return {
        "method": read.method,
        "page_count": read.page_count,
        "fields": fields,
        "line_items": line_items,
        "status": status,
        "issues": issues,
    }
