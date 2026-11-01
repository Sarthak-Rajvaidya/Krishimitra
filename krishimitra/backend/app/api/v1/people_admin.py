"""Admin: user management, approvals, document verification, deletion requests. District managers see only their district."""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field as F
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import district_scope, is_global_staff, require, require_any
from app.api.v1.common import page_args
from app.core.audit import audit
from app.core.security import hash_password, password_ok
from app.core.storage import document_storage
from app.db.session import get_db
from app.models import DeletionRequest, DocStatusV, Role, RoleName, User, UserDocument, UserStatus
from app.services import accounts as acc
from app.services.notify import notify

router = APIRouter(prefix="/admin", tags=["admin-users"])
Staff = Depends(require_any("users.manage", "district.manage"))
Mgr = Depends(require("users.manage"))
STAFF_ROLES = {RoleName.ADMIN, RoleName.SUPER_ADMIN, RoleName.DISTRICT_MANAGER, RoleName.FINANCE, RoleName.DEVELOPER, RoleName.FOUNDER}


def u_out(u: User) -> dict:
    return {"id": u.id, "name": u.full_name, "mobile": u.phone, "email": u.email, "role": u.role.name.value, "status": u.status.value, "district_id": u.district_id,
            "mobile_verified": u.mobile_verified, "email_verified": u.email_verified, "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "created_at": u.created_at.isoformat(), "is_demo": u.is_demo, "note": u.status_note}


def _target(db: Session, actor: User, uid: int) -> User:
    t = db.get(User, uid)
    sc = district_scope(actor)
    if not t or (sc and t.district_id != sc):
        raise HTTPException(404, "User not found")
    return t


@router.get("/users")
def list_users(role: RoleName | None = None, status: UserStatus | None = None, q: str | None = None, district_id: int | None = None,
               page: int = 1, size: int = 50, user: User = Staff, db: Session = Depends(get_db)):
    stmt = select(User).order_by(User.id.desc())
    sc = district_scope(user)
    if sc:
        stmt = stmt.where(User.district_id == sc)
    elif district_id:
        stmt = stmt.where(User.district_id == district_id)
    if role:
        stmt = stmt.join(Role, Role.id == User.role_id).where(Role.name == role)
    if status:
        stmt = stmt.where(User.status == status)
    if q:
        stmt = stmt.where(func.lower(User.full_name).like(f"%{q.lower()}%") | User.phone.like(f"%{q}%") | func.lower(User.email).like(f"%{q.lower()}%"))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    off, size = page_args(page, size)
    return {"total": total, "items": [u_out(u) for u in db.scalars(stmt.offset(off).limit(size)).unique()]}


@router.get("/approvals")
def approvals(user: User = Staff, db: Session = Depends(get_db)):
    """Registrations waiting for a decision, with their documents."""
    stmt = select(User).where(User.status == UserStatus.PENDING_APPROVAL).order_by(User.id).limit(100)
    sc = district_scope(user)
    if sc:
        stmt = stmt.where(User.district_id == sc)
    out = []
    for u in db.scalars(stmt).unique():
        docs = db.scalars(select(UserDocument).where(UserDocument.user_id == u.id)).all()
        out.append({**u_out(u), "documents": [{"id": d.id, "type": d.doc_type, "name": d.original_name, "status": d.status.value} for d in docs]})
    return out


class Decision(BaseModel):
    note: str | None = F(default=None, max_length=300)


def _set(db: Session, actor: User, uid: int, status: UserStatus, note: str | None, allowed: set[UserStatus], action: str) -> dict:
    t = _target(db, actor, uid)
    if t.role.name in STAFF_ROLES and not is_global_staff(actor):
        raise HTTPException(403, "Forbidden")
    if t.role.name == RoleName.SUPER_ADMIN and actor.role.name != RoleName.SUPER_ADMIN:
        raise HTTPException(403, "Only a super admin can change a super admin")
    if t.id == actor.id:
        raise HTTPException(409, "You cannot change your own account status")
    if t.status not in allowed:
        raise HTTPException(409, f"Account is {t.status.value}; cannot {action}")
    acc.set_status(t, status, note)
    if status != UserStatus.ACTIVE:
        acc.revoke_sessions(db, t.id)
    notify(db, t.id, "ACCOUNT", f"Your account was {status.value.lower().replace('_', ' ')}", note or "")
    audit(db, actor.id, f"user.{action}", "user", t.id, {"note": note})
    db.commit()
    return u_out(t)


@router.post("/users/{uid}/approve")
def approve(uid: int, body: Decision, user: User = Depends(require_any("approvals.manage", "district.manage")), db: Session = Depends(get_db)):
    t = _target(db, user, uid)
    if t.role.name in (RoleName.SUPPLIER, RoleName.DELIVERY, RoleName.SOIL_CENTER, RoleName.EXPERT):
        pending = db.scalar(select(func.count(UserDocument.id)).where(UserDocument.user_id == uid, UserDocument.status == DocStatusV.REJECTED))
        if pending:
            raise HTTPException(409, "A rejected document is on file; ask the user to upload a corrected one")
        if not db.scalar(select(UserDocument.id).where(UserDocument.user_id == uid).limit(1)):
            raise HTTPException(409, "No verification documents uploaded yet")
    return _set(db, user, uid, UserStatus.ACTIVE, body.note, {UserStatus.PENDING_APPROVAL, UserStatus.SUSPENDED, UserStatus.REJECTED}, "approve")


@router.post("/users/{uid}/reject")
def reject(uid: int, body: Decision, user: User = Depends(require_any("approvals.manage", "district.manage")), db: Session = Depends(get_db)):
    if not body.note:
        raise HTTPException(422, "Give a reason so the applicant knows what to fix")
    return _set(db, user, uid, UserStatus.REJECTED, body.note, {UserStatus.PENDING_APPROVAL}, "reject")


@router.post("/users/{uid}/suspend")
def suspend(uid: int, body: Decision, user: User = Mgr, db: Session = Depends(get_db)):
    return _set(db, user, uid, UserStatus.SUSPENDED, body.note, {UserStatus.ACTIVE}, "suspend")


@router.post("/users/{uid}/block")
def block(uid: int, body: Decision, user: User = Mgr, db: Session = Depends(get_db)):
    return _set(db, user, uid, UserStatus.BLOCKED, body.note, {UserStatus.ACTIVE, UserStatus.SUSPENDED}, "block")


@router.post("/users/{uid}/reactivate")
def reactivate(uid: int, body: Decision, user: User = Mgr, db: Session = Depends(get_db)):
    return _set(db, user, uid, UserStatus.ACTIVE, body.note, {UserStatus.SUSPENDED, UserStatus.BLOCKED}, "reactivate")


class DistrictIn(BaseModel):
    district_id: int | None


@router.put("/users/{uid}/district")
def set_district(uid: int, body: DistrictIn, user: User = Mgr, db: Session = Depends(get_db)):
    t = _target(db, user, uid)
    t.district_id = body.district_id
    audit(db, user.id, "user.district", "user", uid, {"district": body.district_id})
    db.commit()
    return u_out(t)


@router.get("/users/{uid}/documents")
def user_docs(uid: int, user: User = Depends(require_any("approvals.manage", "district.manage")), db: Session = Depends(get_db)):
    _target(db, user, uid)
    return [{"id": d.id, "type": d.doc_type, "name": d.original_name, "status": d.status.value, "note": d.review_note}
            for d in db.scalars(select(UserDocument).where(UserDocument.user_id == uid).order_by(UserDocument.id))]


@router.get("/documents/{did}/file")
def doc_file(did: int, user: User = Depends(require_any("approvals.manage", "district.manage")), db: Session = Depends(get_db)):
    d = db.get(UserDocument, did)
    if not d:
        raise HTTPException(404, "Document not found")
    _target(db, user, d.user_id)
    audit(db, user.id, "document.view", "user_document", did)      # viewing identity documents is audited
    db.commit()
    return Response(document_storage().read(d.storage_key), media_type=d.content_type, headers={"Cache-Control": "no-store", "Content-Disposition": "attachment"})


class DocDecision(BaseModel):
    approve: bool
    note: str | None = F(default=None, max_length=300)


@router.post("/documents/{did}/review")
def review_doc(did: int, body: DocDecision, user: User = Depends(require_any("approvals.manage", "district.manage")), db: Session = Depends(get_db)):
    d = db.get(UserDocument, did)
    if not d:
        raise HTTPException(404, "Document not found")
    _target(db, user, d.user_id)
    d.status = DocStatusV.VERIFIED if body.approve else DocStatusV.REJECTED
    d.review_note, d.reviewed_by = body.note, user.id
    if not body.approve:
        notify(db, d.user_id, "ACCOUNT", f"Document rejected: {d.doc_type}", body.note or "Please upload a clearer copy")
    audit(db, user.id, "document.review", "user_document", did, {"approve": body.approve})
    db.commit()
    return {"ok": True}


class StaffIn(BaseModel):
    full_name: str = F(min_length=2, max_length=160)
    email: EmailStr
    mobile: str | None = None
    password: str = F(min_length=8, max_length=72)
    role: RoleName
    district_id: int | None = None


@router.post("/staff", status_code=201)
def create_staff(body: StaffIn, user: User = Depends(require("users.manage_roles")), db: Session = Depends(get_db)):
    """Staff accounts are created by admins only, never by self-registration."""
    if body.role not in STAFF_ROLES:
        raise HTTPException(422, "Not a staff role")
    if body.role in (RoleName.ADMIN, RoleName.SUPER_ADMIN) and user.role.name != RoleName.SUPER_ADMIN:
        raise HTTPException(403, "Only a super admin can create admins")
    if body.role == RoleName.DISTRICT_MANAGER and not body.district_id:
        raise HTTPException(422, "A district manager needs a district")
    if not password_ok(body.password):
        raise HTTPException(422, "Password must be 8-72 characters with a letter and a digit")
    u = acc.create_account(db, role=body.role, full_name=body.full_name, password=body.password, email=body.email, mobile=body.mobile, status=UserStatus.ACTIVE)
    u.district_id = body.district_id
    u.email_verified = True
    audit(db, user.id, "staff.create", "user", u.id, {"role": body.role.value})
    db.commit()
    return u_out(u)


class RoleChange(BaseModel):
    role: RoleName


@router.put("/users/{uid}/role")
def change_role(uid: int, body: RoleChange, user: User = Depends(require("users.manage_roles")), db: Session = Depends(get_db)):
    if uid == user.id:
        raise HTTPException(409, "You cannot change your own role")
    t = db.get(User, uid)
    if not t:
        raise HTTPException(404, "User not found")
    if user.role.name != RoleName.SUPER_ADMIN and (body.role in (RoleName.ADMIN, RoleName.SUPER_ADMIN) or t.role.name in (RoleName.ADMIN, RoleName.SUPER_ADMIN)):
        raise HTTPException(403, "Only a super admin can change admin roles")
    old = t.role.name.value
    t.role_id = db.scalar(select(Role.id).where(Role.name == body.role))
    acc.revoke_sessions(db, t.id)
    audit(db, user.id, "user.role_change", "user", uid, {"from": old, "to": body.role.value})
    db.commit()
    return u_out(t)


@router.post("/users/{uid}/reset-password")
def force_reset(uid: int, user: User = Mgr, db: Session = Depends(get_db)):
    """Signs the user out everywhere; they then use 'forgot password'."""
    t = _target(db, user, uid)
    acc.revoke_sessions(db, t.id)
    audit(db, user.id, "user.force_logout", "user", uid)
    db.commit()
    return {"ok": True}


# ---------------- deletion requests ----------------
@router.get("/deletion-requests")
def deletion_requests(user: User = Mgr, db: Session = Depends(get_db)):
    rows = db.execute(select(DeletionRequest, User.full_name).join(User, User.id == DeletionRequest.user_id)
                      .where(DeletionRequest.status == "PENDING").order_by(DeletionRequest.id).limit(100)).all()
    return [{"id": r.id, "user_id": r.user_id, "name": n, "reason": r.reason, "at": r.created_at.isoformat()} for r, n in rows]


@router.post("/deletion-requests/{rid}/process")
def process_deletion(rid: int, approve: bool, user: User = Depends(require("superadmin.manage")), db: Session = Depends(get_db)):
    """Approve = anonymise personal details and sign the user out. Orders and ledger rows stay (legal retention) but no longer identify the person."""
    r = db.get(DeletionRequest, rid)
    if not r or r.status != "PENDING":
        raise HTTPException(404, "Request not found")
    r.processed_by = user.id
    if not approve:
        r.status = "REJECTED"
    else:
        t = db.get(User, r.user_id)
        t.full_name, t.email, t.phone, t.photo_key = "Deleted user", None, None, None
        t.password_hash = hash_password(__import__("secrets").token_urlsafe(24))
        t.privacy, t.notif_prefs = None, None
        acc.set_status(t, UserStatus.DELETED)
        acc.revoke_sessions(db, t.id)
        for d in db.scalars(select(UserDocument).where(UserDocument.user_id == t.id)):
            try:
                document_storage().delete(d.storage_key)
            except Exception:
                pass
            db.delete(d)
        r.status = "DONE"
    audit(db, user.id, "deletion.process", "user", r.user_id, {"approve": approve})
    db.commit()
    return {"status": r.status}


