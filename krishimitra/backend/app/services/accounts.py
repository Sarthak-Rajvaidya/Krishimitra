"""Account lifecycle: contact normalisation, OTPs, status changes, sessions, registration."""
import re
import secrets
from datetime import timedelta

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import encrypt_json
from app.core.security import create_access_token, hash_password, hmac_code, new_sid
from app.db.base import as_utc, utcnow
from app.models import (DeliveryProfile, District, ExpertProfile, FarmerProfile, Otp, Role, RoleName, SoilCenter,
                        SupplierProfile, User, UserSession, UserStatus)
from app.permissions.rbac import NEEDS_APPROVAL

_MOBILE = re.compile(r"^[6-9]\d{9}$")


def norm_mobile(raw: str | None) -> str | None:
    if not raw:
        return None
    d = re.sub(r"\D", "", raw)
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    if len(d) == 11 and d.startswith("0"):
        d = d[1:]
    if not _MOBILE.match(d):
        raise HTTPException(422, "Enter a valid 10-digit Indian mobile number")
    return d


def norm_identifier(raw: str) -> tuple[str, str]:
    """Returns (kind, value) where kind is 'email' or 'mobile'."""
    raw = raw.strip()
    if "@" in raw:
        return "email", raw.lower()
    return "mobile", norm_mobile(raw)  # type: ignore[return-value]


def find_user(db: Session, raw: str) -> User | None:
    try:
        kind, val = norm_identifier(raw)
    except HTTPException:
        return None
    col = User.email if kind == "email" else User.phone
    return db.scalar(select(User).where(col == val))


def set_status(user: User, status: UserStatus, note: str | None = None) -> None:
    user.status = status
    user.is_active = status in (UserStatus.ACTIVE, UserStatus.PENDING_APPROVAL)
    if note is not None:
        user.status_note = note[:300]


def resolve_district(db: Session, name: str | None, state: str | None = None) -> int | None:
    if not name:
        return None
    q = select(District.id).where(func.lower(District.name) == name.strip().lower())
    if state:
        q = q.where(func.lower(District.state) == state.strip().lower())
    return db.scalar(q.limit(1))


# ---------------- OTP ----------------
def issue_otp(db: Session, target: str, purpose: str) -> str:
    s = get_settings()
    now = utcnow()
    last = db.scalar(select(Otp).where(Otp.target == target).order_by(Otp.id.desc()).limit(1))
    if last and (now - as_utc(last.created_at)).total_seconds() < 60 and s.rate_limit_multiplier == 1:
        raise HTTPException(429, "Please wait a minute before requesting another code")
    hour = db.scalar(select(func.count(Otp.id)).where(Otp.target == target, Otp.created_at >= now - timedelta(hours=1)))
    if hour >= 5 * s.rate_limit_multiplier:
        raise HTTPException(429, "Too many codes requested. Try again later")
    code = f"{secrets.randbelow(10 ** 6):06d}"
    db.add(Otp(target=target, purpose=purpose, code_hash=hmac_code(target, purpose, code), created_at=now,
               expires_at=now + timedelta(minutes=s.otp_ttl_minutes)))
    db.flush()
    return code


def check_otp(db: Session, target: str, purpose: str, code: str) -> bool:
    s = get_settings()
    otp = db.scalar(select(Otp).where(Otp.target == target, Otp.purpose == purpose, Otp.used == False)  # noqa: E712
                    .order_by(Otp.id.desc()).limit(1))
    if not otp or as_utc(otp.expires_at) < utcnow() or otp.attempts >= s.otp_max_attempts:
        return False
    otp.attempts += 1
    ok = secrets.compare_digest(otp.code_hash, hmac_code(target, purpose, code.strip()))
    if ok:
        otp.used = True
    db.commit()
    return ok


# ---------------- sessions ----------------
def start_session(db: Session, user: User, request: Request) -> str:
    s = get_settings()
    sid = new_sid()
    now = utcnow()
    db.add(UserSession(id=sid, user_id=user.id, user_agent=(request.headers.get("user-agent") or "")[:200],
                       ip=(request.client.host if request.client else None), created_at=now, expires_at=now + timedelta(days=s.session_days)))
    user.last_login_at = now
    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    return create_access_token(user.id, sid)


def revoke_sessions(db: Session, user_id: int, except_sid: str | None = None) -> None:
    for s in db.scalars(select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked == False)):  # noqa: E712
        if s.id != except_sid:
            s.revoked = True


# ---------------- registration ----------------
def create_account(db: Session, *, role: RoleName, full_name: str, password: str, email: str | None, mobile: str | None,
                   language: str = "en", profile: dict | None = None, status: UserStatus | None = None, is_demo: bool = False) -> User:
    mobile, email = norm_mobile(mobile), (email.lower().strip() if email else None)
    if not mobile and not email:
        raise HTTPException(422, "Provide a mobile number or an email")
    if email and db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "This email is already registered")
    if mobile and db.scalar(select(User.id).where(User.phone == mobile)):
        raise HTTPException(409, "This mobile number is already registered")
    r = db.scalar(select(Role).where(Role.name == role))
    p = profile or {}
    u = User(email=email, phone=mobile, full_name=full_name.strip(), password_hash=hash_password(password), role_id=r.id,
             language=language, is_demo=is_demo, district_id=resolve_district(db, p.get("district"), p.get("state")),
             notif_prefs={"in_app": True, "sms": True, "email": bool(email), "push": False, "muted_kinds": []},
             privacy={"community_profile_public": True, "share_with_experts": True})
    set_status(u, status or UserStatus.PENDING_VERIFICATION)
    db.add(u)
    db.flush()
    _create_profile(db, u, role, p)
    return u


def _create_profile(db: Session, u: User, role: RoleName, p: dict) -> None:
    pick = lambda *keys: {k: p[k] for k in keys if k in p and p[k] not in ("", None)}  # noqa: E731
    if role == RoleName.FARMER:
        db.add(FarmerProfile(user_id=u.id, **pick("village", "district", "state", "primary_crops", "farm_size_acres", "land_ownership",
                                                  "experience_years", "latitude", "longitude")))
    elif role == RoleName.EXPERT:
        db.add(ExpertProfile(user_id=u.id, **pick("qualification", "specialization", "experience_years", "certifications", "district",
                                                  "state", "fee_paise", "bio", "availability", "languages", "modes")))
    elif role == RoleName.SUPPLIER:
        bank = p.get("bank")
        db.add(SupplierProfile(user_id=u.id, shop_name=p.get("shop_name") or u.full_name,
                               bank_enc=encrypt_json(bank) if bank else None,
                               **pick("owner_name", "address", "village", "district", "state", "pincode", "latitude", "longitude",
                                      "business_reg_no", "gst_no", "product_categories", "operating_hours", "service_districts")))
    elif role == RoleName.DELIVERY:
        db.add(DeliveryProfile(user_id=u.id, **pick("address", "vehicle_type", "vehicle_number", "licence_number", "service_pincodes")))
    elif role == RoleName.SOIL_CENTER:
        db.add(SoilCenter(user_id=u.id, name=p.get("name") or u.full_name,
                          **pick("address", "district", "state", "pincode", "latitude", "longitude", "phone", "test_fee_paise")))


def activate_after_verification(user: User, role: RoleName) -> UserStatus:
    new = UserStatus.PENDING_APPROVAL if role.value in NEEDS_APPROVAL else UserStatus.ACTIVE
    set_status(user, new)
    return new
