"""Проверяет адаптацию только на видимых значениях целевых полей."""

import argparse
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from reconstruction import masked
from benchmark_sources import examples, score
from source_model import baselines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--folds", type=int, nargs="+", default=[0, 1, 2, 3])
    args = parser.parse_args()
    out = Path(args.output)
    frame = pd.read_csv(args.input)
    ids = np.random.default_rng(20260905).permutation(
        sorted(frame.anon_polygon_id.unique())
    )
    results = {}
    all_y = []
    all_predictions = {}
    for fold, holdout in enumerate(np.array_split(ids, 4)):
        if fold not in args.folds:
            continue
        cache = out / f"features_{fold}.joblib"
        if not cache.exists():
            continue
        pieces, (tx, ty, _) = joblib.load(cache)
        print("adaptation", fold, flush=True)
        test = frame.loc[frame.anon_polygon_id.isin(holdout)].reset_index(drop=True)
        # Маска совпадает с benchmark_sources и удаляется ДО построения примеров
        # адаптации вместе со спутниковыми и погодными значениями этих строк.
        eval_mask = test.primary_ndvi.between(-1, 1).to_numpy() & (
            np.random.default_rng(9001 + fold).random(len(test)) < 0.15
        )
        visible = masked(test, eval_mask)
        adapt_cache = out / f"adaptation_features_{fold}.joblib"
        if adapt_cache.exists():
            adaptive = joblib.load(adapt_cache)
        else:
            adaptive = [
                examples(visible, seed) for seed in [771, 882, 993, 1104, 1215, 1326]
            ]
            joblib.dump(adaptive, adapt_cache)
        x = pd.concat([p[0] for p in pieces], ignore_index=True)
        y = np.concatenate([p[1] for p in pieces])
        ax = pd.concat([p[0] for p in adaptive], ignore_index=True)
        ay = np.concatenate([p[1] for p in adaptive])
        base = HistGradientBoostingRegressor(
            max_iter=600,
            max_leaf_nodes=31,
            l2_regularization=20,
            learning_rate=0.035,
            early_stopping=False,
            random_state=42,
        )
        linear, _ = baselines(x)
        tl, _ = baselines(tx)
        base.fit(x, y - linear)
        bp = np.clip(tl + base.predict(tx), -1, 1)
        predictions = {"base": bp}
        for weight in [1, 3]:
            xx = pd.concat([x, ax], ignore_index=True)
            yy = np.r_[y, ay]
            ll, _ = baselines(xx)
            model = HistGradientBoostingRegressor(
                max_iter=600,
                max_leaf_nodes=31,
                l2_regularization=20,
                learning_rate=0.035,
                early_stopping=False,
                random_state=42,
            )
            model.fit(
                xx,
                yy - ll,
                sample_weight=np.r_[np.ones(len(x)), np.full(len(ax), weight)],
            )
            pred = np.clip(tl + model.predict(tx), -1, 1)
            predictions[f"adapt_{weight}"] = pred
            predictions[f"blend_{weight}"] = (bp + pred) / 2
        results[str(fold)] = {k: score(ty, v) for k, v in predictions.items()}
        print(json.dumps(results[str(fold)]), flush=True)
        all_y.append(ty)
        for name, pred in predictions.items():
            all_predictions.setdefault(name, []).append(pred)
        (out / "adaptation_report.json").write_text(
            json.dumps({"folds": results}, indent=2)
        )
    aggregate = {
        k: score(np.concatenate(all_y), np.concatenate(v))
        for k, v in all_predictions.items()
    }
    report = {
        "folds": results,
        "aggregate": aggregate,
        "validation": "Evaluation rows permanently masked before adaptation; only visible test-field labels used.",
    }
    (out / "adaptation_report.json").write_text(json.dumps(report, indent=2))
    print("AGGREGATE", json.dumps(aggregate), flush=True)


if __name__ == "__main__":
    main()
