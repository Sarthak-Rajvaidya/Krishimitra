"""Expert discovery, consultations (appointments + chat) and the expert dashboard."""
import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field as F
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require
from app.api.v1.common import page_args
from app.core.audit import audit
from app.core.ratelimit import rate_limit
from app.db.base import as_utc, utcnow
from app.db.session import get_db
from app.models import (Appointment, ConsultMessage, CropDiagnosis, ExpertProfile, ExpertReviewStatus, Product, RoleName, ShareLink, User,
                        UserStatus)
from app.services import wallet
from app.services.notify import notify

router = APIRouter(tags=["experts"])
Farmer = Depends(require("expert.consult"))
Expert = Depends(require("expert.practice"))


def expert_out(p: ExpertProfile, u: User) -> dict:
    return {"id": u.id, "name": u.full_name, "qualification": p.qualification, "specialization": [s for s in p.specialization.split(",") if s],
            "experience_years": p.experience_years, "district": p.district, "state": p.state, "fee_paise": p.fee_paise, "bio": p.bio,
            "languages": p.languages.split(","), "modes": p.modes.split(","), "availability": p.availability,
            "rating_avg": p.rating_avg, "rating_count": p.rating_count}


@router.get("/experts")
def find_experts(q: str | None = None, specialization: str | None = None, district: str | None = None, language: str | None = None,
                 max_fee_rupees: int | None = None, page: int = 1, size: int = 20, db: Session = Depends(get_db)):
    stmt = select(ExpertProfile, User).join(User, User.id == ExpertProfile.user_id).where(User.status == UserStatus.ACTIVE)
    if q:
        stmt = stmt.where(or_(func.lower(User.full_name).like(f"%{q.lower()}%"), func.lower(ExpertProfile.specialization).like(f"%{q.lower()}%")))
    if specialization:
        stmt = stmt.where(func.lower(ExpertProfile.specialization).like(f"%{specialization.lower()}%"))
    if district:
        stmt = stmt.where(func.lower(ExpertProfile.district) == district.lower())
    if language:
        stmt = stmt.where(ExpertProfile.languages.like(f"%{language}%"))
    if max_fee_rupees is not None:
        stmt = stmt.where(ExpertProfile.fee_paise <= max_fee_rupees * 100)
    off, size = page_args(page, size)
    return [expert_out(p, u) for p, u in db.execute(stmt.order_by(ExpertProfile.rating_avg.desc(), ExpertProfile.id).offset(off).limit(size))]


@router.get("/experts/{eid}")
def expert_detail(eid: int, db: Session = Depends(get_db)):
    row = db.execute(select(ExpertProfile, User).join(User, User.id == ExpertProfile.user_id).where(User.id == eid, User.status == UserStatus.ACTIVE)).first()
    if not row:
        raise HTTPException(404, "Expert not found")
    return expert_out(*row)


# ---------------- appointments ----------------
class BookIn(BaseModel):
    expert_id: int
    mode: str = F(pattern="^(CHAT|AUDIO|VIDEO|VISIT)$")
    scheduled_at: datetime
    topic: str = F(min_length=3, max_length=300)
    diagnosis_id: int | None = None
    crop_id: int | None = None
    parent_id: int | None = None
    pay_from_wallet: bool = False


def appt_out(a: Appointment, other_name: str | None = None) -> dict:
    return {"id": a.id, "farmer_id": a.farmer_id, "expert_id": a.expert_id, "other": other_name, "mode": a.mode, "status": a.status,
            "scheduled_at": a.scheduled_at.isoformat(), "topic": a.topic, "fee_paise": a.fee_paise, "paid": a.paid, "meeting_url": a.meeting_url,
            "expert_notes": a.expert_notes, "recommended_product_ids": a.recommended_product_ids, "diagnosis_id": a.diagnosis_id, "parent_id": a.parent_id}


@router.post("/appointments", status_code=201)
def book(body: BookIn, user: User = Farmer, db: Session = Depends(get_db)):
    rate_limit(f"appt:{user.id}", 10)
    p = db.scalar(select(ExpertProfile).where(ExpertProfile.user_id == body.expert_id))
    e = db.get(User, body.expert_id)
    if not p or not e or e.status != UserStatus.ACTIVE:
        raise HTTPException(404, "Expert not found")
    if body.mode not in p.modes.split(","):
        raise HTTPException(422, f"This expert offers: {p.modes}")
    when = as_utc(body.scheduled_at)
    if when < utcnow() + timedelta(minutes=15):
        raise HTTPException(422, "Choose a time at least 15 minutes from now")
    if db.scalar(select(Appointment.id).where(Appointment.expert_id == e.id, Appointment.status.in_(("REQUESTED", "CONFIRMED")),
                                              Appointment.scheduled_at > when - timedelta(minutes=30), Appointment.scheduled_at < when + timedelta(minutes=30)).limit(1)):
        raise HTTPException(409, "That slot is taken. Pick another time")
    if body.diagnosis_id:
        d = db.get(CropDiagnosis, body.diagnosis_id)
        if not d or d.user_id != user.id:
            raise HTTPException(404, "Diagnosis not found")
        if d.expert_review == ExpertReviewStatus.NOT_REQUESTED:
            d.expert_review = ExpertReviewStatus.REQUESTED
    a = Appointment(farmer_id=user.id, expert_id=e.id, mode=body.mode, scheduled_at=when, topic=body.topic, fee_paise=p.fee_paise,
                    diagnosis_id=body.diagnosis_id, crop_id=body.crop_id, parent_id=body.parent_id, is_demo=user.is_demo)
    db.add(a)
    db.flush()
    if body.pay_from_wallet and p.fee_paise:
        wallet.debit(db, user.id, p.fee_paise, "CONSULT_PAYMENT", f"AP{a.id}")
        a.paid = True
    notify(db, e.id, "APPOINTMENT", "New consultation request", f"{user.full_name}: {body.topic[:80]}", data={"appointment_id": a.id}, sms=True)
    db.commit()
    return appt_out(a, e.full_name)


@router.get("/appointments")
def my_appointments(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Farmers see their bookings, experts see requests for them."""
    q = select(Appointment).where(or_(Appointment.farmer_id == user.id, Appointment.expert_id == user.id)).order_by(Appointment.scheduled_at.desc()).limit(100)
    rows = db.scalars(q).all()
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_({r.farmer_id for r in rows} | {r.expert_id for r in rows})))} if rows else {}
    return [appt_out(a, names.get(a.expert_id if a.farmer_id == user.id else a.farmer_id)) for a in rows]


def _party(db: Session, user: User, aid: int) -> Appointment:
    a = db.get(Appointment, aid)
    if not a or user.id not in (a.farmer_id, a.expert_id):
        raise HTTPException(404, "Appointment not found")
    return a


@router.post("/appointments/{aid}/cancel")
def cancel(aid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = _party(db, user, aid)
    if a.status not in ("REQUESTED", "CONFIRMED"):
        raise HTTPException(409, "Appointment is already closed")
    a.status = "CANCELLED"
    if a.paid:
        wallet.credit(db, a.farmer_id, a.fee_paise, "REFUND", f"AP{a.id}")
        a.paid = False
    notify(db, a.expert_id if user.id == a.farmer_id else a.farmer_id, "APPOINTMENT", "Consultation cancelled", a.topic[:80])
    db.commit()
    return appt_out(a)


class PayIn(BaseModel):
    pass


@router.post("/appointments/{aid}/pay")
def pay(aid: int, user: User = Depends(require("expert.consult", "wallet.use")), db: Session = Depends(get_db)):
    a = _party(db, user, aid)
    if a.farmer_id != user.id or a.paid or a.status not in ("REQUESTED", "CONFIRMED"):
        raise HTTPException(409, "Nothing to pay")
    wallet.debit(db, user.id, a.fee_paise, "CONSULT_PAYMENT", f"AP{a.id}")
    a.paid = True
    db.commit()
    return appt_out(a)


class DecideIn(BaseModel):
    action: str = F(pattern="^(CONFIRM|DECLINE|COMPLETE|NO_SHOW)$")
    meeting_url: str | None = F(default=None, max_length=300, pattern=r"^https://")
    expert_notes: str | None = F(default=None, max_length=4000)
    recommended_product_ids: list[int] | None = F(default=None, max_length=10)


@router.post("/appointments/{aid}/decide")
def decide(aid: int, body: DecideIn, user: User = Expert, db: Session = Depends(get_db)):
    a = _party(db, user, aid)
    if a.expert_id != user.id:
        raise HTTPException(403, "Only the expert can do this")
    moves = {"CONFIRM": ("REQUESTED", "CONFIRMED"), "DECLINE": ("REQUESTED", "DECLINED"), "COMPLETE": ("CONFIRMED", "COMPLETED"), "NO_SHOW": ("CONFIRMED", "NO_SHOW")}
    frm, to = moves[body.action]
    if a.status != frm:
        raise HTTPException(409, f"Appointment must be {frm} to {body.action.lower()}")
    a.status = to
    if body.meeting_url:
        a.meeting_url = body.meeting_url
    if body.expert_notes is not None:
        a.expert_notes = body.expert_notes
    if body.recommended_product_ids is not None:
        ids = db.scalars(select(Product.id).where(Product.id.in_(body.recommended_product_ids), Product.is_active.is_(True))).all()
        a.recommended_product_ids = list(ids)
    if to == "DECLINED" and a.paid:
        wallet.credit(db, a.farmer_id, a.fee_paise, "REFUND", f"AP{a.id}")
        a.paid = False
    if to == "COMPLETED":
        if a.paid and a.fee_paise:
            from app.core.config import get_settings
            wallet.credit(db, a.expert_id, a.fee_paise - a.fee_paise * get_settings().commission_bp // 10_000, "CONSULT_EARNING", f"AP{a.id}")
        if a.diagnosis_id:
            d = db.get(CropDiagnosis, a.diagnosis_id)
            if d:
                d.expert_review = ExpertReviewStatus.REVIEWED
    notify(db, a.farmer_id, "APPOINTMENT", f"Consultation {to.lower().replace('_', ' ')}", a.topic[:80], sms=to in ("CONFIRMED", "DECLINED"))
    db.commit()
    return appt_out(a)


# ---------------- chat ----------------
class MsgIn(BaseModel):
    body: str = F(min_length=1, max_length=2000)


@router.get("/appointments/{aid}/messages")
def messages(aid: int, after_id: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = _party(db, user, aid)
    rows = db.scalars(select(ConsultMessage).where(ConsultMessage.appointment_id == a.id, ConsultMessage.id > after_id).order_by(ConsultMessage.id).limit(200))
    return [{"id": m.id, "mine": m.sender_id == user.id, "body": m.body, "at": m.created_at.isoformat()} for m in rows]


@router.post("/appointments/{aid}/messages", status_code=201)
def send(aid: int, body: MsgIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rate_limit(f"cm:{user.id}", 30)
    a = _party(db, user, aid)
    if a.status not in ("REQUESTED", "CONFIRMED", "COMPLETED"):
        raise HTTPException(409, "Chat is closed for this consultation")
    m = ConsultMessage(appointment_id=a.id, sender_id=user.id, body=body.body, created_at=utcnow())
    db.add(m)
    notify(db, a.expert_id if user.id == a.farmer_id else a.farmer_id, "EXPERT", "New message", body.body[:100], dedupe_key=f"cm{a.id}", dedupe_hours=1)
    db.commit()
    return {"id": m.id}


# ---------------- expert dashboard ----------------
@router.get("/expert/dashboard")
def dashboard(user: User = Expert, db: Session = Depends(get_db)):
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    cnt = lambda *c: db.scalar(select(func.count(Appointment.id)).where(Appointment.expert_id == user.id, *c))  # noqa: E731
    p = db.scalar(select(ExpertProfile).where(ExpertProfile.user_id == user.id))
    pending_reviews = db.scalar(select(func.count(CropDiagnosis.id)).where(CropDiagnosis.expert_review == ExpertReviewStatus.REQUESTED))
    return {"pending_requests": cnt(Appointment.status == "REQUESTED"), "today": cnt(Appointment.scheduled_at >= today, Appointment.scheduled_at < today + timedelta(days=1), Appointment.status == "CONFIRMED"),
            "completed": cnt(Appointment.status == "COMPLETED"), "rating_avg": p.rating_avg if p else 0, "rating_count": p.rating_count if p else 0,
            "open_disease_reviews": pending_reviews, "wallet": wallet.get_wallet(db, user.id).balance_paise}


class ProfileIn(BaseModel):
    bio: str | None = F(default=None, max_length=2000)
    fee_rupees: int | None = F(default=None, ge=0, le=10000)
    availability: dict | None = None
    modes: list[str] | None = None
    languages: list[str] | None = None


@router.put("/expert/profile")
def update_profile(body: ProfileIn, user: User = Expert, db: Session = Depends(get_db)):
    p = db.scalar(select(ExpertProfile).where(ExpertProfile.user_id == user.id))
    if not p:
        raise HTTPException(404, "Profile missing")
    if body.bio is not None:
        p.bio = body.bio
    if body.fee_rupees is not None:
        p.fee_paise = body.fee_rupees * 100
    if body.availability is not None:
        p.availability = body.availability
    if body.modes:
        p.modes = ",".join(m for m in body.modes if m in ("CHAT", "AUDIO", "VIDEO", "VISIT"))
    if body.languages:
        p.languages = ",".join(body.languages)
    db.commit()
    return {"ok": True}


# ---------------- expert reviews of shared diagnoses ----------------
@router.post("/crop/diagnoses/{did}/share")
def share_diagnosis(did: int, hours: int = 72, user: User = Depends(require("ai.use")), db: Session = Depends(get_db)):
    """Creates a time-limited link an expert (or anyone you send it to) can open. Revocable."""
    d = db.get(CropDiagnosis, did)
    if not d or d.user_id != user.id:
        raise HTTPException(404, "Diagnosis not found")
    token = secrets.token_urlsafe(24)
    db.add(ShareLink(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id, target_type="DIAGNOSIS", target_id=did,
                     expires_at=utcnow() + timedelta(hours=max(1, min(hours, 168)))))
    audit(db, user.id, "diagnosis.share", "diagnosis", did)
    db.commit()
    return {"token": token, "expires_in_hours": hours}


@router.get("/shared/{token}")
def open_shared(token: str, db: Session = Depends(get_db)):
    from app.api.v1.crop import diag_out
    s = db.scalar(select(ShareLink).where(ShareLink.token_hash == hashlib.sha256(token.encode()).hexdigest()))
    if not s or s.revoked or as_utc(s.expires_at) < utcnow():
        raise HTTPException(404, "Link not found or expired")
    d = db.get(CropDiagnosis, s.target_id)
    if not d:
        raise HTTPException(404, "Not found")
    out = diag_out(d)
    out["image_url"] = None            # the image itself stays private; ask the farmer for it in chat
    return out


@router.get("/expert/disease-reviews")
def open_reviews(user: User = Expert, db: Session = Depends(get_db)):
    rows = db.scalars(select(CropDiagnosis).where(CropDiagnosis.expert_review == ExpertReviewStatus.REQUESTED).order_by(CropDiagnosis.id).limit(50))
    return [{"id": d.id, "crop": d.crop, "symptoms": d.symptoms, "district": d.district, "predictions": [(p.class_label, round(p.probability, 3)) for p in d.predictions]} for d in rows]


