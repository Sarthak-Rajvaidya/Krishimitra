import io

from fastapi import HTTPException

SUPPORTED = {"pdf", "txt", "md"}


def extract_pages(data: bytes, file_type: str) -> list[tuple[int | None, str]]:
    ft = file_type.lower()
    if ft not in SUPPORTED:
        raise HTTPException(415, f"Unsupported document type '{ft}'. Use PDF, TXT or MD.")
    if ft in ("txt", "md"):
        return [(None, data.decode("utf-8", errors="replace"))]
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(i + 1, p.extract_text() or "") for i, p in enumerate(reader.pages)]
    except Exception:
        raise HTTPException(422, "Could not read this PDF")
    if not any(t.strip() for _, t in pages):
        raise HTTPException(422, "PDF has no extractable text (scanned documents need OCR first)")
    return pages
