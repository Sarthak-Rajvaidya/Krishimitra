"""Explainable recommendation engine. Deliberately independent of sales logic:
ordering never uses price, margin or stock; candidates are only 'included' when verified label
metadata AND retrieved evidence support them. Everything else is returned as excluded WITH a reason."""
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.rag.pipeline import Retrieved, retrieve
from app.api.v1.common import stock_map
from app.db.base import utcnow
from app.models import CropDiagnosis, DiagnosisStatus, Product, ProductType, Recommendation

NUTRIENT_WORDS = ("deficien", "yellowing", "chlorosis", "interveinal", "stunted", "purple", "necrotic edge")


@dataclass
class Case:
    crop: str | None
    issue: str | None
    healthy: bool
    symptoms: str
    stage: str | None
    status: DiagnosisStatus | None


def parse_label(label: str) -> tuple[str | None, str | None, bool]:
    parts = [p.replace("_", " ").strip() for p in re.split(r"_{2,}|___", label) if p.strip()]
    crop = parts[0] if parts else None
    issue = parts[1] if len(parts) > 1 else None
    return crop, issue, bool(issue and "healthy" in issue.lower())


def build_case(d: CropDiagnosis) -> Case:
    crop, issue, healthy = (d.crop, None, False)
    if d.predictions and d.status == DiagnosisStatus.PREDICTED:
        pc, issue, healthy = parse_label(d.predictions[0].class_label)
        crop = d.crop or pc
    return Case(crop, issue, healthy, d.symptoms or "", d.crop_stage, d.status)


def _terms(*vals) -> list[str]:
    return [v.lower() for v in vals if v]


def _cite(p: Retrieved) -> dict:
    return {"n": p.n, "title": p.title, "page": p.page, "section": p.section, "document_id": p.document_id,
            "excerpt": p.text[:240]}


def recommend(db: Session, user_id: int, d: CropDiagnosis, conversation_id: int | None = None) -> dict:
    case = build_case(d)
    questions: list[str] = []
    notes: list[str] = []
    if case.status == DiagnosisStatus.MODEL_UNAVAILABLE:
        notes.append("No trained image model was available, so there is no image-based assessment. Only your reported symptoms are used.")
    if case.status == DiagnosisStatus.LOW_CONFIDENCE:
        notes.append("The image model was uncertain; treat any suggestion as a lead to confirm, not a diagnosis.")
    if not case.crop:
        questions.append("Which crop is this?")
    if not case.stage:
        questions.append("What growth stage is the crop at?")
    nutrient = any(w in case.symptoms.lower() for w in NUTRIENT_WORDS)
    if nutrient:
        questions.append("Do you have a recent soil test report? Nutrient deficiency cannot be confirmed from a leaf photo alone.")

    passages: list[Retrieved] = []
    if case.healthy:
        notes.append("The model's top class is a healthy leaf. No treatment product is suggested.")
    else:
        q = " ".join(x for x in (case.crop, case.issue, case.symptoms[:200], "management") if x)
        try:
            passages = retrieve(q) if q.strip() else []
        except Exception:
            passages = []
            notes.append("The knowledge base was unavailable, so no product could be supported by evidence.")
    if not passages and not case.healthy:
        notes.append("No verified evidence was found in the knowledge base for this case, so no product can be supported. "
                     "Please consult a qualified agronomist.")

    candidates: list[Product] = []
    if not case.healthy:
        terms = _terms(case.crop, case.issue)
        for p in db.scalars(select(Product).where(Product.is_active == True, Product.deleted_at.is_(None))).unique():  # noqa: E712
            hay = " ".join([p.name, p.crops, p.use_tags, p.description, (p.label.label_targets or "") if p.label else "",
                            (p.label.label_crops or "") if p.label else ""]).lower()
            if any(t and t in hay for t in terms) or (nutrient and p.product_type == ProductType.MICRONUTRIENT):
                candidates.append(p)
    stocks = stock_map(db, [p.id for p in candidates])

    out, rows = [], []
    for p in sorted(candidates, key=lambda x: x.name):  # alphabetical: no commercial ordering
        lab = p.label
        label_ok = bool(lab and lab.verified)
        crop_ok = bool(label_ok and case.crop and case.crop.lower() in (lab.label_crops or "").lower())
        target_ok = bool(label_ok and case.issue and case.issue.lower() in (lab.label_targets or "").lower())
        is_nutrient_product = p.product_type == ProductType.MICRONUTRIENT or p.product_type == ProductType.FERTILIZER
        reason, included = None, False
        if not label_ok:
            reason = "Product label information has not been verified, so applicability to this crop and issue cannot be confirmed."
        elif is_nutrient_product and nutrient:
            reason = "Nutrient products are not suggested from symptoms or a photo alone; a soil/tissue test is needed first."
        elif not crop_ok:
            reason = f"The verified label does not list {case.crop or 'this crop'}."
        elif not target_ok and not is_nutrient_product:
            reason = f"The verified label does not list '{case.issue or 'this issue'}' as a target."
        elif not passages:
            reason = "No retrieved source supports using this product for this case."
        else:
            included = True
        item = {
            "product_id": p.id, "name": p.name, "product_type": p.product_type.value,
            "purpose": f"{case.issue or 'Symptoms reported'} on {case.crop or 'crop'}",
            "included": included,
            "why_considered": "Catalogue metadata matches the crop, issue or symptoms." + (" Demo catalogue entry." if p.is_demo else ""),
            "exclusion_reason": reason,
            "evidence": [_cite(x) for x in passages[:3]] if included else [],
            "uncertainty": "Based on an AI image classifier and retrieved documents; confirm with an agronomist before purchase or application."
                           if included else None,
            "label_restrictions": (lab.restrictions if lab else None) or "No verified label restrictions on file. Read the product label before use.",
            "pack": {"pack_size": p.pack_size, "price_paise": p.price_paise, "in_stock": stocks.get(p.id, 0) > 0},
            "requires_expert": True,  # always: this is decision support, never a prescription
            "dose_info": "Not provided here. Follow the verified product label or agronomist advice.",
        }
        out.append(item)
        rec = Recommendation(user_id=user_id, diagnosis_id=d.id, conversation_id=conversation_id, product_id=p.id,
                             purpose=item["purpose"][:200], included=included, reasoning=item, requires_expert=True,
                             created_at=utcnow())
        db.add(rec)
        rows.append((item, rec))
    db.commit()
    for item, rec in rows:
        item["recommendation_id"] = rec.id
    return {"diagnosis_id": d.id, "case": {"crop": case.crop, "suspected_issue": case.issue, "stage": case.stage},
            "notes": notes, "follow_up_questions": questions,
            "supporting_passages": [_cite(p) for p in passages],
            "candidates": sorted(out, key=lambda i: (not i["included"], i["name"])),
            "disclaimer": "These are decision-support options, not a prescription. No doses are given. Confirm with a qualified agronomist."}
