"""Storage adapters. LocalStorage for dev; implement the same interface for S3/GCS/Azure later.
EncryptedStorage wraps any storage so identity/business documents are encrypted at rest."""
import re
import uuid
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings
from app.core.crypto import decrypt_bytes, encrypt_bytes

_KEY = re.compile(r"^[a-f0-9]{32}\.[a-z0-9]{2,5}$")


class Storage(Protocol):
    def save(self, data: bytes, ext: str) -> str: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    def __init__(self, base: str):
        self.base = Path(base).resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, ext: str) -> str:
        key = f"{uuid.uuid4().hex}.{ext.lower().lstrip('.')}"
        (self.base / key).write_bytes(data)
        return key

    def read(self, key: str) -> bytes:
        if not _KEY.match(key):          # blocks path traversal
            raise FileNotFoundError(key)
        p = (self.base / key).resolve()
        if self.base not in p.parents:
            raise FileNotFoundError(key)
        return p.read_bytes()

    def delete(self, key: str) -> None:
        if _KEY.match(key):
            (self.base / key).unlink(missing_ok=True)


class EncryptedStorage:
    def __init__(self, inner: Storage):
        self.inner = inner

    def save(self, data: bytes, ext: str) -> str:
        return self.inner.save(encrypt_bytes(data), ext)

    def read(self, key: str) -> bytes:
        return decrypt_bytes(self.inner.read(key))

    def delete(self, key: str) -> None:
        self.inner.delete(key)  # type: ignore[attr-defined]


def image_storage() -> LocalStorage:
    return LocalStorage(get_settings().upload_dir)


def knowledge_storage() -> LocalStorage:
    return LocalStorage(get_settings().knowledge_dir)


def document_storage() -> EncryptedStorage:
    return EncryptedStorage(LocalStorage(get_settings().upload_dir + "/private"))


def media_storage() -> LocalStorage:
    return LocalStorage(get_settings().upload_dir + "/media")
