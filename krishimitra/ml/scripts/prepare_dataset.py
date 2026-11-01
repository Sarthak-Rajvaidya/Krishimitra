"""Prepare an ImageFolder dataset from Hugging Face. NOT run at backend startup.

BEFORE USING: open the dataset card, read the licence and attribution requirements, and record them in
ml/data/DATASET_NOTES.md (the training script refuses to run without that file).

Usage:
  python ml/scripts/prepare_dataset.py --hf-id <owner/dataset> --out ml/data/raw/plantvillage \
      --classes "Tomato___Early_blight,Tomato___Late_blight,Tomato___healthy" --max-per-class 600
Class names come from the dataset's own ClassLabel feature, so check them against the card first.
"""
import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf-id", required=True)
    ap.add_argument("--split", default="train")
    ap.add_argument("--out", required=True)
    ap.add_argument("--classes", default="", help="comma-separated subset; empty = all")
    ap.add_argument("--max-per-class", type=int, default=0)
    a = ap.parse_args()
    from datasets import load_dataset
    ds = load_dataset(a.hf_id, split=a.split)
    label_feat = next((k for k, v in ds.features.items() if v.__class__.__name__ == "ClassLabel"), None)
    img_feat = next((k for k, v in ds.features.items() if v.__class__.__name__ == "Image"), None)
    if not label_feat or not img_feat:
        raise SystemExit(f"Could not find Image/ClassLabel features in {list(ds.features)}")
    names = ds.features[label_feat].names
    wanted = {c.strip() for c in a.classes.split(",") if c.strip()} or set(names)
    unknown = wanted - set(names)
    if unknown:
        raise SystemExit(f"Unknown classes: {sorted(unknown)}\nAvailable: {names}")
    out = Path(a.out)
    counts = {n: 0 for n in wanted}
    for i, row in enumerate(ds):
        name = names[row[label_feat]]
        if name not in wanted or (a.max_per_class and counts[name] >= a.max_per_class):
            continue
        d = out / name
        d.mkdir(parents=True, exist_ok=True)
        row[img_feat].convert("RGB").save(d / f"{counts[name]:05d}.jpg", quality=92)
        counts[name] += 1
    print("Saved:", counts)


if __name__ == "__main__":
    main()
