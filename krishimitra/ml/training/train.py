"""Transfer-learning trainer (MobileNetV3-small) with leakage-aware stratified splits and full evaluation.

  python ml/training/train.py --data-dir ml/data/raw/plantvillage --epochs 8 --version 0.1.0

Outputs in ml/artifacts/: model.pt (state_dict), labels.json, model_card.json, metrics.json, config.json
NOTE on leakage: PlantVillage contains augmented copies of the same leaf photographed once. A random image-level
split can leak near-duplicates across train/test and inflate accuracy. If your copy exposes a source-image id in
the filename, pass --group-regex (first capture group = group id) so groups never straddle splits.
Reported accuracy is on lab-style images and will NOT match field photos.
"""
import argparse
import json
import random
import re
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import torchvision
from sklearn.metrics import classification_report, confusion_matrix
from torch import nn
from torch.utils.data import DataLoader, Subset
from torchvision import datasets, transforms

MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)


def seed_all(seed: int) -> None:
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)


def grouped_stratified_split(ds, seed: int, group_regex: str | None, val=0.15, test=0.15):
    rng = random.Random(seed)
    by_class: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    rx = re.compile(group_regex) if group_regex else None
    for i, (path, y) in enumerate(ds.samples):
        name = Path(path).stem
        g = (rx.search(name).group(1) if rx and rx.search(name) else str(i))
        by_class[y][g].append(i)
    tr, va, te = [], [], []
    for y, groups in by_class.items():
        keys = sorted(groups); rng.shuffle(keys)
        n = len(keys); n_te, n_va = max(1, int(n * test)), max(1, int(n * val))
        for j, k in enumerate(keys):
            (te if j < n_te else va if j < n_te + n_va else tr).extend(groups[k])
    return tr, va, te


def evaluate(model, loader, device, classes):
    model.eval(); ys, ps = [], []
    with torch.no_grad():
        for x, y in loader:
            ps += model(x.to(device)).argmax(1).cpu().tolist(); ys += y.tolist()
    rep = classification_report(ys, ps, labels=list(range(len(classes))), target_names=classes, output_dict=True, zero_division=0)
    cm = confusion_matrix(ys, ps, labels=list(range(len(classes)))).tolist()
    return float(np.mean(np.array(ys) == np.array(ps))), rep, cm


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out", default="ml/artifacts")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--group-regex", default=None)
    ap.add_argument("--num-workers", type=int, default=2)
    a = ap.parse_args()
    notes = Path(a.data_dir).parent / "DATASET_NOTES.md"
    if not notes.exists():
        raise SystemExit(f"Create {notes} recording the dataset source, licence and attribution before training.")
    seed_all(a.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    train_tf = transforms.Compose([transforms.RandomResizedCrop(224, scale=(0.7, 1)), transforms.RandomHorizontalFlip(),
                                   transforms.ColorJitter(0.2, 0.2, 0.2), transforms.ToTensor(), transforms.Normalize(MEAN, STD)])
    eval_tf = transforms.Compose([transforms.Resize((224, 224)), transforms.ToTensor(), transforms.Normalize(MEAN, STD)])
    base_train = datasets.ImageFolder(a.data_dir, transform=train_tf)
    base_eval = datasets.ImageFolder(a.data_dir, transform=eval_tf)
    classes = base_train.classes
    tr, va, te = grouped_stratified_split(base_train, a.seed, a.group_regex)
    assert not (set(tr) & set(va) | set(tr) & set(te) | set(va) & set(te)), "split leakage"
    mk = lambda ds, idx, sh: DataLoader(Subset(ds, idx), batch_size=a.batch_size, shuffle=sh, num_workers=a.num_workers)  # noqa: E731
    tl, vl, tel = mk(base_train, tr, True), mk(base_eval, va, False), mk(base_eval, te, False)

    model = torchvision.models.mobilenet_v3_small(weights=torchvision.models.MobileNet_V3_Small_Weights.IMAGENET1K_V1)
    for p in model.features.parameters():
        p.requires_grad = False
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, len(classes))
    model.to(device)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    best, best_state = -1.0, None
    for epoch in range(a.epochs):
        if epoch == max(1, a.epochs // 2):                       # unfreeze for fine-tuning
            for p in model.features.parameters():
                p.requires_grad = True
        opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr if epoch < a.epochs // 2 else a.lr / 10)
        model.train()
        for x, y in tl:
            opt.zero_grad(); loss = nn.functional.cross_entropy(model(x.to(device)), y.to(device)); loss.backward(); opt.step()
        acc, _, _ = evaluate(model, vl, device, classes)
        print(f"epoch {epoch + 1}/{a.epochs} val_acc={acc:.4f}")
        if acc > best:
            best, best_state = acc, {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            torch.save(best_state, out / "checkpoint_best.pt")
    model.load_state_dict(best_state)
    test_acc, report, cm = evaluate(model, tel, device, classes)
    torch.save(best_state, out / "model.pt")
    (out / "labels.json").write_text(json.dumps(classes, indent=2))
    (out / "metrics.json").write_text(json.dumps({"test_accuracy": test_acc, "report": report, "confusion_matrix": cm, "classes": classes,
                                                  "split_sizes": {"train": len(tr), "val": len(va), "test": len(te)}}, indent=2))
    (out / "config.json").write_text(json.dumps(vars(a) | {"device": device}, indent=2))
    (out / "model_card.json").write_text(json.dumps({
        "name": "crop-doctor", "version": a.version, "architecture": "mobilenet_v3_small", "trained": True,
        "test_accuracy": test_acc, "val_accuracy": best, "classes": len(classes), "trained_at": time.strftime("%Y-%m-%d"),
        "dataset_notes_file": str(notes),
        "limitations": "Trained on lab-style PlantVillage images; field accuracy is unknown. Raw softmax scores are not calibrated."}, indent=2))
    print(f"TEST accuracy: {test_acc:.4f}  (n={len(te)})")


if __name__ == "__main__":
    main()
