"""Field/file encryption (Fernet = AES-128-CBC + HMAC). Key comes from DATA_ENCRYPTION_KEY.
In development a key is derived from SECRET_KEY so the app runs; production refuses to start without an explicit key."""
import base64
import hashlib
import json
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    s = get_settings()
    if s.data_encryption_key:
        return Fernet(s.data_encryption_key.encode())
    if s.app_env == "production":
        raise RuntimeError("DATA_ENCRYPTION_KEY must be set in production (python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("dev-derived:" + s.secret_key).encode()).digest()))


def encrypt_bytes(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    try:
        return _fernet().decrypt(token)
    except InvalidToken:
        raise ValueError("Cannot decrypt (wrong key or corrupted data)")


def encrypt_json(obj: dict) -> str:
    return encrypt_bytes(json.dumps(obj).encode()).decode()


def decrypt_json(token: str) -> dict:
    return json.loads(decrypt_bytes(token.encode()))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
