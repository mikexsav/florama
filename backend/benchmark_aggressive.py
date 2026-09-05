"""Проверяет бустинг большей ёмкости на тех же непересекающихся группах полей."""

import argparse
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from source_model import baselines
from benchmark_sources import score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", required=True)
    parser.add_argument("--start-fold", type=int, default=0)
    args = parser.parse_args()
    out = Path(args.cache)
    results = {}
    pooled = {}
    truths = []
    configs = {
        "lgbm63": lambda: LGBMRegressor(
            n_estimators=1400,
            num_leaves=63,
            learning_rate=0.025,
            min_child_samples=35,
            reg_lambda=12,
            colsample_bytree=0.85,
            subsample=0.85,
            subsample_freq=1,
            n_jobs=2,
            random_state=42,
            verbosity=-1,
        ),
        "lgbm127": lambda: LGBMRegressor(
            n_estimators=1800,
            num_leaves=127,
            learning_rate=0.02,
            min_child_samples=25,
            reg_lambda=8,
            colsample_bytree=0.8,
            subsample=0.85,
            subsample_freq=1,
            n_jobs=2,
            random_state=43,
            verbosity=-1,
        ),
        "lgbm31": lambda: LGBMRegressor(
            n_estimators=1800,
            num_leaves=31,
            learning_rate=0.025,
            min_child_samples=45,
            reg_lambda=20,
            colsample_bytree=0.9,
            n_jobs=2,
            random_state=44,
            verbosity=-1,
        ),
        "xgb6": lambda: XGBRegressor(
            n_estimators=1400,
            max_depth=6,
            learning_rate=0.025,
            min_child_weight=20,
            reg_lambda=15,
            colsample_bytree=0.85,
            subsample=0.85,
            tree_method="hist",
            max_bin=256,
            n_jobs=2,
            random_state=42,
            objective="reg:squarederror",
        ),
        "hist127": lambda: HistGradientBoostingRegressor(
            max_iter=1400,
            max_leaf_nodes=127,
            learning_rate=0.025,
            min_samples_leaf=25,
            l2_regularization=12,
            early_stopping=False,
            random_state=42,
        ),
    }
    for fold in range(args.start_fold, 4):
        pieces, (tx, ty, _) = joblib.load(out / f"features_{fold}.joblib")
        x = pd.concat([p[0] for p in pieces], ignore_index=True)
        y = np.concatenate([p[1] for p in pieces])
        linear, _ = baselines(x)
        tl, _ = baselines(tx)
        reference = joblib.load(out / f"fold_{fold}.joblib")["predictions"][
            "expert_blend_0.5"
        ]
        predictions = {"v15": reference}
        for name, factory in configs.items():
            print("fit", fold, name, flush=True)
            model = factory()
            model.fit(x, y - linear)
            prediction = np.clip(tl + model.predict(tx), -1, 1)
            predictions[name] = prediction
            predictions[name + "_blend"] = (reference + prediction) / 2
            print(
                "score",
                fold,
                name,
                json.dumps(score(ty, prediction)),
                "blend",
                json.dumps(score(ty, predictions[name + "_blend"])),
                flush=True,
            )
        values = np.stack([predictions[name] for name in configs], axis=1)
        predictions["boost_ensemble"] = values.mean(axis=1)
        predictions["boost_ensemble_blend"] = (reference + values.mean(axis=1)) / 2
        results[str(fold)] = {
            name: score(ty, pred) for name, pred in predictions.items()
        }
        truths.append(ty)
        for name, pred in predictions.items():
            pooled.setdefault(name, []).append(pred)
        joblib.dump(
            {"truth": ty, "predictions": predictions}, out / f"aggressive_{fold}.joblib"
        )
        (out / "aggressive_report.json").write_text(
            json.dumps({"folds": results}, indent=2)
        )
    all_truth = []
    all_predictions = {}
    for fold in range(4):
        saved = joblib.load(out / f"aggressive_{fold}.joblib")
        all_truth.append(saved["truth"])
        for name, prediction in saved["predictions"].items():
            all_predictions.setdefault(name, []).append(prediction)
    aggregate = {
        name: score(np.concatenate(all_truth), np.concatenate(values))
        for name, values in all_predictions.items()
    }
    (out / "aggressive_report.json").write_text(
        json.dumps({"folds": results, "aggregate": aggregate}, indent=2)
    )
    print("AGGREGATE", json.dumps(aggregate), flush=True)


if __name__ == "__main__":
    main()
