"""Notifications: in-app rows are written immediately; SMS/email go through an outbox processed by the worker."""
import logging
import smtplib
from datetime import timedelta
from email.message import EmailMessage

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import utcnow
from app.models import Notification, NotificationOutbox, Role, RoleName, User, UserStatus

log = logging.getLogger("notify")
DEFAULT_PREFS = {"in_app": True, "sms": True, "email": False, "push": False, "muted_kinds": []}
CRITICAL = {"ACCOUNT", "ORDER", "DELIVERY", "PAYMENT"}


def prefs_of(user: User) -> dict:
    return {**DEFAULT_PREFS, **(user.notif_prefs or {})}


def notify(db: Session, user_id: int, kind: str, title: str, body: str = "", data: dict | None = None,
           dedupe_key: str | None = None, dedupe_hours: int = 12, sms: bool = False, email: bool = False) -> Notification | None:
    """Add a notification inside the caller's transaction. Returns None when suppressed (duplicate / muted)."""
    user = db.get(User, user_id)
    if not user:
        return None
    p = prefs_of(user)
    if kind in p["muted_kinds"] and kind not in CRITICAL:
        return None
    if dedupe_key:
        since = utcnow() - timedelta(hours=dedupe_hours)
        last = db.scalar(select(Notification).where(Notification.user_id == user_id, Notification.dedupe_key == dedupe_key,
                                                    Notification.created_at >= since).limit(1))
        if last:
            return None
    n = Notification(user_id=user_id, kind=kind, title=title[:160], body=body[:500], data=data, dedupe_key=dedupe_key, created_at=utcnow())
    db.add(n)
    db.flush()
    if sms and p["sms"] and user.phone and user.mobile_verified:
        db.add(NotificationOutbox(notification_id=n.id, user_id=user_id, channel="SMS", target=user.phone, body=f"{title}. {body}"[:300], created_at=utcnow()))
    if email and p["email"] and user.email:
        db.add(NotificationOutbox(notification_id=n.id, user_id=user_id, channel="EMAIL", target=user.email, subject=title[:160], body=body or title, created_at=utcnow()))
    return n


def notify_role(db: Session, role: RoleName, kind: str, title: str, body: str = "", district_id: int | None = None, limit: int = 200) -> int:
    q = select(User.id).join(Role, Role.id == User.role_id).where(Role.name == role, User.status == UserStatus.ACTIVE)
    if district_id is not None:
        q = q.where(User.district_id == district_id)
    ids = db.scalars(q.limit(limit)).all()
    for uid in ids:
        notify(db, uid, kind, title, body)
    return len(ids)


# ---------- delivery adapters ----------
def send_sms(to: str, text: str) -> None:
    s = get_settings()
    if s.sms_provider == "twilio":
        if not (s.twilio_account_sid and s.twilio_auth_token and s.twilio_from):
            raise RuntimeError("Twilio not configured")
        r = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}/Messages.json",
                       data={"To": f"+91{to}" if len(to) == 10 else to, "From": s.twilio_from, "Body": text},
                       auth=(s.twilio_account_sid, s.twilio_auth_token), timeout=10)
        if r.status_code >= 300:
            raise RuntimeError(f"Twilio HTTP {r.status_code}")
        return
    # console provider: development only. Message text is never logged (it may contain an OTP).
    log.info("SMS (console provider) to ******%s [text withheld]", to[-4:])


def send_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if not s.smtp_host:
        log.info("EMAIL (no SMTP configured) to %s subject=%r [body withheld]", to.split("@")[-1], subject)
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
        smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


def deliver_now(channel: str, target: str, subject: str, body: str) -> bool:
    try:
        if channel == "SMS":
            send_sms(target, body)
        elif channel == "EMAIL":
            send_email(target, subject, body)
        else:
            raise RuntimeError("push provider not configured")
        return True
    except Exception as ex:
        log.warning("delivery failed channel=%s err=%s", channel, type(ex).__name__)
        return False


def process_outbox(db: Session, limit: int = 100) -> dict:
    rows = db.scalars(select(NotificationOutbox).where(NotificationOutbox.status == "PENDING", NotificationOutbox.attempts < 5)
                      .order_by(NotificationOutbox.id).limit(limit).with_for_update(skip_locked=True) if db.bind.dialect.name == "postgresql"
                      else select(NotificationOutbox).where(NotificationOutbox.status == "PENDING", NotificationOutbox.attempts < 5)
                      .order_by(NotificationOutbox.id).limit(limit)).all()
    sent = failed = 0
    for o in rows:
        o.attempts += 1
        if deliver_now(o.channel, o.target, o.subject, o.body):
            o.status, o.sent_at, sent = "SENT", utcnow(), sent + 1
        elif o.attempts >= 5:
            o.status, o.error, failed = "FAILED", "gave up after 5 attempts", failed + 1
    db.commit()
    return {"sent": sent, "failed": failed, "picked": len(rows)}
