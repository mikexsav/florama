"""Проверяет адаптацию по полям с навсегда удалёнными контрольными ответами."""

import argparse
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)
from benchmark_sources import examples, score
from reconstruction import masked
from source_model import baselines


def selected_ids(frame, seed):
    selection = frame.primary_ndvi.between(-1, 1).to_numpy() & (
        np.random.default_rng(seed).random(len(frame)) < 0.15
    )
    return (
        frame.loc[selection, "anon_polygon_id"]
        .str.split("-")
        .str[-1]
        .astype(int)
        .to_numpy()
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output)
    frame = pd.read_csv(args.input)
    ids = np.random.default_rng(20260905).permutation(
        sorted(frame.anon_polygon_id.unique())
    )
    reports = {}
    ys = []
    preds = {}
    for fold, holdout in enumerate(np.array_split(ids, 4)):
        pieces, (tx, ty, _) = joblib.load(out / f"features_{fold}.joblib")
        reference = joblib.load(out / f"fold_{fold}.joblib")
        print("field_adaptation", fold, flush=True)
        train = frame.loc[~frame.anon_polygon_id.isin(holdout)].reset_index(drop=True)
        test = frame.loc[frame.anon_polygon_id.isin(holdout)].reset_index(drop=True)
        eval_mask = test.primary_ndvi.between(-1, 1).to_numpy() & (
            np.random.default_rng(9001 + fold).random(len(test)) < 0.15
        )
        visible = masked(test, eval_mask)
        ac = out / f"adaptation_features_{fold}.joblib"
        if ac.exists():
            adaptive = joblib.load(ac)
        else:
            adaptive = [
                examples(visible, seed) for seed in [771, 882, 993, 1104, 1215, 1326]
            ]
            joblib.dump(adaptive, ac)
        x = pd.concat([p[0] for p in pieces + adaptive], ignore_index=True)
        y = np.concatenate([p[1] for p in pieces + adaptive])
        labels = np.concatenate([p[2] for p in pieces + adaptive])
        codes = np.concatenate(
            [selected_ids(train, seed) for seed in [142, 243, 344, 445, 546, 647]]
            + [
                selected_ids(visible, seed)
                for seed in [771, 882, 993, 1104, 1215, 1326]
            ]
        )
        x["field_code"] = codes
        tx = tx.copy()
        tx["field_code"] = selected_ids(test, 9001 + fold)
        weights = np.r_[
            np.ones(sum(len(p[1]) for p in pieces)),
            np.full(sum(len(p[1]) for p in adaptive), 3.0),
        ]
        linear, candidates = baselines(x)
        tl, tc = baselines(tx)
        params = dict(
            max_iter=600,
            max_leaf_nodes=31,
            l2_regularization=20,
            learning_rate=0.035,
            early_stopping=False,
            random_state=42,
            categorical_features=["field_code"],
        )
        model = HistGradientBoostingRegressor(**params)
        model.fit(x, y - linear, sample_weight=weights)
        general = np.clip(tl + model.predict(tx), -1, 1)
        classifier = HistGradientBoostingClassifier(
            max_iter=300,
            max_leaf_nodes=15,
            l2_regularization=12,
            learning_rate=0.045,
            early_stopping=False,
            random_state=42,
            categorical_features=["field_code"],
        )
        classifier.fit(x, labels, sample_weight=weights)
        probabilities = classifier.predict_proba(tx)
        experts = []
        for source in range(3):
            selected = labels == source
            xx = x.loc[selected]
            columns = xx.columns[xx.nunique(dropna=True) > 1].tolist()
            expert = HistGradientBoostingRegressor(
                max_iter=500,
                max_leaf_nodes=23,
                l2_regularization=18,
                learning_rate=0.035,
                early_stopping=False,
                random_state=42 + source,
                categorical_features=["field_code"],
            )
            expert.fit(
                xx[columns],
                (y - candidates[:, source])[selected],
                sample_weight=weights[selected],
            )
            experts.append(np.clip(tc[:, source] + expert.predict(tx[columns]), -1, 1))
        source = np.sum(probabilities * np.stack(experts, axis=1), axis=1)
        current = reference["predictions"]["expert_blend_0.5"]
        predictions = {
            "v15": current,
            "field_general": general,
            "field_experts": source,
            "field_blend": (general + source) / 2,
            "mixed": 0.5 * current + 0.25 * general + 0.25 * source,
        }
        joblib.dump(
            {"truth": ty, "predictions": predictions},
            out / f"field_adaptation_{fold}.joblib",
        )
        reports[str(fold)] = {k: score(ty, v) for k, v in predictions.items()}
        print(json.dumps(reports[str(fold)]), flush=True)
        ys.append(ty)
        for name, pred in predictions.items():
            preds.setdefault(name, []).append(pred)
        (out / "field_adaptation_report.json").write_text(
            json.dumps({"folds": reports}, indent=2)
        )
    aggregate = {
        k: score(np.concatenate(ys), np.concatenate(v)) for k, v in preds.items()
    }
    (out / "field_adaptation_report.json").write_text(
        json.dumps({"folds": reports, "aggregate": aggregate}, indent=2)
    )
    print("AGGREGATE", json.dumps(aggregate), flush=True)


if __name__ == "__main__":
    main()
