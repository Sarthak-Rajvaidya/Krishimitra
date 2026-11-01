"""Learning centre, government schemes and financial information (all editable CMS content)."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as F
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require
from app.api.v1.common import page_args
from app.core.audit import audit
from app.db.session import get_db
from app.models import Content, FarmerProfile, SavedContent, SchemeApplication, User

router = APIRouter(tags=["content"])
Cms = Depends(require("content.manage"))
KINDS = "ARTICLE|GUIDE|VIDEO|TRAINING|SCHEME|FAQ|LOAN|INSURANCE|ANNOUNCEMENT|DISEASE|PEST"
FIN_NOTE = "Information only. KrishiMitra does not lend or sell insurance. Confirm terms, rates and eligibility with the bank, insurer or official portal."


def c_out(c: Content, full: bool = False) -> dict:
    d = {"id": c.id, "kind": c.kind, "category": c.category, "title": c.title, "summary": c.summary, "language": c.language, "state": c.state,
         "level": c.level, "url": c.url, "deadline": c.deadline, "needs_verification": c.needs_verification, "source": c.source}
    if c.kind in ("SCHEME", "LOAN", "INSURANCE"):
        d["note"] = ("Details not yet verified against the official source. Check the link before applying." if c.needs_verification else None)
        if c.kind != "SCHEME":
            d["disclaimer"] = FIN_NOTE
    if full:
        d.update(body=c.body, eligibility=c.eligibility, documents_required=c.documents_required, procedure=c.procedure, benefits=c.benefits, meta=c.meta)
    return d


@router.get("/content")
def browse(kind: str | None = Query(None, pattern=f"^({KINDS})$"), category: str | None = None, language: str | None = None, state: str | None = None,
           q: str | None = Query(None, max_length=60), page: int = 1, size: int = 20, db: Session = Depends(get_db)):
    stmt = select(Content).where(Content.is_published.is_(True))
    if kind:
        stmt = stmt.where(Content.kind == kind)
    if category:
        stmt = stmt.where(func.lower(Content.category) == category.lower())
    if language:
        stmt = stmt.where(Content.language.in_((language, "en")))
    if state:
        stmt = stmt.where(or_(Content.state.is_(None), func.lower(Content.state) == state.lower()))
    if q:
        stmt = stmt.where(or_(func.lower(Content.title).like(f"%{q.lower()}%"), func.lower(Content.summary).like(f"%{q.lower()}%")))
    off, size = page_args(page, size)
    return [c_out(c) for c in db.scalars(stmt.order_by(Content.id.desc()).offset(off).limit(size))]


@router.get("/content/{cid}")
def detail(cid: int, db: Session = Depends(get_db)):
    c = db.get(Content, cid)
    if not c or not c.is_published:
        raise HTTPException(404, "Not found")
    return c_out(c, True)


@router.get("/schemes/for-me")
def schemes_for_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Schemes for the farmer's state (plus central ones). Eligibility is shown as text; the farmer decides - nothing is auto-judged."""
    fp = db.scalar(select(FarmerProfile).where(FarmerProfile.user_id == user.id))
    st = fp.state if fp and fp.state else None
    stmt = select(Content).where(Content.is_published.is_(True), Content.kind == "SCHEME")
    stmt = stmt.where(or_(Content.state.is_(None), func.lower(Content.state) == st.lower())) if st else stmt
    return [c_out(c) for c in db.scalars(stmt.order_by(Content.level, Content.title).limit(100))]


@router.post("/content/{cid}/save")
def save(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not db.get(Content, cid):
        raise HTTPException(404, "Not found")
    if not db.scalar(select(SavedContent.id).where(SavedContent.user_id == user.id, SavedContent.content_id == cid)):
        db.add(SavedContent(user_id=user.id, content_id=cid))
        db.commit()
    return {"ok": True}


@router.delete("/content/{cid}/save")
def unsave(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.scalar(select(SavedContent).where(SavedContent.user_id == user.id, SavedContent.content_id == cid))
    if s:
        db.delete(s)
        db.commit()
    return {"ok": True}


@router.get("/saved")
def saved(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [c_out(c) for c in db.scalars(select(Content).join(SavedContent, SavedContent.content_id == Content.id).where(SavedContent.user_id == user.id).limit(200))]


# ---------------- scheme application tracker (self-reported) ----------------
class AppIn(BaseModel):
    content_id: int
    status: str = F(default="PLANNED", pattern="^(PLANNED|APPLIED|APPROVED|REJECTED)$")
    reference_no: str | None = F(default=None, max_length=80)
    note: str | None = F(default=None, max_length=300)


@router.get("/scheme-applications")
def my_applications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(SchemeApplication, Content.title).join(Content, Content.id == SchemeApplication.content_id)
                      .where(SchemeApplication.user_id == user.id).order_by(SchemeApplication.id.desc())).all()
    return [{"id": a.id, "content_id": a.content_id, "scheme": t, "status": a.status, "reference_no": a.reference_no, "note": a.note} for a, t in rows]


@router.put("/scheme-applications")
def track(body: AppIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(Content, body.content_id)
    if not c or c.kind != "SCHEME":
        raise HTTPException(404, "Scheme not found")
    a = db.scalar(select(SchemeApplication).where(SchemeApplication.user_id == user.id, SchemeApplication.content_id == c.id))
    if not a:
        a = SchemeApplication(user_id=user.id, content_id=c.id)
        db.add(a)
    a.status, a.reference_no, a.note = body.status, body.reference_no, body.note
    db.commit()
    return {"id": a.id, "status": a.status}


# ---------------- CMS (admin) ----------------
class ContentIn(BaseModel):
    kind: str = F(pattern=f"^({KINDS})$")
    category: str | None = F(default=None, max_length=60)
    title: str = F(min_length=3, max_length=240)
    summary: str | None = F(default=None, max_length=500)
    body: str = F(default="", max_length=40000)
    language: str = F(default="en", pattern="^(en|hi|mr)$")
    state: str | None = None
    level: str | None = F(default=None, pattern="^(CENTRAL|STATE)$")
    url: str | None = F(default=None, max_length=400, pattern=r"^https?://")
    eligibility: str | None = None
    documents_required: str | None = None
    procedure: str | None = None
    benefits: str | None = None
    deadline: date | None = None
    source: str | None = F(default=None, max_length=200)
    meta: dict | None = None
    needs_verification: bool = True
    is_published: bool = False


@router.get("/admin/content")
def admin_list(kind: str | None = None, page: int = 1, size: int = 50, user: User = Cms, db: Session = Depends(get_db)):
    stmt = select(Content).order_by(Content.id.desc())
    if kind:
        stmt = stmt.where(Content.kind == kind)
    off, size = page_args(page, size)
    return [{**c_out(c), "is_published": c.is_published} for c in db.scalars(stmt.offset(off).limit(size))]


@router.post("/admin/content", status_code=201)
def admin_create(body: ContentIn, user: User = Cms, db: Session = Depends(get_db)):
    c = Content(created_by=user.id, **body.model_dump())
    db.add(c)
    audit(db, user.id, "content.create", "content", None, {"kind": body.kind})
    db.commit()
    return c_out(c, True)


@router.put("/admin/content/{cid}")
def admin_update(cid: int, body: ContentIn, user: User = Cms, db: Session = Depends(get_db)):
    c = db.get(Content, cid)
    if not c:
        raise HTTPException(404, "Not found")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    audit(db, user.id, "content.update", "content", cid)
    db.commit()
    return c_out(c, True)


@router.delete("/admin/content/{cid}")
def admin_delete(cid: int, user: User = Cms, db: Session = Depends(get_db)):
    c = db.get(Content, cid)
    if not c:
        raise HTTPException(404, "Not found")
    c.is_published = False
    audit(db, user.id, "content.unpublish", "content", cid)
    db.commit()
    return {"ok": True}
