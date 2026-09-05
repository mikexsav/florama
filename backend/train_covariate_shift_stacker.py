"""Перевзвешивает видимые OOF-примеры под распределение скрытых пропусков."""

import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier

from reconstruction import gap_mask, masked, validate_frame
from train_transductive_stacker import model, predictions, rmse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--oof-cache", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--folds", type=int, default=6)
    args = parser.parse_args()
    frame = pd.read_csv(args.input)
    validate_frame(frame)
    hidden = gap_mask(frame)
    if frame.loc[hidden, "primary_ndvi"].notna().any():
        raise ValueError("Скрытые целевые значения не должны присутствовать.")
    artifact = joblib.load(args.base_model)
    records = [
        joblib.load(Path(args.oof_cache) / f"oof_{fold}.joblib")
        for fold in range(args.folds)
    ]
    clean = masked(frame, hidden)
    final_x, final_base = predictions(artifact, clean)
    hidden_x = final_x.loc[hidden].reset_index(drop=True)
    source_x = pd.concat([record["features"] for record in records], ignore_index=True)
    domain_x = pd.concat([source_x, hidden_x], ignore_index=True)
    domain_y = np.r_[
        np.zeros(len(source_x), dtype=int), np.ones(len(hidden_x), dtype=int)
    ]
    # Баланс доменов превращает отношение шансов в оценку плотностей, а не в
    # отражение разного числа строк двух выборок.
    domain_rows = len(domain_x)
    domain_weight = np.r_[
        np.full(len(source_x), domain_rows / (2 * len(source_x))),
        np.full(len(hidden_x), domain_rows / (2 * len(hidden_x))),
    ]
    classifier = LGBMClassifier(
        n_estimators=450,
        num_leaves=15,
        learning_rate=0.025,
        min_child_samples=80,
        reg_lambda=30,
        reg_alpha=2.0,
        colsample_bytree=0.8,
        n_jobs=4,
        random_state=9300,
        verbosity=-1,
    )
    classifier.fit(
        domain_x,
        domain_y,
        sample_weight=domain_weight,
        categorical_feature=["field_code"],
    )
    probability = np.clip(classifier.predict_proba(source_x)[:, 1], 0.02, 0.98)
    density_weight = np.clip(probability / (1 - probability), 0.15, 8.0)
    # Нормировка стабилизирует регуляризацию; границы сохраняются в диагностике.
    density_weight /= density_weight.mean()
    print(
        "domain",
        {
            "weight_min": float(density_weight.min()),
            "weight_max": float(density_weight.max()),
            "effective_rows": float(
                density_weight.sum() ** 2 / np.sum(density_weight**2)
            ),
        },
        flush=True,
    )
    offsets = np.cumsum([0] + [len(record["target"]) for record in records])
    oof = []
    for fold, test in enumerate(records):
        train_indices = np.concatenate(
            [
                np.arange(offsets[index], offsets[index + 1])
                for index in range(args.folds)
                if index != fold
            ]
        )
        test_indices = np.arange(offsets[fold], offsets[fold + 1])
        train_y = np.concatenate(
            [record["target"] - record["base"] for record in records]
        )[train_indices]
        regressor = model(9400 + fold)
        regressor.fit(
            source_x.iloc[train_indices],
            train_y,
            sample_weight=density_weight[train_indices],
            categorical_feature=["field_code"],
        )
        correction = regressor.predict(test["features"])
        oof.append(
            (test["target"], test["base"], correction, density_weight[test_indices])
        )
    target = np.concatenate([value[0] for value in oof])
    base = np.concatenate([value[1] for value in oof])
    correction = np.concatenate([value[2] for value in oof])
    weights = np.concatenate([value[3] for value in oof])

    def weighted_rmse(prediction):
        return float(np.sqrt(np.average((target - prediction) ** 2, weights=weights)))

    scores = {
        weight: weighted_rmse(np.clip(base + weight * correction, -1, 1))
        for weight in (0.0, 0.15, 0.25, 0.35, 0.5, 0.65, 0.8, 1.0)
    }
    selected_weight = min(scores, key=scores.get)
    print(
        "weighted_oof",
        {
            "base": weighted_rmse(base),
            "scores": scores,
            "selected": selected_weight,
            "unweighted_base": rmse(target, base),
        },
        flush=True,
    )
    target_residual = np.concatenate(
        [record["target"] - record["base"] for record in records]
    )
    final_model = model(9500)
    final_model.fit(
        source_x,
        target_residual,
        sample_weight=density_weight,
        categorical_feature=["field_code"],
    )
    hidden_prediction = np.clip(
        final_base[hidden] + selected_weight * final_model.predict(hidden_x), -1, 1
    )
    result = frame.loc[hidden, ["anon_polygon_id", "date"]].copy()
    result["primary_ndvi_true"] = hidden_prediction
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False, float_format="%.8f")
    joblib.dump(
        {
            "model": final_model,
            "domain": classifier,
            "weight": selected_weight,
            "weighted_oof": scores,
            "density_summary": {
                "min": float(density_weight.min()),
                "max": float(density_weight.max()),
            },
        },
        output.with_suffix(".joblib"),
    )
    print("written", output, "rows", len(result), flush=True)


if __name__ == "__main__":
    main()
