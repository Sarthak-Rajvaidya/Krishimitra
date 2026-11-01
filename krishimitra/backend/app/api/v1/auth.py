import logging
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, user_permissions
from app.core.audit import audit
from app.core.config import get_settings
from app.core.ratelimit import rate_limit  # noqa: F401  (re-exported for other routers)
from app.core.security import password_ok, verify_password, hash_password
from app.db.base import as_utc, utcnow
from app.db.session import get_db
from app.models import RoleName, User, UserSession, UserStatus
from app.permissions.rbac import NEEDS_APPROVAL, PORTAL_PATH, SELF_REGISTER_ROLES
from app.services import accounts as acc
from app.services.notify import deliver_now, notify_role

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("auth")
PW_HELP = "Password must be 8-72 characters and contain a letter and a digit"


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "mobile": u.phone, "full_name": u.full_name, "role": u.role.name.value,
            "status": u.status.value, "permissions": sorted(user_permissions(u)), "language": u.language, "district_id": u.district_id,
            "mobile_verified": u.mobile_verified, "email_verified": u.email_verified, "is_demo": u.is_demo,
            "portal": PORTAL_PATH.get(u.role.name.value, "/"), "has_photo": bool(u.photo_key)}


def _set_cookie(resp: Response, token: str) -> None:
    s = get_settings()
    resp.set_cookie("ks_token", token, httponly=True, samesite="lax", secure=s.cookie_secure, max_age=s.session_days * 86400, path="/")


def _send_code(bg: BackgroundTasks, target: str, kind: str, code: str, purpose: str) -> None:
    text = f"Your KrishiMitra code is {code}. Valid for {get_settings().otp_ttl_minutes} minutes. Do not share it."
    bg.add_task(deliver_now, "EMAIL" if kind == "email" else "SMS", target, "Your KrishiMitra verification code", text)


def _echo(code: str) -> dict:
    s = get_settings()
    return {"dev_code": code} if (s.otp_dev_echo and s.app_env != "production") else {}


# ---------------- registration ----------------
class RegisterIn(BaseModel):
    role: Literal["FARMER", "EXPERT", "SUPPLIER", "DELIVERY", "SOIL_CENTER"] = "FARMER"
    full_name: str = Field(min_length=2, max_length=160)
    mobile: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    password: str = Field(min_length=8, max_length=72)
    language: Literal["en", "hi", "mr"] = "en"
    profile: dict = Field(default_factory=dict)       # role specific details (see README "Registration fields")


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, bg: BackgroundTasks, db: Session = Depends(get_db)):
    rate_limit(f"reg:{request.client.host if request.client else 'x'}", 10)
    if body.role not in SELF_REGISTER_ROLES:
        raise HTTPException(403, "This role cannot self-register")
    if not password_ok(body.password):
        raise HTTPException(422, PW_HELP)
    if body.role == "FARMER" and not body.mobile:
        raise HTTPException(422, "Farmers register with a mobile number")
    role = RoleName(body.role)
    if role == RoleName.SUPPLIER and not body.profile.get("shop_name"):
        raise HTTPException(422, "Shop / business name is required")
    if role == RoleName.EXPERT and not (body.profile.get("qualification") and body.profile.get("specialization")):
        raise HTTPException(422, "Qualification and specialization are required")
    if role == RoleName.DELIVERY and not (body.profile.get("vehicle_type") and body.profile.get("licence_number")):
        raise HTTPException(422, "Vehicle type and driving licence number are required")
    u = acc.create_account(db, role=role, full_name=body.full_name, password=body.password, email=body.email, mobile=body.mobile,
                           language=body.language, profile=body.profile)
    kind, target = ("mobile", u.phone) if u.phone else ("email", u.email)
    code = acc.issue_otp(db, target, "VERIFY")
    db.commit()
    _send_code(bg, target, kind, code, "VERIFY")
    return {"user_id": u.id, "status": u.status.value, "verify_via": kind, "next": "Enter the code we sent to verify your contact", **_echo(code)}


class VerifyIn(BaseModel):
    identifier: str
    code: str = Field(min_length=4, max_length=8)


@router.post("/verify")
def verify(body: VerifyIn, request: Request, response: Response, db: Session = Depends(get_db)):
    rate_limit(f"verify:{request.client.host if request.client else 'x'}", 20)
    u = acc.find_user(db, body.identifier)
    kind, target = acc.norm_identifier(body.identifier)
    if not u or u.status != UserStatus.PENDING_VERIFICATION or not acc.check_otp(db, target, "VERIFY", body.code):
        raise HTTPException(400, "Invalid or expired code")
    if kind == "mobile":
        u.mobile_verified = True
    else:
        u.email_verified = True
    new = acc.activate_after_verification(u, u.role.name)
    audit(db, u.id, "account.verified", "user", u.id, {"status": new.value})
    if new == UserStatus.PENDING_APPROVAL:
        notify_role(db, RoleName.ADMIN, "ACCOUNT", f"New {u.role.name.value.replace('_', ' ').title()} awaiting approval", u.full_name, district_id=None)
    db.commit()
    token = acc.start_session(db, u, request)
    _set_cookie(response, token)
    return {"user": user_out(u), "token": token}


class OtpRequestIn(BaseModel):
    identifier: str
    purpose: Literal["VERIFY", "LOGIN"] = "LOGIN"


@router.post("/otp/request")
def otp_request(body: OtpRequestIn, request: Request, bg: BackgroundTasks, db: Session = Depends(get_db)):
    rate_limit(f"otp:{request.client.host if request.client else 'x'}", 10)
    u = acc.find_user(db, body.identifier)
    kind, target = acc.norm_identifier(body.identifier)
    extra = {}
    # identical response whether or not the account exists (no user enumeration)
    if u and (u.status == UserStatus.PENDING_VERIFICATION if body.purpose == "VERIFY" else u.status in (UserStatus.ACTIVE, UserStatus.PENDING_APPROVAL)):
        code = acc.issue_otp(db, target, body.purpose)
        db.commit()
        _send_code(bg, target, kind, code, body.purpose)
        extra = _echo(code)
    return {"sent": True, **extra}


# ---------------- login / logout ----------------
class LoginIn(BaseModel):
    identifier: str = Field(max_length=255)     # email or mobile
    password: str = Field(max_length=72)


def _check_lock(u: User) -> None:
    if u.locked_until and as_utc(u.locked_until) > utcnow():
        raise HTTPException(423, "Account temporarily locked after too many failed attempts. Try again later or reset your password")


def _login_ok(db: Session, u: User, request: Request, response: Response) -> dict:
    if u.status == UserStatus.PENDING_VERIFICATION:
        raise HTTPException(403, "Please verify your mobile number or email first")
    if u.status not in (UserStatus.ACTIVE, UserStatus.PENDING_APPROVAL):
        raise HTTPException(403, f"Account is {u.status.value.lower()}. Contact support")
    token = acc.start_session(db, u, request)
    _set_cookie(response, token)
    return {"user": user_out(u), "token": token}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "x"
    rate_limit(f"login:{ip}", 20)
    u = acc.find_user(db, body.identifier)
    if u:
        _check_lock(u)
    if not u or not verify_password(body.password, u.password_hash):
        if u:
            u.failed_logins += 1
            if u.failed_logins >= get_settings().max_failed_logins:
                u.locked_until = utcnow() + timedelta(minutes=get_settings().lockout_minutes)
                audit(db, u.id, "account.locked", "user", u.id)
            db.commit()
        raise HTTPException(401, "Invalid credentials")
    return _login_ok(db, u, request, response)


class OtpLoginIn(BaseModel):
    identifier: str
    code: str = Field(min_length=4, max_length=8)


@router.post("/login/otp")
def login_otp(body: OtpLoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    rate_limit(f"loginotp:{request.client.host if request.client else 'x'}", 20)
    u = acc.find_user(db, body.identifier)
    _, target = acc.norm_identifier(body.identifier)
    if u:
        _check_lock(u)
    if not u or not acc.check_otp(db, target, "LOGIN", body.code):
        raise HTTPException(401, "Invalid or expired code")
    return _login_ok(db, u, request, response)


@router.post("/logout")
def logout(request: Request, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sess = db.get(UserSession, request.state.session_id)
    if sess:
        sess.revoked = True
        db.commit()
    response.delete_cookie("ks_token", path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


# ---------------- passwords ----------------
class ForgotIn(BaseModel):
    identifier: str


@router.post("/password/forgot")
def forgot(body: ForgotIn, request: Request, bg: BackgroundTasks, db: Session = Depends(get_db)):
    rate_limit(f"forgot:{request.client.host if request.client else 'x'}", 5)
    u = acc.find_user(db, body.identifier)
    extra = {}
    if u and u.status in (UserStatus.ACTIVE, UserStatus.PENDING_APPROVAL):
        kind, target = acc.norm_identifier(body.identifier)
        code = acc.issue_otp(db, target, "RESET")
        db.commit()
        _send_code(bg, target, kind, code, "RESET")
        extra = _echo(code)
    return {"sent": True, "message": "If the account exists, a reset code has been sent", **extra}


class ResetIn(BaseModel):
    identifier: str
    code: str = Field(min_length=4, max_length=8)
    new_password: str = Field(min_length=8, max_length=72)


@router.post("/password/reset")
def reset(body: ResetIn, request: Request, db: Session = Depends(get_db)):
    rate_limit(f"reset:{request.client.host if request.client else 'x'}", 10)
    if not password_ok(body.new_password):
        raise HTTPException(422, PW_HELP)
    u = acc.find_user(db, body.identifier)
    _, target = acc.norm_identifier(body.identifier)
    if not u or not acc.check_otp(db, target, "RESET", body.code):
        raise HTTPException(400, "Invalid or expired code")
    u.password_hash = hash_password(body.new_password)
    u.failed_logins, u.locked_until = 0, None
    acc.revoke_sessions(db, u.id)
    audit(db, u.id, "password.reset", "user", u.id)
    db.commit()
    return {"ok": True}


class ChangeIn(BaseModel):
    old_password: str = Field(max_length=72)
    new_password: str = Field(min_length=8, max_length=72)


@router.post("/password/change")
def change(body: ChangeIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    if not password_ok(body.new_password):
        raise HTTPException(422, PW_HELP)
    user.password_hash = hash_password(body.new_password)
    acc.revoke_sessions(db, user.id, except_sid=request.state.session_id)
    audit(db, user.id, "password.change", "user", user.id)
    db.commit()
    return {"ok": True}


# ---------------- sessions ----------------
@router.get("/sessions")
def sessions(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked == False,  # noqa: E712
                                                UserSession.expires_at > utcnow()).order_by(UserSession.created_at.desc()))
    return [{"id": s.id, "current": s.id == request.state.session_id, "device": s.user_agent, "ip": s.ip,
             "created_at": s.created_at.isoformat()} for s in rows]


@router.delete("/sessions/{sid}")
def revoke(sid: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.get(UserSession, sid)
    if not s or s.user_id != user.id:
        raise HTTPException(404, "Session not found")
    s.revoked = True
    db.commit()
    return {"ok": True}
