"""Own-account management: profile, documents, privacy, notification preferences, deletion request."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.v1.auth import user_out
from app.core.audit import audit
from app.core.config import get_settings
from app.core.storage import document_storage, media_storage
from app.db.session import get_db
from app.models import DeletionRequest, DocStatusV, User, UserDocument
from app.services.accounts import norm_mobile

router = APIRouter(prefix="/account", tags=["account"])

DOC_TYPES = {"AADHAAR", "PAN", "GST", "SHOP_LICENCE", "DRIVING_LICENCE", "VEHICLE_RC", "CERTIFICATE", "LAB_ACCREDITATION", "OTHER"}
DOC_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}
PHOTO_MIME = {"image/jpeg": ".jpg", "image/png": ".png"}


class ProfileIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    language: str | None = Field(default=None, pattern="^(en|hi|mr)$")
    email: str | None = None
    mobile: str | None = None


@router.get("/profile")
def get_profile(user: User = Depends(get_current_user)):
    return {**user_out(user), "privacy": user.privacy, "notif_prefs": user.notif_prefs}


@router.patch("/profile")
def update_profile(body: ProfileIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.full_name:
        user.full_name = body.full_name.strip()
    if body.language:
        user.language = body.language
    # changing a contact needs re-verification, so it is not done in this call
    if body.email or body.mobile:
        raise HTTPException(400, "Contact changes need verification; contact support to change email or mobile")
    db.commit()
    return user_out(user)


@router.post("/photo")
async def upload_photo(file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ext = PHOTO_MIME.get(file.content_type or "")
    if not ext:
        raise HTTPException(415, "Photo must be JPG or PNG")
    data = await file.read(get_settings().max_upload_mb * 1024 * 1024 + 1)
    if len(data) > get_settings().max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "File too large")
    user.photo_key = media_storage().save(data, ext)
    db.commit()
    return {"ok": True}


@router.get("/photo/{user_id}")
def get_photo(user_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u or not u.photo_key:
        raise HTTPException(404, "No photo")
    mime = "image/png" if u.photo_key.endswith(".png") else "image/jpeg"
    return Response(media_storage().read(u.photo_key), media_type=mime, headers={"Cache-Control": "private, max-age=300"})


# ---------------- documents (verification) ----------------
@router.get("/documents")
def list_documents(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(UserDocument).where(UserDocument.user_id == user.id).order_by(UserDocument.id.desc()))
    return [{"id": d.id, "doc_type": d.doc_type, "name": d.original_name, "status": d.status.value, "note": d.review_note,
             "uploaded_at": d.created_at.isoformat()} for d in rows]


@router.post("/documents", status_code=201)
async def upload_document(doc_type: str = Form(...), file: UploadFile = File(...),
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    doc_type = doc_type.upper()
    if doc_type not in DOC_TYPES:
        raise HTTPException(422, f"doc_type must be one of {sorted(DOC_TYPES)}")
    ext = DOC_MIME.get(file.content_type or "")
    if not ext:
        raise HTTPException(415, "Upload a JPG, PNG or PDF")
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, "File too large")
    if db.scalar(select(UserDocument.id).where(UserDocument.user_id == user.id).limit(21) .offset(20)):
        raise HTTPException(429, "Too many documents uploaded")
    key = document_storage().save(data, ext)
    d = UserDocument(user_id=user.id, doc_type=doc_type, original_name=(file.filename or "document")[:200], storage_key=key,
                     content_type=file.content_type or "", status=DocStatusV.PENDING)
    db.add(d)
    audit(db, user.id, "document.upload", "user_document", None, {"type": doc_type})
    db.commit()
    return {"id": d.id, "status": d.status.value}


@router.get("/documents/{doc_id}/file")
def own_document_file(doc_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = db.get(UserDocument, doc_id)
    if not d or d.user_id != user.id:
        raise HTTPException(404, "Document not found")
    return Response(document_storage().read(d.storage_key), media_type=d.content_type,
                    headers={"Cache-Control": "no-store", "Content-Disposition": "attachment"})


# ---------------- privacy / notification preferences ----------------
class PrivacyIn(BaseModel):
    community_profile_public: bool | None = None
    share_with_experts: bool | None = None


@router.put("/privacy")
def set_privacy(body: PrivacyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.privacy = {**(user.privacy or {}), **body.model_dump(exclude_none=True)}
    db.commit()
    return user.privacy


class PrefsIn(BaseModel):
    in_app: bool | None = None
    sms: bool | None = None
    email: bool | None = None
    push: bool | None = None
    muted_kinds: list[str] | None = Field(default=None, max_length=30)


@router.put("/notification-prefs")
def set_prefs(body: PrefsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.notif_prefs = {**(user.notif_prefs or {}), **body.model_dump(exclude_none=True)}
    db.commit()
    return user.notif_prefs


# ---------------- deletion request ----------------
class DeleteIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


@router.post("/deletion-request", status_code=201)
def request_deletion(body: DeleteIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if db.scalar(select(DeletionRequest.id).where(DeletionRequest.user_id == user.id, DeletionRequest.status == "PENDING")):
        raise HTTPException(409, "A deletion request is already pending")
    db.add(DeletionRequest(user_id=user.id, reason=body.reason))
    audit(db, user.id, "account.deletion_requested", "user", user.id)
    db.commit()
    return {"ok": True, "message": "Request received. Orders and payment records are retained as required by law; personal details are removed on approval."}
