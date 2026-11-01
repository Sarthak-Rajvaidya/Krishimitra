import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings

ALGO = "HS256"
_PW = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,72}$")


def password_ok(pw: str) -> bool:
    return bool(_PW.match(pw))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_access_token(user_id: int, sid: str, days: int | None = None) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(days=days or s.session_days)
    return jwt.encode({"sub": str(user_id), "sid": sid, "exp": exp}, s.secret_key, algorithm=ALGO)


def decode_token(token: str) -> tuple[int, str] | None:
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=[ALGO])
        return int(data["sub"]), str(data["sid"])
    except Exception:
        return None


def new_sid() -> str:
    return secrets.token_hex(16)


def hmac_code(target: str, purpose: str, code: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), f"{target}:{purpose}:{code}".encode(), hashlib.sha256).hexdigest()
