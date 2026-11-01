"""Genuine PyTorch inference. Returns an explicit 'unavailable' state if no trained model exists."""
import io
import json
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings

IMG_SIZE = 224
MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)


@dataclass
class Prediction:
    available: bool
    reason: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    top: list[tuple[str, float]] | None = None   # raw softmax outputs; NOT calibrated diagnosis probabilities
    uncertain: bool = False


class CropClassifier:
    def __init__(self, artifact_dir: str | None = None):
        self.dir = Path(artifact_dir or get_settings().model_artifact_dir)
        self._model = None
        self._labels: list[str] | None = None
        self.card: dict | None = None

    # -- artifact guard --
    def status(self) -> dict:
        card = self.dir / "model_card.json"
        if not (self.dir / "model.pt").exists() or not (self.dir / "labels.json").exists() or not card.exists():
            return {"available": False, "reason": "No trained model artifacts found. Run ml/training/train.py first."}
        info = json.loads(card.read_text())
        if not info.get("trained") or info.get("test_accuracy") is None:
            return {"available": False, "reason": "Model card says the model is untrained or unevaluated."}
        return {"available": True, "card": info}

    def _load(self):
        if self._model is not None:
            return
        import torch
        import torchvision
        st = self.status()
        self.card = st["card"]
        self._labels = json.loads((self.dir / "labels.json").read_text())
        m = torchvision.models.mobilenet_v3_small(weights=None)
        m.classifier[3] = torch.nn.Linear(m.classifier[3].in_features, len(self._labels))
        m.load_state_dict(torch.load(self.dir / "model.pt", map_location="cpu"))
        m.eval()
        self._model = m

    def predict(self, image_bytes: bytes, top_k: int = 3) -> Prediction:
        st = self.status()
        if not st["available"]:
            return Prediction(False, st["reason"])
        try:
            import torch
            from PIL import Image
            from torchvision import transforms
        except ImportError:
            return Prediction(False, "PyTorch is not installed on this server (pip install -r requirements-ml.txt).")
        self._load()
        tf = transforms.Compose([transforms.Resize((IMG_SIZE, IMG_SIZE)), transforms.ToTensor(),
                                 transforms.Normalize(MEAN, STD)])
        x = tf(Image.open(io.BytesIO(image_bytes)).convert("RGB")).unsqueeze(0)
        with torch.no_grad():
            probs = torch.softmax(self._model(x), dim=1)[0]
        vals, idx = probs.topk(min(top_k, len(self._labels)))
        top = [(self._labels[i], float(v)) for v, i in zip(vals, idx)]
        thr = get_settings().min_confidence_for_display
        return Prediction(True, None, self.card.get("name"), self.card.get("version"), top, uncertain=top[0][1] < thr)


_clf: CropClassifier | None = None


def get_classifier() -> CropClassifier:
    global _clf
    if _clf is None:
        _clf = CropClassifier()
    return _clf


def set_classifier(c: CropClassifier | None) -> None:
    global _clf
    _clf = c
