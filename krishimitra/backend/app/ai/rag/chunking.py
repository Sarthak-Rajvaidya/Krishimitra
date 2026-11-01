import re
from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    page: int | None
    section: str | None
    index: int


def normalize(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_pages(pages: list[tuple[int | None, str]], size: int = 900, overlap: int = 150) -> list[Chunk]:
    """Paragraph-aware chunking with overlap. Tracks page and nearest heading as section."""
    chunks: list[Chunk] = []
    idx = 0
    for page, raw in pages:
        text = normalize(raw)
        if not text:
            continue
        section = None
        buf_section = None
        buf = ""
        for para in re.split(r"\n\s*\n", text):
            para = para.strip()
            if not para:
                continue
            if len(para) < 80 and (para.isupper() or para.endswith(":") or re.match(r"^\d+(\.\d+)*\s+\S", para)):
                section = para.rstrip(":")[:150]
            if len(buf) + len(para) + 2 > size and buf:
                chunks.append(Chunk(buf.strip(), page, buf_section, idx)); idx += 1
                buf = buf[-overlap:] if overlap else ""
                buf_section = section
            while len(para) > size:       # hard-split very long paragraphs
                chunks.append(Chunk((buf + " " + para[:size]).strip(), page, buf_section or section, idx)); idx += 1
                para, buf = para[size - overlap:], ""
            if not buf:
                buf_section = section
            buf += ("\n\n" if buf else "") + para
        if buf.strip():
            chunks.append(Chunk(buf.strip(), page, buf_section or section, idx)); idx += 1
    return chunks
