"""Register trained artifacts + evaluation in the application database (run from backend/ dir).

  cd backend && python ../ml/evaluation/register_model.py --artifacts ../ml/artifacts --activate
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from sqlalchemy import select  # noqa: E402

from app.db.base import utcnow  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import ModelEvaluation, ModelVersion  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", default="../ml/artifacts")
    ap.add_argument("--activate", action="store_true")
    a = ap.parse_args()
    d = Path(a.artifacts)
    card, metrics = json.loads((d / "model_card.json").read_text()), json.loads((d / "metrics.json").read_text())
    if not card.get("trained"):
        raise SystemExit("Model card is not marked trained")
    with SessionLocal() as db:
        mv = db.scalar(select(ModelVersion).where(ModelVersion.name == card["name"], ModelVersion.version == card["version"])) \
            or ModelVersion(name=card["name"], version=card["version"])
        mv.architecture, mv.classes, mv.is_trained = card["architecture"], json.loads((d / "labels.json").read_text()), True
        mv.artifact_path = str(d); mv.dataset_note = card.get("limitations", "")
        if a.activate:
            for o in db.scalars(select(ModelVersion).where(ModelVersion.is_active == True)):  # noqa: E712
                o.is_active = False
            mv.is_active = True
        db.add(mv); db.flush()
        db.add(ModelEvaluation(model_version_id=mv.id, test_accuracy=metrics["test_accuracy"],
                               metrics={"report": metrics["report"], "confusion_matrix": metrics["confusion_matrix"], "classes": metrics["classes"]},
                               created_at=utcnow()))
        db.commit()
        print("Registered", mv.name, mv.version, "test_acc=", metrics["test_accuracy"])


if __name__ == "__main__":
    main()
