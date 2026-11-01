from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.llm.router import LLMRouter, get_router
from app.ai.rag.pipeline import answer_question
from app.api.deps import require
from app.api.v1.auth import rate_limit
from app.db.base import utcnow
from app.db.session import get_db
from app.models import AdvisoryConversation, AdvisoryMessage, CropDiagnosis, LLMCallLog, User

router = APIRouter(prefix="/advisory", tags=["advisory"])
ai_user = require("ai.use")

SUGGESTED = {"en": ["How do I recognise early blight in tomato?", "When should I take a soil sample?",
                    "What are non-chemical ways to reduce pest pressure?"],
             "mr": ["टोमॅटोमधील करपा रोग कसा ओळखायचा?", "मातीचा नमुना कधी घ्यावा?", "कीड कमी करण्याचे रासायनिक नसलेले उपाय कोणते?"]}


def msg_out(m: AdvisoryMessage) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, "citations": m.citations or [], "grounded": m.grounded,
            "provider": m.provider, "feedback": m.feedback, "at": m.created_at.isoformat()}


def conv_out(c: AdvisoryConversation, with_messages: bool = False) -> dict:
    d = {"id": c.id, "title": c.title, "diagnosis_id": c.diagnosis_id, "updated_at": c.updated_at.isoformat(), "is_demo": c.is_demo}
    if with_messages:
        d["messages"] = [msg_out(m) for m in c.messages]
    return d


def _own(db: Session, user: User, cid: int) -> AdvisoryConversation:
    c = db.get(AdvisoryConversation, cid)
    if not c or c.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    return c


class NewConv(BaseModel):
    diagnosis_id: int | None = None


class Ask(BaseModel):
    message: str = Field(min_length=2, max_length=1500)


class Fb(BaseModel):
    value: int = Field(ge=-1, le=1)


@router.get("/suggestions")
def suggestions(lang: str = "en", user: User = Depends(ai_user)):
    return SUGGESTED.get(lang, SUGGESTED["en"])


@router.get("/conversations")
def conversations(user: User = Depends(ai_user), db: Session = Depends(get_db)):
    return [conv_out(c) for c in db.scalars(select(AdvisoryConversation).where(AdvisoryConversation.user_id == user.id)
                                           .order_by(AdvisoryConversation.updated_at.desc()))]


@router.post("/conversations", status_code=201)
def new_conversation(body: NewConv, user: User = Depends(ai_user), db: Session = Depends(get_db)):
    if body.diagnosis_id:
        d = db.get(CropDiagnosis, body.diagnosis_id)
        if not d or d.user_id != user.id:
            raise HTTPException(404, "Diagnosis not found")
    c = AdvisoryConversation(user_id=user.id, diagnosis_id=body.diagnosis_id, is_demo=user.is_demo)
    db.add(c)
    db.commit()
    return conv_out(c, True)


@router.get("/conversations/{cid}")
def get_conversation(cid: int, user: User = Depends(ai_user), db: Session = Depends(get_db)):
    return conv_out(_own(db, user, cid), True)


@router.post("/conversations/{cid}/messages")
def ask(cid: int, body: Ask, user: User = Depends(ai_user), db: Session = Depends(get_db),
        llm: LLMRouter = Depends(get_router)):
    rate_limit(f"chat:{user.id}", 20)
    c = _own(db, user, cid)
    history = [{"role": m.role, "content": m.content} for m in c.messages]
    notes = ""
    if c.diagnosis_id:
        d = db.get(CropDiagnosis, c.diagnosis_id)
        if d and d.user_id == user.id:
            top = d.predictions[0].class_label if d.predictions and d.status.value == "PREDICTED" else "none (no confident image prediction)"
            notes = f"crop={d.crop}; stage={d.crop_stage}; reported symptoms={d.symptoms}; image-model top class={top}"
    now = utcnow()
    c.messages.append(AdvisoryMessage(role="user", content=body.message, created_at=now))
    if c.title == "New conversation":
        c.title = body.message[:60]
    ans = answer_question(body.message, history, llm, notes)
    for a in ans.attempts:
        if a["error_kind"] not in ("not_configured", "cooldown"):
            db.add(LLMCallLog(provider=a["provider"], ok=a["ok"], latency_ms=a["latency_ms"], error_kind=a["error_kind"], created_at=utcnow()))
    m = AdvisoryMessage(role="assistant", content=ans.text, citations=ans.citations, provider=ans.provider,
                        latency_ms=ans.latency_ms, grounded=ans.grounded, created_at=utcnow())
    c.messages.append(m)
    c.updated_at = utcnow()
    db.commit()
    return msg_out(m)


@router.post("/messages/{mid}/feedback")
def feedback(mid: int, body: Fb, user: User = Depends(ai_user), db: Session = Depends(get_db)):
    m = db.get(AdvisoryMessage, mid)
    if not m or m.role != "assistant" or _own(db, user, m.conversation_id) is None:
        raise HTTPException(404, "Message not found")
    m.feedback = body.value
    db.commit()
    return {"ok": True}
