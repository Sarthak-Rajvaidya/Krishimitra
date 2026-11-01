from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.crop_doctor.imaging import validate_and_clean
from app.ai.crop_doctor.inference import get_classifier
from app.ai.recommendations.service import recommend
from app.api.deps import require
from app.api.v1.auth import rate_limit
from app.core.storage import image_storage
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (CropDiagnosis, DiagnosisFollowup, DiagnosisPrediction, DiagnosisStatus, ExpertReviewStatus,
                        ModelVersion, Recommendation, RecommendationFeedback, User)

router = APIRouter(tags=["crop-doctor"])
ai_user = require("ai.use")


def diag_out(d: CropDiagnosis) -> dict:
    return {"id": d.id, "crop": d.crop, "crop_stage": d.crop_stage, "plant_part": d.plant_part, "symptoms": d.symptoms,
            "status": d.status.value, "created_at": d.created_at.isoformat(), "user_agrees": d.user_agrees,
            "expert_review": d.expert_review.value, "is_demo": d.is_demo, "image_url": f"/api/v1/crop/diagnoses/{d.id}/image",
            "predictions": [{"label": p.class_label, "score": round(p.probability, 4)} for p in d.predictions],
            "score_note": "Scores are raw model outputs, not calibrated probabilities of a correct diagnosis.",
            "model_note": "No trained model was available; no image-based prediction was made." if d.status == DiagnosisStatus.MODEL_UNAVAILABLE else None,
            "uncertain": d.status == DiagnosisStatus.LOW_CONFIDENCE,
            "followups": [{"note": f.note, "outcome": f.outcome, "at": f.created_at.isoformat()} for f in d.followups]}


def _own(db: Session, user: User, did: int) -> CropDiagnosis:
    d = db.get(CropDiagnosis, did)
    if not d or d.user_id != user.id:
        raise HTTPException(404, "Diagnosis not found")
    return d


@router.get("/crop/model-status")
def model_status(user: User = Depends(ai_user)):
    st = get_classifier().status()
    return {"available": st["available"], "reason": st.get("reason"),
            "model": (st.get("card") or {}).get("name"), "version": (st.get("card") or {}).get("version")}


@router.post("/crop/diagnose", status_code=201)
async def diagnose(request: Request, image: UploadFile = File(...), crop: str | None = Form(None, max_length=80),
                   crop_stage: str | None = Form(None, max_length=80), plant_part: str | None = Form(None, max_length=80),
                   symptoms: str | None = Form(None, max_length=1000), district: str | None = Form(None, max_length=120),
                   user: User = Depends(ai_user), db: Session = Depends(get_db)):
    rate_limit(f"diag:{user.id}", 10)
    raw = await image.read(10 * 1024 * 1024)
    clean, ext = validate_and_clean(raw)
    key = image_storage().save(clean, ext)
    clf = get_classifier()
    pred = clf.predict(clean)
    mv = None
    if pred.available:
        mv = db.scalar(select(ModelVersion).where(ModelVersion.name == pred.model_name, ModelVersion.version == pred.model_version))
    status = DiagnosisStatus.MODEL_UNAVAILABLE if not pred.available else (
        DiagnosisStatus.LOW_CONFIDENCE if pred.uncertain else DiagnosisStatus.PREDICTED)
    d = CropDiagnosis(user_id=user.id, image_key=key, crop=crop, crop_stage=crop_stage, plant_part=plant_part,
                      symptoms=symptoms, district=district, status=status, model_version_id=mv.id if mv else None,
                      is_demo=user.is_demo)
    if pred.available:
        for i, (label, p) in enumerate(pred.top or [], start=1):
            d.predictions.append(DiagnosisPrediction(rank=i, class_label=label, probability=p))
    db.add(d)
    db.commit()
    return diag_out(d)


@router.get("/crop/diagnoses")
def my_diagnoses(user: User = Depends(ai_user), db: Session = Depends(get_db)):
    return [diag_out(d) for d in db.scalars(select(CropDiagnosis).where(CropDiagnosis.user_id == user.id).order_by(CropDiagnosis.id.desc()))]


@router.get("/crop/diagnoses/{did}")
def get_diag(did: int, user: User = Depends(ai_user), db: Session = Depends(get_db)):
    return diag_out(_own(db, user, did))


@router.get("/crop/diagnoses/{did}/image")
def get_image(did: int, user: User = Depends(ai_user), db: Session = Depends(get_db)):
    d = _own(db, user, did)
    try:
        return Response(image_storage().read(d.image_key), media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=3600"})
    except FileNotFoundError:
        raise HTTPException(404, "Image not available")


class Agree(BaseModel):
    agrees: bool


@router.post("/crop/diagnoses/{did}/feedback")
def feedback(did: int, body: Agree, user: User = Depends(ai_user), db: Session = Depends(get_db)):
    d = _own(db, user, did)
    d.user_agrees = body.agrees
    db.commit()
    return {"ok": True}


class Followup(BaseModel):
    note: str = Field(min_length=3, max_length=1000)
    outcome: str | None = Field(default=None, pattern="^(improved|same|worse)$")


@router.post("/crop/diagnoses/{did}/followups", status_code=201)
def add_followup(did: int, body: Followup, user: User = Depends(ai_user), db: Session = Depends(get_db)):
    d = _own(db, user, did)
    d.followups.append(DiagnosisFollowup(note=body.note, outcome=body.outcome, created_at=utcnow()))
    db.commit()
    return diag_out(d)


@router.post("/crop/diagnoses/{did}/expert-review")
def request_expert(did: int, user: User = Depends(ai_user), db: Session = Depends(get_db)):
    d = _own(db, user, did)
    if d.expert_review == ExpertReviewStatus.NOT_REQUESTED:
        d.expert_review = ExpertReviewStatus.REQUESTED
        db.commit()
    return diag_out(d)


# ---- recommendations ----
@router.post("/recommendations/diagnosis/{did}")
def recommendations(did: int, conversation_id: int | None = None, user: User = Depends(ai_user), db: Session = Depends(get_db)):
    return recommend(db, user.id, _own(db, user, did), conversation_id)


@router.post("/recommendations/{rid}/viewed")
def viewed(rid: int, user: User = Depends(ai_user), db: Session = Depends(get_db)):
    r = db.get(Recommendation, rid)
    if not r or r.user_id != user.id:
        raise HTTPException(404, "Not found")
    r.viewed_at = r.viewed_at or utcnow()
    db.commit()
    return {"ok": True}


class RecFeedback(BaseModel):
    helpful: bool
    outcome: str | None = Field(default=None, pattern="^(improved|same|worse|not_used)$")
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/recommendations/{rid}/feedback", status_code=201)
def rec_feedback(rid: int, body: RecFeedback, user: User = Depends(ai_user), db: Session = Depends(get_db)):
    r = db.get(Recommendation, rid)
    if not r or r.user_id != user.id:
        raise HTTPException(404, "Not found")
    db.add(RecommendationFeedback(recommendation_id=rid, user_id=user.id, created_at=utcnow(), **body.model_dump()))
    db.commit()
    return {"ok": True}


# ---- AI -> marketplace: compare sellers for a recommended product ----
@router.get("/recommendations/{rid}/offers")
def offers(rid: int, district: str | None = None, user: User = Depends(ai_user), db: Session = Depends(get_db)):
    """Same-type products from approved sellers, cheapest per unit first, with sellers in your district marked.
    The recommendation itself never depends on this (advice is not ranked by price)."""
    from app.api.v1.common import product_out, stock_map
    from app.models import Product, SupplierProfile
    r = db.get(Recommendation, rid)
    if not r or r.user_id != user.id or not r.product_id:
        raise HTTPException(404, "Not found")
    base = db.get(Product, r.product_id)
    cands = db.scalars(select(Product).where(Product.product_type == base.product_type, Product.is_active.is_(True), Product.deleted_at.is_(None),
                                             Product.approval_status == "APPROVED", Product.category_id == base.category_id).limit(40)).unique().all()
    st = stock_map(db, [p.id for p in cands])
    sup = {s.user_id: s for s in db.scalars(select(SupplierProfile).where(SupplierProfile.user_id.in_([p.supplier_id for p in cands if p.supplier_id])))}
    out = []
    for p in cands:
        s = sup.get(p.supplier_id) if p.supplier_id else None
        o = product_out(p, st.get(p.id, 0))
        o.update(seller=s.shop_name if s else "KrishiMitra", seller_id=p.supplier_id, seller_district=s.district if s else None,
                 same_district=bool(district and s and s.district and s.district.lower() == district.lower()), is_recommended_product=p.id == base.id)
        out.append(o)
    out.sort(key=lambda o: (not o["in_stock"], o["unit_price_paise"] or o["price_paise"]))
    return {"offers": out[:15], "note": "Sorted by price per unit. Only the recommended product is backed by the advice; check labels on alternatives."}
