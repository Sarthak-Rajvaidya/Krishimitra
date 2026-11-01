"""Developer/ops endpoints: health, models, flags, knowledge management, sanitized logs."""
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.ai.crop_doctor.inference import get_classifier
from app.ai.llm.router import get_router
from app.ai.rag.pipeline import ingest_document, retrieve
from app.ai.rag.store import get_store
from app.api.deps import require
from app.api.v1.common import page_args
from app.core.audit import audit
from app.core.config import get_settings
from app.core.storage import knowledge_storage
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (DocStatus, ErrorLog, FeatureFlag, IngestionJob, KnowledgeDocument, LLMCallLog, ModelEvaluation,
                        ModelVersion, User)

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok", "brand": get_settings().brand_name}


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    t0 = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"ready": db_ok, "database": {"ok": db_ok, "latency_ms": int((time.perf_counter() - t0) * 1000)}}


sysview = require("system.view")


@router.get("/system/overview")
def overview(user: User = Depends(sysview), db: Session = Depends(get_db)):
    t0 = time.perf_counter()
    db.execute(text("SELECT 1"))
    db_ms = int((time.perf_counter() - t0) * 1000)
    try:
        vec = get_store().health()
    except Exception as ex:
        vec = {"ok": False, "error": type(ex).__name__}
    docs = {s.value: c for s, c in db.execute(select(KnowledgeDocument.status, func.count()).group_by(KnowledgeDocument.status))}
    return {"api": {"ok": True}, "database": {"ok": True, "latency_ms": db_ms}, "vector_db": vec,
            "llm_providers": get_router().status(), "crop_model": get_classifier().status() | {"card": None},
            "knowledge_documents": docs, "environment": get_settings().app_env}


@router.get("/system/llm-stats")
def llm_stats(user: User = Depends(sysview), db: Session = Depends(get_db)):
    rows = db.execute(select(LLMCallLog.provider, func.count(), func.sum(LLMCallLog.ok), func.avg(LLMCallLog.latency_ms))
                      .group_by(LLMCallLog.provider)).all()
    return [{"provider": p, "calls": c, "ok": int(o or 0), "avg_latency_ms": round(float(a or 0))} for p, c, o, a in rows]


@router.get("/system/models")
def models(user: User = Depends(sysview), db: Session = Depends(get_db)):
    out = []
    for m in db.scalars(select(ModelVersion).order_by(ModelVersion.id.desc())):
        ev = db.scalar(select(ModelEvaluation).where(ModelEvaluation.model_version_id == m.id).order_by(ModelEvaluation.id.desc()))
        out.append({"id": m.id, "name": m.name, "version": m.version, "architecture": m.architecture, "is_active": m.is_active,
                    "is_trained": m.is_trained, "classes": m.classes, "dataset_note": m.dataset_note,
                    "last_evaluation": {"test_accuracy": ev.test_accuracy, "metrics": ev.metrics, "at": ev.created_at.isoformat()} if ev else None})
    return out


@router.post("/system/models/{mid}/activate")
def activate_model(mid: int, user: User = Depends(require("system.configure")), db: Session = Depends(get_db)):
    m = db.get(ModelVersion, mid)
    if not m:
        raise HTTPException(404, "Model not found")
    if not m.is_trained:
        raise HTTPException(409, "Cannot activate an untrained or unevaluated model")
    for o in db.scalars(select(ModelVersion).where(ModelVersion.is_active == True)):  # noqa: E712
        o.is_active = False
    m.is_active = True
    audit(db, user.id, "model.activate", "model", mid)
    db.commit()
    return {"ok": True}


class FlagIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_.-]{3,80}$")
    description: str = ""
    enabled: bool


@router.get("/system/flags")
def flags(user: User = Depends(sysview), db: Session = Depends(get_db)):
    return [{"key": f.key, "description": f.description, "enabled": f.enabled, "updated_by": f.updated_by,
             "updated_at": f.updated_at.isoformat()} for f in db.scalars(select(FeatureFlag).order_by(FeatureFlag.key))]


@router.put("/system/flags")
def set_flag(body: FlagIn, user: User = Depends(require("system.configure")), db: Session = Depends(get_db)):
    f = db.scalar(select(FeatureFlag).where(FeatureFlag.key == body.key))
    before = f.enabled if f else None
    if not f:
        f = FeatureFlag(key=body.key)
        db.add(f)
    f.enabled, f.description, f.updated_by = body.enabled, body.description or f.description or "", user.id
    audit(db, user.id, "flag.set", "feature_flag", body.key, {"before": before, "after": body.enabled})
    db.commit()
    return {"ok": True}


@router.get("/system/error-logs")
def error_logs(user: User = Depends(sysview), db: Session = Depends(get_db)):
    return [{"path": e.path, "status": e.status_code, "message": e.message, "at": e.created_at.isoformat()}
            for e in db.scalars(select(ErrorLog).order_by(ErrorLog.id.desc()).limit(100))]


# ---- knowledge base ----
@router.get("/knowledge/documents")
def docs(user: User = Depends(require("knowledge.view")), db: Session = Depends(get_db)):
    return [{"id": d.id, "title": d.title, "source_org": d.source_org, "source_url": d.source_url, "licence": d.licence,
             "authorized_by": d.authorized_by, "file_type": d.file_type, "status": d.status.value, "chunks": d.chunk_count,
             "is_demo": d.is_demo} for d in db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.id.desc()))]


@router.get("/knowledge/jobs")
def jobs(user: User = Depends(require("knowledge.view")), db: Session = Depends(get_db)):
    return [{"id": j.id, "document_id": j.document_id, "status": j.status.value, "error": j.error,
             "started_at": j.started_at.isoformat() if j.started_at else None} for j in
            db.scalars(select(IngestionJob).order_by(IngestionJob.id.desc()).limit(100))]


@router.post("/knowledge/documents", status_code=201)
async def upload_doc(file: UploadFile = File(...), title: str = Form(..., max_length=255), source_org: str = Form(..., max_length=160),
                     licence: str = Form(..., min_length=2, max_length=160), authorized_by: str = Form(..., min_length=2, max_length=160),
                     source_url: str | None = Form(None, max_length=500), language: str = Form("en", max_length=5),
                     user: User = Depends(require("knowledge.manage")), db: Session = Depends(get_db)):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    data = await file.read(25 * 1024 * 1024)
    key = knowledge_storage().save(data, ext if ext in ("pdf", "txt", "md") else "bin")
    doc = KnowledgeDocument(title=title, source_org=source_org, source_url=source_url, licence=licence,
                            authorized_by=authorized_by, storage_key=key, file_type=ext, language=language)
    db.add(doc)
    db.flush()
    audit(db, user.id, "knowledge.upload", "document", doc.id, {"title": title, "licence": licence})
    job = ingest_document(db, doc, data, user.id)
    return {"document_id": doc.id, "status": job.status.value, "error": job.error}


class RetrievalTest(BaseModel):
    query: str = Field(min_length=2, max_length=500)


@router.post("/knowledge/retrieval-test")
def retrieval_test(body: RetrievalTest, user: User = Depends(require("knowledge.view"))):
    return [{"n": p.n, "score": p.score, "title": p.title, "page": p.page, "section": p.section, "excerpt": p.text[:300]}
            for p in retrieve(body.query)]
