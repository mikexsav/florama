"""Валидация по непересекающимся полям без загрузки приватных ответов."""

import argparse
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from reconstruction import build_features, masked
from source_model import extended_features, fit_bundle, predict_bundle, baselines


def examples(frame, seed):
    valid = frame.primary_ndvi.between(-1, 1).to_numpy()
    mask = valid & (np.random.default_rng(seed).random(len(frame)) < 0.15)
    clean = masked(frame, mask)
    base = build_features(clean)
    features = extended_features(clean, base).loc[mask].reset_index(drop=True)
    original = frame.loc[mask]
    target = original.primary_ndvi.to_numpy(float)
    source = np.where(
        original.s2_ndvi.notna(), 0, np.where(original.landsat_ndvi.notna(), 1, 2)
    )
    return features, target, source


def score(y, p):
    return {
        "rmse": float(np.sqrt(np.mean((y - p) ** 2))),
        "mae": float(np.mean(np.abs(y - p))),
        "n": len(y),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    frame = pd.read_csv(args.input)
    ids = np.random.default_rng(20260905).permutation(
        sorted(frame.anon_polygon_id.unique())
    )
    folds = np.array_split(ids, 4)
    reports = {}
    pooled = {}
    truths = []
    for fold, holdout in enumerate(folds):
        train = frame.loc[~frame.anon_polygon_id.isin(holdout)].reset_index(drop=True)
        test = frame.loc[frame.anon_polygon_id.isin(holdout)].reset_index(drop=True)
        print(
            "fold",
            fold,
            "train_fields",
            train.anon_polygon_id.nunique(),
            "test_fields",
            len(holdout),
            flush=True,
        )
        cache = out / f"features_{fold}.joblib"
        if cache.exists():
            pieces, test_examples = joblib.load(cache)
        else:
            pieces = [examples(train, seed) for seed in [142, 243, 344, 445, 546, 647]]
            test_examples = examples(test, 9001 + fold)
            joblib.dump((pieces, test_examples), cache)
        x = pd.concat([p[0] for p in pieces], ignore_index=True)
        y = np.concatenate([p[1] for p in pieces])
        labels = np.concatenate([p[2] for p in pieces])
        tx, ty, _ = test_examples
        base_columns = [
            c
            for c in x
            if c not in set(x.columns) - set(build_features(train.head(1)).columns)
        ]
        # Старая и новая модели оцениваются на одних и тех же строках.
        old_columns = [
            c
            for c in base_columns
            if not c.startswith("phase_")
            and not c.endswith(("_date_fraction", "_season_fraction"))
        ]
        old = HistGradientBoostingRegressor(
            max_iter=350,
            max_leaf_nodes=23,
            l2_regularization=10,
            learning_rate=0.045,
            random_state=42,
        )
        ox, oy, _ = pieces[0]
        ol, _ = baselines(ox)
        old.fit(ox[old_columns], oy - ol)
        tl, _ = baselines(tx)
        old_prediction = np.clip(tl + old.predict(tx[old_columns]), -1, 1)
        current = HistGradientBoostingRegressor(
            max_iter=500,
            max_leaf_nodes=31,
            l2_regularization=20,
            learning_rate=0.035,
            random_state=42,
        )
        linear, _ = baselines(x)
        current.fit(x[base_columns], y - linear)
        current_prediction = np.clip(tl + current.predict(tx[base_columns]), -1, 1)
        bundle = fit_bundle(x, y, labels)
        joblib.dump(bundle, out / f"bundle_{fold}.joblib")
        general, source = predict_bundle(bundle, tx)
        predictions = {
            "old_recipe": old_prediction,
            "v14": current_prediction,
            "extended": general,
            "experts": source,
        }
        for w in [0.25, 0.5, 0.75]:
            predictions[f"expert_blend_{w}"] = (1 - w) * general + w * source
        reports[str(fold)] = {
            name: score(ty, pred) for name, pred in predictions.items()
        }
        print(json.dumps(reports[str(fold)]), flush=True)
        truths.append(ty)
        for name, pred in predictions.items():
            pooled.setdefault(name, []).append(pred)
        joblib.dump(
            {"truth": ty, "predictions": predictions, "holdout": holdout},
            out / f"fold_{fold}.joblib",
        )
        (out / "report.json").write_text(json.dumps({"folds": reports}, indent=2))
    aggregate = {
        name: score(np.concatenate(truths), np.concatenate(pred))
        for name, pred in pooled.items()
    }
    report = {
        "folds": reports,
        "aggregate": aggregate,
        "validation": "Four disjoint AOI folds; held-out fields excluded from training features; fresh masks; no private ground truth.",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print("AGGREGATE", json.dumps(aggregate), flush=True)


if __name__ == "__main__":
    main()
