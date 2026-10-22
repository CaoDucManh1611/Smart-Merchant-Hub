"""Install a trusted local Data_RAG training run for explicitly opted-in demo tenants."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import shutil
import joblib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-run", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "backend" / "artifacts" / "data_rag")
    parser.add_argument("--dataset", type=Path, help="Optional dataset directory; otherwise inferred from the training run")
    args = parser.parse_args()
    source = args.training_run.resolve()
    report = json.loads((source / "training_report.json").read_text(encoding="utf-8"))
    if report.get("status") != "completed" or report["dataset"].get("evaluation_truth_opened_or_used") is not False:
        parser.error("Only a completed, leakage-checked local training run is supported.")
    names = ("product_choice_ranker.joblib", "rfm_kmeans.joblib")
    for name in names:
        if not (source / name).is_file():
            parser.error(f"Missing checkpoint: {name}")
    args.output.mkdir(parents=True, exist_ok=True)
    for name in (*names, "training_report.json"):
        shutil.copy2(source / name, args.output / name)
    portable = []
    for name in names:
        checkpoint = joblib.load(source / name)
        pipeline = checkpoint["pipeline"]
        scaler = pipeline.named_steps["scale"]
        model = pipeline.steps[-1][1]
        values = {"features": checkpoint["features"], "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist()}
        if name.startswith("product"):
            if model.classes_.tolist() != [0, 1] or len(model.coef_) != 1:
                parser.error("Only a binary product-choice logistic model is supported.")
            values.update(weights=model.coef_[0].tolist(), intercept=float(model.intercept_[0]))
        else:
            values.update(centers=model.cluster_centers_.tolist())
        target = name.replace(".joblib", ".json")
        (args.output / target).write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
        portable.append(target)
    dataset = args.dataset or source.parent.parent / "dataset"
    with (dataset / "products.csv").open(encoding="utf-8-sig", newline="") as stream:
        catalog = list(csv.DictReader(stream))
    (args.output / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "model_version": "data_rag_demo_v1", "data_provenance": "synthetic_data_rag",
        "training_run": source.name, "training_time": report["created_at_local"],
        "sha256": {name: hashlib.sha256((args.output / name).read_bytes()).hexdigest() for name in (*names, *portable, "catalog.json")},
        "scope": "demo tenant allowlist only; ranking choice scores are not purchase probabilities",
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

