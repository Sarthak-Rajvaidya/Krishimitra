"""Upload validation. Re-encodes the image so EXIF/metadata and polyglot payloads are dropped."""
import io

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings

ALLOWED = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
MAX_PIXELS = 25_000_000


def validate_and_clean(data: bytes) -> tuple[bytes, str]:
    s = get_settings()
    if not data:
        raise HTTPException(422, "Empty file")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Image larger than {s.max_upload_mb} MB")
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        if fmt not in ALLOWED:
            raise HTTPException(415, "Only JPEG, PNG or WEBP images are supported")
        if img.width * img.height > MAX_PIXELS:
            raise HTTPException(422, "Image dimensions too large")
        img.load()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
        raise HTTPException(422, "File is not a valid image")
    out = io.BytesIO()
    clean = img.convert("RGB")
    clean.save(out, "JPEG", quality=90)
    return out.getvalue(), "jpg"
